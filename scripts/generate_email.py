#!/usr/bin/env python3
"""Generate a deterministic, grounded outreach draft from local JSON input."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


EXIT_SUCCESS = 0
EXIT_INVALID_INPUT = 2
EXIT_INSUFFICIENT_EVIDENCE = 3

ROOT = Path(__file__).resolve().parents[1]
BANNED_PHRASES_PATH = ROOT / "references" / "banned_phrases.md"

TOP_LEVEL_KEYS = {
    "company_name",
    "company_domain",
    "source_urls",
    "facts",
    "contact",
    "sender",
    "preferences",
}
FACT_KEYS = {"text", "source", "category"}
CONTACT_KEYS = {"name", "role", "email"}
SENDER_KEYS = {"name", "role", "offer", "call_to_action"}
PREFERENCE_KEYS = {"tone", "max_words"}
FACT_CATEGORIES = {"product", "hiring", "news", "technology", "leadership", "other"}
TONES = {"professional", "direct", "friendly"}
WORD_PATTERN = re.compile(r"\b[\w’'-]+\b", re.UNICODE)


class InputError(ValueError):
    """Raised when input does not match the locked schema."""


class CliError(ValueError):
    """Raised when command-line arguments are invalid."""


def failure(reason: str, code: int) -> tuple[dict[str, Any], int]:
    return (
        {
            "status": "failure",
            "subject": None,
            "email_body": None,
            "evidence_ledger": [],
            "claim_audit": [],
            "limitations": [
                reason,
                "No outreach draft was produced or sent.",
            ],
        },
        code,
    )


def require_object(value: Any, path: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"{path} must be an object")
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        details = []
        if missing:
            details.append(f"missing {missing}")
        if extra:
            details.append(f"unexpected {extra}")
        raise InputError(f"{path} has invalid fields: {', '.join(details)}")
    return value


def require_contact_object(value: Any) -> dict[str, Any]:
    """Validate contact fields while allowing the new target email to be omitted."""
    if not isinstance(value, dict):
        raise InputError("contact must be an object")
    actual = set(value)
    required = {"name", "role"}
    missing = sorted(required - actual)
    extra = sorted(actual - CONTACT_KEYS)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing {missing}")
        if extra:
            details.append(f"unexpected {extra}")
        raise InputError(f"contact has invalid fields: {', '.join(details)}")
    return value


def require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{path} must be a nonempty string")
    if any(ord(character) < 32 and character not in "\t" for character in value):
        raise InputError(f"{path} contains a control character")
    return value.strip()


def require_nullable_string(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return require_string(value, path)


def require_url(value: Any, path: str) -> str:
    url = require_string(value, path)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InputError(f"{path} must be an absolute HTTP or HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise InputError(f"{path} must not contain credentials")
    return url


def validate_input(raw: Any) -> dict[str, Any]:
    data = require_object(raw, "input", TOP_LEVEL_KEYS)
    company_name = require_string(data["company_name"], "company_name")
    company_domain = require_string(data["company_domain"], "company_domain")

    if not isinstance(data["source_urls"], list):
        raise InputError("source_urls must be an array")
    source_urls = [
        require_url(url, f"source_urls[{index}]")
        for index, url in enumerate(data["source_urls"])
    ]
    if not source_urls:
        raise InputError("source_urls must contain at least one URL")

    if not isinstance(data["facts"], list):
        raise InputError("facts must be an array")
    facts = []
    for index, raw_fact in enumerate(data["facts"]):
        fact = require_object(raw_fact, f"facts[{index}]", FACT_KEYS)
        text = require_string(fact["text"], f"facts[{index}].text")
        source = require_url(fact["source"], f"facts[{index}].source")
        category = require_string(fact["category"], f"facts[{index}].category")
        if source not in source_urls:
            raise InputError(
                f"facts[{index}].source {source!r} is not listed in source_urls; "
                f"each fact source must exactly match one of {len(source_urls)} declared URL(s)"
            )
        if category not in FACT_CATEGORIES:
            raise InputError(f"facts[{index}].category is not allowed")
        facts.append({"text": text, "source": source, "category": category})

    contact = require_contact_object(data["contact"])
    contact_name = require_nullable_string(contact["name"], "contact.name")
    contact_role = require_nullable_string(contact["role"], "contact.role")
    contact_email = require_nullable_string(contact.get("email"), "contact.email")

    sender = require_object(data["sender"], "sender", SENDER_KEYS)
    clean_sender = {
        key: require_string(sender[key], f"sender.{key}") for key in sorted(SENDER_KEYS)
    }

    preferences = require_object(data["preferences"], "preferences", PREFERENCE_KEYS)
    tone = require_string(preferences["tone"], "preferences.tone")
    if tone not in TONES:
        raise InputError("preferences.tone is not allowed")
    max_words = preferences["max_words"]
    if isinstance(max_words, bool) or not isinstance(max_words, int):
        raise InputError("preferences.max_words must be an integer")
    if max_words < 1 or max_words > 150:
        raise InputError("preferences.max_words must be between 1 and 150")

    return {
        "company_name": company_name,
        "company_domain": company_domain,
        "source_urls": source_urls,
        "facts": facts,
        "contact": {
            "name": contact_name,
            "role": contact_role,
            "email": contact_email,
        },
        "sender": clean_sender,
        "preferences": {"tone": tone, "max_words": max_words},
    }


def load_banned_phrases() -> list[str]:
    phrases = []
    for line in BANNED_PHRASES_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            phrase = stripped[2:].strip().casefold()
            if phrase:
                phrases.append(phrase)
    if not phrases:
        raise RuntimeError("the banned phrase list is empty")
    return phrases


def contains_banned_phrase(text: str, banned_phrases: list[str]) -> bool:
    lowered = text.casefold()
    return any(phrase in lowered for phrase in banned_phrases)


def word_count(text: str) -> int:
    return len(WORD_PATTERN.findall(text))


def tone_parts(
    tone: str, contact_name: str | None, contact_role: str | None
) -> tuple[str, str, str | None, str]:
    greeting = f"Hi {contact_name}," if contact_name else "Hi,"
    if tone == "friendly":
        return (
            greeting,
            "I came across this:",
            f"With your {contact_role} role in mind, I thought I'd reach out."
            if contact_role
            else None,
            "Best,",
        )
    if tone == "direct":
        return (
            greeting,
            "Saw that",
            f"I'm reaching out to you in your {contact_role} role."
            if contact_role
            else None,
            "Thanks,",
        )
    return (
        greeting,
        "I noticed that",
        f"Given your {contact_role} role, I wanted to reach out."
        if contact_role
        else None,
        "Regards,",
    )


def build_subject(tone: str, company_name: str, category: str) -> str:
    contexts = {
        "product": "product",
        "hiring": "hiring",
        "news": "company news",
        "technology": "technology",
        "leadership": "leadership",
        "other": "company note",
    }
    context = contexts[category]
    if tone == "friendly":
        if category == "other":
            return f"A note for {company_name}"
        return f"{context.capitalize()} at {company_name}"
    if tone == "direct":
        return f"{company_name}: {context}"
    return f"{company_name} — {context}"


def build_draft(data: dict[str, Any], banned_phrases: list[str]) -> tuple[dict[str, Any], int]:
    if not data["facts"]:
        return failure(
            "Insufficient evidence: facts is empty; provide at least one fact with "
            "nonempty text, an allowed category, and a source listed in source_urls.",
            EXIT_INSUFFICIENT_EVIDENCE,
        )

    contact_name = data["contact"]["name"]
    contact_role = data["contact"]["role"]
    tone = data["preferences"]["tone"]
    greeting, fact_lead, role_line, signoff = tone_parts(
        tone, contact_name, contact_role
    )
    sender = data["sender"]
    blocked_by_phrases = 0
    blocked_by_length: list[int] = []

    for fact in data["facts"]:
        subject = build_subject(tone, data["company_name"], fact["category"])
        role_paragraph = f"\n\n{role_line}" if role_line else ""
        body = (
            f"{greeting}\n\n"
            f"{fact_lead} {fact['text']} [1]"
            f"{role_paragraph}\n\n"
            f"I'm {sender['name']}, {sender['role']}. {sender['offer']}\n\n"
            f"{sender['call_to_action']}\n\n"
            f"{signoff}\n{sender['name']}"
        )
        if contains_banned_phrase(subject, banned_phrases) or contains_banned_phrase(
            body, banned_phrases
        ):
            blocked_by_phrases += 1
            continue
        count = word_count(body)
        if count > data["preferences"]["max_words"] or count >= 150:
            blocked_by_length.append(count)
            continue
        claim_mapping = {
            "claim": fact["text"],
            "supported_by_fact": fact["text"],
            "source": fact["source"],
        }
        return (
            {
                "subject": subject,
                "email_body": body,
                "evidence_ledger": [
                    {
                        "marker": "[1]",
                        "outreach_claim": fact["text"],
                        "supporting_fact_text": fact["text"],
                        "source": fact["source"],
                        "category": fact["category"],
                        "support_relationship": "verbatim",
                    }
                ],
                "claim_audit": [claim_mapping],
                "limitations": [
                    "Review-only draft; no message was sent.",
                    "The company-specific statement is copied verbatim from supplied fact [1].",
                    "Sender, contact, and offer details are user-provided and were not independently verified.",
                    "The locked input schema has no retrieval-date field, so no retrieval date was inferred.",
                ],
            },
            EXIT_SUCCESS,
        )

    reasons = []
    if blocked_by_phrases:
        reasons.append(
            f"{blocked_by_phrases} fact candidate(s) produced a banned phrase in the subject or body"
        )
    if blocked_by_length:
        reasons.append(
            f"{len(blocked_by_length)} fact candidate(s) produced {min(blocked_by_length)} "
            f"words or more; preferences.max_words is {data['preferences']['max_words']} "
            "and the hard limit is fewer than 150 words"
        )
    return failure(
        "Blocked draft: " + "; ".join(reasons) + ".",
        EXIT_INSUFFICIENT_EVIDENCE,
    )


def read_input(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise InputError(
            f"cannot read input file {path!r}: {error.strerror or error}"
        ) from error
    except json.JSONDecodeError as error:
        raise InputError(
            f"input file {path!r} is not valid JSON at line {error.lineno}, "
            f"column {error.colno}: {error.msg}"
        ) from error


def render_human(result: dict[str, Any], target_email: str | None) -> str:
    """Render a reviewable result without changing the machine-readable payload."""
    lines = [f"Target: {target_email or 'not provided'}"]
    if result.get("status") == "failure":
        lines.extend(["Status: failure", "", "Limitations:"])
        lines.extend(f"- {item}" for item in result["limitations"])
        return "\n".join(lines)

    lines.extend(
        [
            f"Subject: {result['subject']}",
            "",
            result["email_body"],
            "",
            "Evidence:",
        ]
    )
    for item in result["evidence_ledger"]:
        lines.extend(
            [
                f"- {item['marker']} {item['supporting_fact_text']}",
                f"  Source: {item['source']}",
            ]
        )
    lines.append("")
    lines.append("Limitations:")
    lines.extend(f"- {item}" for item in result["limitations"])
    return "\n".join(lines)


def parse_cli(argv: list[str]) -> tuple[str, bool, bool, bool]:
    input_path = None
    pretty = False
    strict = False
    json_output = False
    for argument in argv[1:]:
        if argument == "--pretty":
            pretty = True
        elif argument == "--strict":
            strict = True
        elif argument == "--json":
            json_output = True
        elif argument.startswith("-"):
            raise CliError(
                f"unknown option {argument!r}; allowed options are --json, --pretty, and --strict"
            )
        elif input_path is None:
            input_path = argument
        else:
            raise CliError(
                f"expected exactly one input JSON path, but also received {argument!r}"
            )
    if input_path is None:
        raise CliError(
            "missing input JSON path; usage: generate_email.py "
            "[--json] [--pretty] [--strict] <input.json>"
        )
    return input_path, pretty, strict, json_output


def main(argv: list[str]) -> int:
    pretty = "--pretty" in argv[1:]
    json_output = "--json" in argv[1:]
    target_email = None
    try:
        input_path, pretty, _strict, json_output = parse_cli(argv)
        data = validate_input(read_input(input_path))
        target_email = data["contact"]["email"]
        result, code = build_draft(data, load_banned_phrases())
    except CliError as error:
        result, code = failure(f"Invalid command line: {error}.", EXIT_INVALID_INPUT)
    except InputError as error:
        result, code = failure(f"Invalid input: {error}.", EXIT_INVALID_INPUT)
    except (OSError, RuntimeError) as error:
        result, code = failure(f"Generator configuration error: {error}.", EXIT_INVALID_INPUT)
    if json_output:
        formatting = {"indent": 2} if pretty else {"separators": (",", ":")}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, **formatting))
    else:
        print(render_human(result, target_email))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
