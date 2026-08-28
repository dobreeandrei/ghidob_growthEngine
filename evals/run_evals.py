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
ROBOTIC_EMAIL_PHRASES = ("supplied evidence", "supplied facts", "company evidence")


def load_banned_phrases() -> list[str]:
    return [
        line.strip()[2:].strip().casefold()
        for line in BANNED_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- ")
    ]


def invoke(
    payload: Any,
    directory: Path,
    name: str,
    flags: tuple[str, ...] = (),
) -> tuple[int, dict[str, Any], str, str]:
    input_path = directory / f"{name}.json"
    input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(GENERATOR_PATH), "--json", *flags, str(input_path)],
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
    return completed.returncode, output, completed.stderr, completed.stdout


def invoke_human(
    payload: Any,
    directory: Path,
    name: str,
    flags: tuple[str, ...] = (),
) -> tuple[int, str, str]:
    input_path = directory / f"{name}.json"
    input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(GENERATOR_PATH), *flags, str(input_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def assert_failure(output: dict[str, Any]) -> None:
    assert output["status"] == "failure", output
    assert output["subject"] is None, output
    assert output["email_body"] is None, output
    assert output["evidence_ledger"] == [], output
    assert output["claim_audit"] == [], output
    assert output["limitations"], output


def evaluate_success(case: dict[str, Any], output: dict[str, Any], banned: list[str]) -> None:
    payload = case["input"]
    assert set(output) == {
        "subject",
        "email_body",
        "evidence_ledger",
        "claim_audit",
        "limitations",
    }
    body = output["email_body"]
    assert isinstance(body, str) and body
    count = len(WORD_PATTERN.findall(body))
    assert count <= payload["preferences"]["max_words"], count
    assert count < 150, count
    combined_draft = f"{output['subject']}\n{body}".casefold()
    assert all(phrase not in combined_draft for phrase in banned)
    assert all(phrase not in body.casefold() for phrase in ROBOTIC_EMAIL_PHRASES)

    ledger = output["evidence_ledger"]
    assert len(ledger) == 1, ledger
    item = ledger[0]
    matching_facts = [
        fact
        for fact in payload["facts"]
        if fact["text"] == item["supporting_fact_text"]
        and fact["source"] == item["source"]
        and fact["category"] == item["category"]
    ]
    assert matching_facts, item
    assert item["source"] in payload["source_urls"], item
    assert item["outreach_claim"] == item["supporting_fact_text"], item
    assert item["support_relationship"] == "verbatim", item
    assert item["supporting_fact_text"] in body, "used fact must appear verbatim in body"
    assert item["marker"] in body, "ledger marker must appear in body"
    if item["category"] == "other":
        assert payload["company_name"].casefold() in output["subject"].casefold()
    else:
        assert item["category"] in output["subject"].casefold(), output["subject"]

    audit = output["claim_audit"]
    assert audit == [
        {
            "claim": item["outreach_claim"],
            "supported_by_fact": item["supporting_fact_text"],
            "source": item["source"],
        }
    ], audit
    assert audit[0]["claim"] in body, audit

    company_claims = [fact["text"] for fact in payload["facts"] if fact["text"] in body]
    assert company_claims == [item["supporting_fact_text"]], company_claims


def construct_sender_completion(
    base_input: dict[str, Any], flow: dict[str, Any], remove_declared: bool = True
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    partial = json.loads(json.dumps(base_input))
    if remove_declared:
        for field in flow["remove_top_level_fields"]:
            partial.pop(field, None)

    sender = partial.get("sender") if isinstance(partial.get("sender"), dict) else {}
    preferences = (
        partial.get("preferences")
        if isinstance(partial.get("preferences"), dict)
        else {}
    )
    questions = [
        field
        for field in (
            "sender.name",
            "sender.role",
            "sender.offer",
            "sender.call_to_action",
        )
        if not isinstance(sender.get(field.split(".")[1]), str)
        or not sender[field.split(".")[1]].strip()
    ]
    contact = partial.get("contact") if isinstance(partial.get("contact"), dict) else {}
    if not isinstance(contact.get("email"), str) or not contact["email"].strip():
        questions.append("contact.email")
    if preferences.get("tone") not in {"professional", "direct", "friendly"}:
        questions.append("preferences.tone")

    answers = flow["answers"]
    completed = json.loads(json.dumps(partial))
    completed["sender"] = {
        key: sender.get(key) or answers[f"sender.{key}"]
        for key in ("name", "role", "offer", "call_to_action")
    }
    completed["contact"] = {
        "name": contact.get("name"),
        "role": contact.get("role"),
        "email": contact.get("email"),
    }
    completed["preferences"] = {
        "tone": preferences.get("tone") or answers.get("preferences.tone", "direct"),
        "max_words": preferences.get("max_words", 150),
    }
    return partial, completed, questions


def main() -> int:
    suite = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = suite["cases"]
    banned = load_banned_phrases()
    failures = []
    passed = 0

    with tempfile.TemporaryDirectory(prefix="personalized-outreach-evals-") as temp:
        temp_dir = Path(temp)
        for case in cases:
            try:
                code, output, stderr, stdout = invoke(
                    case["input"], temp_dir, case["name"]
                )
                assert stderr == "", stderr
                assert code == case["expected_exit"], (code, output)
                assert stdout.count("\n") == 1, "--json must be compact by default"
                repeat_code, repeat_output, repeat_stderr, _ = invoke(
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
                        message = output["limitations"][0]
                        assert "facts is empty" in message, message
                        assert "source_urls" in message, message
                    if case["name"] == "excluded_unlisted_fact_source":
                        message = output["limitations"][0]
                        invalid_source = case["input"]["facts"][0]["source"]
                        assert invalid_source in message, message
                        assert "source_urls" in message, message
                print(f"PASS {case['name']} (exit {code})")
                passed += 1
            except (AssertionError, KeyError, TypeError) as error:
                failures.append(f"{case['name']}: {error}")
                print(f"FAIL {case['name']}: {error}")

        success_case = next(case for case in cases if case["expected_exit"] == 0)

        # --strict is an explicit no-op because default validation is already strict;
        # --pretty changes JSON formatting only.
        try:
            default_code, default_output, _, _ = invoke(
                success_case["input"], temp_dir, "cli_default"
            )
            strict_code, strict_output, strict_stderr, strict_stdout = invoke(
                success_case["input"],
                temp_dir,
                "cli_pretty_strict",
                ("--pretty", "--strict"),
            )
            assert strict_stderr == "", strict_stderr
            assert (strict_code, strict_output) == (default_code, default_output)
            assert strict_stdout.count("\n") > 5, "--pretty must indent JSON"
            print("PASS cli_pretty_strict_parity (exit 0)")
            passed += 1
        except (AssertionError, KeyError, TypeError) as error:
            failures.append(f"cli_pretty_strict_parity: {error}")
            print(f"FAIL cli_pretty_strict_parity: {error}")

        # Human-readable output is the default and includes the review target.
        try:
            human_code, human_stdout, human_stderr = invoke_human(
                success_case["input"], temp_dir, "cli_human_default", ("--strict",)
            )
            assert human_stderr == "", human_stderr
            assert human_code == 0, human_stdout
            assert human_stdout.startswith(
                f"Target: {success_case['input']['contact']['email']}\nSubject: "
            ), human_stdout
            assert success_case["input"]["facts"][0]["text"] in human_stdout
            assert "\nEvidence:\n" in human_stdout, human_stdout
            assert "\nLimitations:\n" in human_stdout, human_stdout
            try:
                json.loads(human_stdout)
            except json.JSONDecodeError:
                pass
            else:
                raise AssertionError("default output must not be JSON")
            print("PASS cli_human_default (exit 0)")
            passed += 1
        except (AssertionError, KeyError, TypeError) as error:
            failures.append(f"cli_human_default: {error}")
            print(f"FAIL cli_human_default: {error}")

        # Tone outputs must be observably distinct without changing their evidence.
        tone_outputs = {}
        for tone in suite["tone_regression"]["tones"]:
            tone_payload = json.loads(json.dumps(success_case["input"]))
            tone_payload["preferences"]["tone"] = tone
            try:
                code, output, stderr, _ = invoke(
                    tone_payload, temp_dir, f"tone_{tone}", ("--strict",)
                )
                assert stderr == "", stderr
                assert code == 0, (code, output)
                evaluate_success({"input": tone_payload}, output, banned)
                assert output["email_body"].startswith(
                    f"Hi {tone_payload['contact']['name']},"
                )
                assert tone_payload["contact"]["role"] in output["email_body"]
                tone_outputs[tone] = (output["subject"], output["email_body"])
                print(f"PASS tone_{tone} (exit 0)")
                passed += 1
            except (AssertionError, KeyError, TypeError) as error:
                failures.append(f"tone_{tone}: {error}")
                print(f"FAIL tone_{tone}: {error}")
        try:
            assert len(set(tone_outputs.values())) == 3, tone_outputs
            assert len({value[0] for value in tone_outputs.values()}) == 3, tone_outputs
            print("PASS tone_outputs_distinct")
            passed += 1
        except AssertionError as error:
            failures.append(f"tone_outputs_distinct: {error}")
            print(f"FAIL tone_outputs_distinct: {error}")

        # Missing contact name must always use the exact neutral fallback.
        fallback_payload = json.loads(json.dumps(success_case["input"]))
        fallback_payload["contact"]["name"] = None
        fallback_payload["contact"].pop("email")
        try:
            code, output, stderr, _ = invoke(
                fallback_payload, temp_dir, "contact_name_fallback"
            )
            assert stderr == "", stderr
            assert code == 0, (code, output)
            assert output["email_body"].startswith("Hi,\n"), output["email_body"]
            assert fallback_payload["contact"]["role"] in output["email_body"]
            evaluate_success({"input": fallback_payload}, output, banned)
            human_code, human_stdout, human_stderr = invoke_human(
                fallback_payload, temp_dir, "contact_email_fallback"
            )
            assert human_stderr == "", human_stderr
            assert human_code == 0, human_stdout
            assert human_stdout.startswith("Target: not provided\n"), human_stdout
            print("PASS contact_name_fallback (exit 0)")
            passed += 1
        except (AssertionError, KeyError, TypeError) as error:
            failures.append(f"contact_name_fallback: {error}")
            print(f"FAIL contact_name_fallback: {error}")

        # Simulate Codex collecting missing sender answers without interactive eval I/O.
        flow = suite["sender_completion_flow"]
        flow_base = next(case for case in cases if case["name"] == flow["base_case"])
        try:
            partial, completed, questions = construct_sender_completion(
                flow_base["input"], flow
            )
            assert questions == flow["expected_question_fields"], questions
            assert len(questions) == 6, questions
            assert "sender" not in partial
            assert completed["facts"] == flow_base["input"]["facts"]
            assert completed["source_urls"] == flow_base["input"]["source_urls"]
            defaults = flow["expected_defaults"]
            assert completed["preferences"]["tone"] == defaults["preferences.tone"]
            assert completed["preferences"]["max_words"] == defaults[
                "preferences.max_words"
            ]
            assert completed["contact"]["name"] == defaults["contact.name"]
            assert completed["contact"]["role"] == defaults["contact.role"]
            assert completed["contact"]["email"] == defaults["contact.email"]
            code, output, stderr, _ = invoke(
                completed,
                temp_dir,
                "sender_completion_flow",
                ("--pretty", "--strict"),
            )
            assert stderr == "", stderr
            assert code == 0, (code, output)
            assert output["email_body"].startswith("Hi,\n")
            for field in ("name", "role", "offer", "call_to_action"):
                assert completed["sender"][field] in output["email_body"]
            evaluate_success({"input": completed}, output, banned)
            print("PASS sender_completion_flow (exit 0)")
            passed += 1
        except (AssertionError, KeyError, TypeError) as error:
            failures.append(f"sender_completion_flow: {error}")
            print(f"FAIL sender_completion_flow: {error}")

        # An approved profile reuses sender values and tone, but never target data.
        try:
            profile = {
                "sender": completed["sender"],
                "preferences": {"tone": completed["preferences"]["tone"]},
            }
            assert set(profile) == set(flow["profile_fields"]), profile
            assert set(profile["sender"]) == set(flow["profile_fields"]["sender"])
            assert set(profile["preferences"]) == set(
                flow["profile_fields"]["preferences"]
            )
            assert "contact" not in profile
            assert "company_name" not in profile

            future = json.loads(json.dumps(flow_base["input"]))
            future["sender"] = profile["sender"]
            future["preferences"] = {
                "tone": profile["preferences"]["tone"],
                "max_words": 150,
            }
            future["contact"]["email"] = None
            _, future_completed, future_questions = construct_sender_completion(
                future, flow, remove_declared=False
            )
            assert future_questions == ["contact.email"], future_questions
            assert future_completed["sender"] == profile["sender"]
            print("PASS approved_profile_reuse")
            passed += 1
        except (AssertionError, KeyError, TypeError) as error:
            failures.append(f"approved_profile_reuse: {error}")
            print(f"FAIL approved_profile_reuse: {error}")

        # Adversarial mutation: a banned sender phrase must fail without a draft.
        banned_payload = json.loads(json.dumps(success_case["input"]))
        banned_payload["sender"]["offer"] = "This is a guaranteed results program."
        try:
            code, output, stderr, _ = invoke(
                banned_payload, temp_dir, "banned_phrase_mutation"
            )
            assert stderr == "", stderr
            assert code == 3, (code, output)
            assert_failure(output)
            assert "1 fact candidate(s) produced a banned phrase" in output["limitations"][0]
            print("PASS banned_phrase_mutation (exit 3)")
            passed += 1
        except (AssertionError, KeyError, TypeError) as error:
            failures.append(f"banned_phrase_mutation: {error}")
            print(f"FAIL banned_phrase_mutation: {error}")

        sent_claim_payload = json.loads(json.dumps(success_case["input"]))
        sent_claim_payload["sender"]["call_to_action"] = "This email has been sent."
        try:
            code, output, stderr, _ = invoke(
                sent_claim_payload, temp_dir, "sent_status_claim"
            )
            assert stderr == "", stderr
            assert code == 3, (code, output)
            assert_failure(output)
            print("PASS sent_status_claim_blocked (exit 3)")
            passed += 1
        except (AssertionError, KeyError, TypeError) as error:
            failures.append(f"sent_status_claim_blocked: {error}")
            print(f"FAIL sent_status_claim_blocked: {error}")

    if failures:
        print(f"\n{len(failures)} eval check(s) failed.")
        return 1
    print(f"\nAll {passed} eval checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
