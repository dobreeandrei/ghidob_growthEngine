#!/usr/bin/env python3
"""Run deterministic standard-library evals for personalized outreach."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "test_companies.json"
GENERATOR_PATH = ROOT / "scripts" / "generate_email.py"
BANNED_PATH = ROOT / "references" / "banned_phrases.md"
WORD_PATTERN = re.compile(r"\b[\w’'-]+\b", re.UNICODE)


def load_banned_phrases() -> list[str]:
    return [
        line.strip()[2:].strip().casefold()
        for line in BANNED_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- ")
    ]


def invoke(payload: Any, directory: Path, name: str) -> tuple[int, dict[str, Any], str]:
    input_path = directory / f"{name}.json"
    input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(GENERATOR_PATH), str(input_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        output = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"generator stdout was not JSON: {error}; stderr={completed.stderr!r}"
        ) from error
    return completed.returncode, output, completed.stderr


def assert_failure(output: dict[str, Any]) -> None:
    assert output["status"] == "failure", output
    assert output["subject"] is None, output
    assert output["email_body"] is None, output
    assert output["evidence_ledger"] == [], output
    assert output["limitations"], output


def evaluate_success(case: dict[str, Any], output: dict[str, Any], banned: list[str]) -> None:
    payload = case["input"]
    assert set(output) == {"subject", "email_body", "evidence_ledger", "limitations"}
    body = output["email_body"]
    assert isinstance(body, str) and body
    count = len(WORD_PATTERN.findall(body))
    assert count <= payload["preferences"]["max_words"], count
    assert count < 150, count
    combined_draft = f"{output['subject']}\n{body}".casefold()
    assert all(phrase not in combined_draft for phrase in banned)

    ledger = output["evidence_ledger"]
    assert len(ledger) == 1, ledger
    item = ledger[0]
    matching_facts = [
        fact
        for fact in payload["facts"]
        if fact["text"] == item["fact"]
        and fact["source"] == item["source"]
        and fact["category"] == item["category"]
    ]
    assert matching_facts, item
    assert item["source"] in payload["source_urls"], item
    assert item["fact"] in body, "used fact must appear verbatim in body"
    assert item["marker"] in body, "ledger marker must appear in body"

    company_claims = [fact["text"] for fact in payload["facts"] if fact["text"] in body]
    assert company_claims == [item["fact"]], company_claims


def main() -> int:
    suite = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = suite["cases"]
    banned = load_banned_phrases()
    failures = []

    with tempfile.TemporaryDirectory(prefix="personalized-outreach-evals-") as temp:
        temp_dir = Path(temp)
        for case in cases:
            try:
                code, output, stderr = invoke(case["input"], temp_dir, case["name"])
                assert stderr == "", stderr
                assert code == case["expected_exit"], (code, output)
                repeat_code, repeat_output, repeat_stderr = invoke(
                    case["input"], temp_dir, f"{case['name']}_repeat"
                )
                assert repeat_stderr == "", repeat_stderr
                assert (repeat_code, repeat_output) == (code, output), (
                    repeat_code,
                    repeat_output,
                )
                if code == 0:
                    evaluate_success(case, output, banned)
                else:
                    assert_failure(output)
                    if case["name"] == "insufficient_evidence":
                        assert "Insufficient evidence" in output["limitations"][0]
                    if case["name"] == "excluded_unlisted_fact_source":
                        assert "source_urls" in output["limitations"][0]
                print(f"PASS {case['name']} (exit {code})")
            except (AssertionError, KeyError, TypeError) as error:
                failures.append(f"{case['name']}: {error}")
                print(f"FAIL {case['name']}: {error}")

        # Adversarial mutation: a banned sender phrase must fail without a draft.
        banned_payload = json.loads(json.dumps(cases[0]["input"]))
        banned_payload["sender"]["offer"] = "This is a guaranteed results program."
        try:
            code, output, stderr = invoke(banned_payload, temp_dir, "banned_phrase_mutation")
            assert stderr == "", stderr
            assert code == 3, (code, output)
            assert_failure(output)
            print("PASS banned_phrase_mutation (exit 3)")
        except (AssertionError, KeyError, TypeError) as error:
            failures.append(f"banned_phrase_mutation: {error}")
            print(f"FAIL banned_phrase_mutation: {error}")

    if failures:
        print(f"\n{len(failures)} eval check(s) failed.")
        return 1
    print(f"\nAll {len(cases) + 1} eval checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
