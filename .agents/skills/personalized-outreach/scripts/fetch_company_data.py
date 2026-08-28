#!/usr/bin/env python3
"""
Fetch raw company web content for the personalized-outreach skill.

No third-party imports on purpose: the jury laptop has Python 3 with
nothing pre-installed for this repo, and RULES.md says "nothing gets
installed before your run." Standard library only.

Live mode (APIFY_TOKEN set): calls apify/website-content-crawler via a
single synchronous HTTP request and returns freshly scraped pages.

Offline mode (no APIFY_TOKEN, or the live call fails/times out): loads
a committed cached snapshot instead. This is not a fallback bolted on
for the demo -- it is the only mode the jury laptop can ever run in,
since RULES.md guarantees no credentials are present there.

Usage:
    python3 fetch_company_data.py <company-slug> [url1 url2 ...]

Output (stdout): JSON
    {
      "company": "<slug>",
      "mode": "live" | "cached",
      "retrieved_at": "<ISO8601>",
      "source_urls": [...],
      "items": [{"url": ..., "markdown": ...}, ...]
    }
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

ACTOR_ID = "apify~website-content-crawler"
RUN_SYNC_URL = f"https://api.apify.com/v2/actors/{ACTOR_ID}/run-sync-get-dataset-items"
LIVE_TIMEOUT_SECONDS = 25  # keep well under the 75s seed-prompt budget

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(SCRIPT_DIR, "..", "cache", "sample_outputs")


def fetch_live(company_slug, start_urls, token):
    run_input = {
        "startUrls": [{"url": u} for u in start_urls],
        "crawlerType": "cheerio",
        "maxCrawlDepth": 0,
        "maxCrawlPages": len(start_urls),
        "saveMarkdown": True,
    }
    url = f"{RUN_SYNC_URL}?token={token}"
    req = urllib.request.Request(
        url,
        data=json.dumps(run_input).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=LIVE_TIMEOUT_SECONDS) as resp:
        raw_items = json.loads(resp.read().decode("utf-8"))

    items = [
        {"url": item.get("url", ""), "markdown": item.get("markdown", "")}
        for item in raw_items
    ]
    return items


def load_cached(company_slug):
    cache_path = os.path.join(CACHE_DIR, f"{company_slug}.json")
    if not os.path.exists(cache_path):
        return None
    with open(cache_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: fetch_company_data.py <company-slug> [url1 url2 ...]"}))
        sys.exit(1)

    company_slug = sys.argv[1]
    start_urls = sys.argv[2:]
    token = os.environ.get("APIFY_TOKEN")

    if token and start_urls:
        try:
            items = fetch_live(company_slug, start_urls, token)
            result = {
                "company": company_slug,
                "mode": "live",
                "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_urls": start_urls,
                "items": items,
            }
            print(json.dumps(result, indent=2))
            return
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            pass  # fall through to cache -- never let a live failure block the skill

    cached = load_cached(company_slug)
    if cached is None:
        print(json.dumps({
            "error": f"no cached data for '{company_slug}' and no live token/result available",
            "company": company_slug,
            "mode": "unavailable",
        }))
        sys.exit(1)

    cached["mode"] = "cached"
    print(json.dumps(cached, indent=2))


if __name__ == "__main__":
    main()
