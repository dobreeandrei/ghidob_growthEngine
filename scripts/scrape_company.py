#!/usr/bin/env python3
"""
Scrape public company pages into the normalized evidence shape the
personalized-outreach orchestrator (SKILL.md) consumes.

Interface (fixed, do not change without updating SKILL.md):

    /usr/bin/python3 scripts/scrape_company.py --url <company-url> --output <temporary-json-path>

On success: writes a JSON object to --output containing exactly
company_name, company_domain, source_urls, facts -- and exits 0.
On any failure (nothing usable scraped): writes nothing to --output
and exits nonzero, so the orchestrator falls back to asking for a
local JSON file instead of guessing.

Standard library only -- no third-party imports, no pip install.
Uses Apify (apify/website-content-crawler) when APIFY_TOKEN is set;
otherwise falls back to a plain direct HTTP fetch of the same
candidate pages, so this remains testable with no account at all.
This script has no sender-profile logic and is not used by the
jury path, which reads the committed demo/input file directly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

ACTOR_ID = "apify~website-content-crawler"
RUN_SYNC_URL = f"https://api.apify.com/v2/actors/{ACTOR_ID}/run-sync-get-dataset-items"
LIVE_TIMEOUT_SECONDS = 25
DIRECT_TIMEOUT_SECONDS = 8
MIN_USABLE_TEXT_CHARS = 40
MAX_FACT_TEXT_CHARS = 400
MIN_SENTENCE_LINE_CHARS = 30
SENTENCE_PUNCTUATION_RE = re.compile(r"[.!?]")

CANDIDATE_PATHS = ["", "/jobs", "/careers", "/about", "/news", "/blog"]

CATEGORY_BY_PATH = {
    "/jobs": "hiring",
    "/careers": "hiring",
    "/about": "leadership",
    "/news": "news",
    "/blog": "news",
}

SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
BLOCK_BOUNDARY_RE = re.compile(
    r"</?(p|div|li|h[1-6]|br|tr|td|section|article|header|footer|nav|main|ul|ol|blockquote)\b[^>]*>",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")
MD_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
WHITESPACE_RE = re.compile(r"[ \t]+")
BLANK_LINES_RE = re.compile(r"\n{3,}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape public company pages into normalized evidence JSON.")
    parser.add_argument("--url", required=True, help="A public HTTP/HTTPS company URL, e.g. the homepage.")
    parser.add_argument("--output", required=True, help="Path to write the resulting JSON evidence file.")
    return parser.parse_args(argv)


def candidate_urls(base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    urls = []
    seen = set()
    for path in CANDIDATE_PATHS:
        url = base_url if path == "" else urljoin(root + "/", path.lstrip("/"))
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def fetch_via_apify(urls: list[str], token: str) -> dict[str, str]:
    run_input = {
        "startUrls": [{"url": u} for u in urls],
        "crawlerType": "cheerio",
        "maxCrawlDepth": 0,
        "maxCrawlPages": len(urls),
        "saveMarkdown": True,
    }
    request = urllib.request.Request(
        f"{RUN_SYNC_URL}?token={token}",
        data=json.dumps(run_input).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=LIVE_TIMEOUT_SECONDS) as response:
        items = json.loads(response.read().decode("utf-8"))
    pages: dict[str, str] = {}
    for item in items:
        url = item.get("url", "")
        text = (item.get("markdown") or "").strip()
        if url and text:
            pages[url] = text
    return pages


def strip_html(html: str) -> str:
    text = SCRIPT_STYLE_RE.sub(" ", html)
    text = COMMENT_RE.sub(" ", text)
    text = BLOCK_BOUNDARY_RE.sub("\n", text)
    text = TAG_RE.sub(" ", text)
    text = re.sub(r"&nbsp;|&amp;|&#\d+;|&[a-zA-Z]+;", " ", text)
    return text


def fetch_via_direct_http(urls: list[str]) -> dict[str, str]:
    pages: dict[str, str] = {}
    for url in urls:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; scrape_company/1.0)"})
            with urllib.request.urlopen(request, timeout=DIRECT_TIMEOUT_SECONDS) as response:
                raw = response.read().decode("utf-8", errors="replace")
            text = strip_html(raw)
            pages[url] = text
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            continue
    return pages


STOPWORDS = {"the", "a", "an", "is", "are", "for", "to", "and", "of", "with"}


def is_content_line(line: str) -> bool:
    if line.startswith("#"):
        return True
    if len(line) >= MIN_SENTENCE_LINE_CHARS:
        return True
    return bool(SENTENCE_PUNCTUATION_RE.search(line))


def reads_as_a_sentence(text: str) -> bool:
    words = {w.casefold() for w in re.findall(r"[A-Za-z']+", text)}
    return bool(words & STOPWORDS)


def content_lines(text: str) -> list[str]:
    text = MD_LINK_RE.sub(r"\1", text)
    text = WHITESPACE_RE.sub(" ", text)
    text = BLANK_LINES_RE.sub("\n\n", text)
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line and is_content_line(line)]
    deduped: list[str] = []
    seen_lines: set[str] = set()
    for line in lines:
        key = line.casefold()
        if key in seen_lines:
            continue
        seen_lines.add(key)
        deduped.append(line)
    return deduped


def category_for(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    for suffix, category in CATEGORY_BY_PATH.items():
        if path.endswith(suffix) and path:
            return category
    return "other"


def guess_company_name(base_url: str, homepage_text: str) -> str:
    domain = urlparse(base_url).netloc
    domain = domain[4:] if domain.startswith("www.") else domain
    fallback = domain.split(".")[0].capitalize() if domain else "The company"

    for raw_line in homepage_text.splitlines():
        line = raw_line.strip().lstrip("#").strip()
        if not line:
            continue
        candidate = line.split("|")[0].strip()
        if 2 <= len(candidate) <= 60 and not candidate.lower().startswith(("sign in", "get started")):
            return candidate
    return fallback


def build_facts(pages: dict[str, str]) -> list[dict[str, str]]:
    facts = []
    for url, raw_text in pages.items():
        lines = content_lines(raw_text)
        if not lines:
            continue
        # Real page content tends to be one coherent, longer line; short nav
        # labels and menu items are the noise a plain regex parser can't
        # otherwise tell apart from content on a script-heavy single-page site.
        longest = max(lines, key=len)
        if len(longest) < MIN_USABLE_TEXT_CHARS or not reads_as_a_sentence(longest):
            continue
        excerpt = longest[:MAX_FACT_TEXT_CHARS].rstrip()
        facts.append({"text": excerpt, "source": url, "category": category_for(url)})
    return facts


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    parsed = urlparse(args.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        print(f"error: --url must be an absolute http(s) URL, got {args.url!r}", file=sys.stderr)
        return 2

    urls = candidate_urls(args.url)
    token = os.environ.get("APIFY_TOKEN")
    pages: dict[str, str] = {}

    if token:
        try:
            pages = fetch_via_apify(urls, token)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            pages = {}

    if not pages:
        pages = fetch_via_direct_http(urls)

    facts = build_facts(pages)
    if not facts:
        print(f"error: no usable public content found for {args.url}", file=sys.stderr)
        return 1

    homepage_text = pages.get(args.url, next(iter(pages.values()), ""))
    result = {
        "company_name": guess_company_name(args.url, homepage_text),
        "company_domain": parsed.netloc[4:] if parsed.netloc.startswith("www.") else parsed.netloc,
        "source_urls": [fact["source"] for fact in facts],
        "facts": facts,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
