# Evaluations

Three cases, run against the submitted commit. Written before running, observed results recorded from an actual run.

| Case | Input | Expected behavior | Observed result | Pass / fail | Evidence |
| --- | --- | --- | --- | --- | --- |
| Intended | `demo/input/personalized-outreach.json` (`company_url: https://cal.com`, live scrape, sender pre-filled for this demo) | `scripts/scrape_company.py` returns a sourced fact, then `scripts/generate_email.py` produces a grounded email with subject, body, evidence ledger, and claim audit; exit code 0 | Ran the full pipeline end to end: the scraper returned a genuine, sourced fact from `cal.com`, and the generator produced a subject, body, evidence ledger, and claim audit citing it; exited 0. Sender-asking behavior for a general (non-demo-fixture) invocation is separately verified in `evals/run_evals.py` → `sender_completion_flow` | Pass | `demo/output/personalized-outreach.json` (captured from this exact run); `evals/run_evals.py` → `PASS success_grounded_draft (exit 0)` |
| Insufficient evidence | `evals/test_companies.json` → `insufficient_evidence` (empty `facts` array) | Skill abstains instead of guessing; returns failure JSON with a stated reason; exit code 3 | Returned failure JSON stating "facts is empty"; no draft produced; exited 3 | Pass | `evals/run_evals.py` → `PASS insufficient_evidence (exit 3)` |
| Failure / exclusion / safety | `evals/test_companies.json` → `excluded_unlisted_fact_source` (a fact's `source` is not listed in `source_urls`) | Skill refuses malformed/unverifiable input rather than drafting from an unlisted source; exit code 2 | Rejected the input as invalid because the fact's source did not match a declared `source_urls` entry; exited 2 | Pass | `evals/run_evals.py` → `PASS excluded_unlisted_fact_source (exit 2)` |

Additional checks in the same run (`cli_pretty_strict_parity`, three tone variants, `contact_name_fallback`, `banned_phrase_mutation`) also passed; the full transcript is reproducible by running `python3 evals/run_evals.py` from the repository root.

Separately verified: `scripts/scrape_company.py --url https://this-domain-should-not-resolve-xyz123.example --output /tmp/x.json` exits nonzero and writes nothing to `--output`, confirming the orchestrator's silent fallback to `demo/input/personalized-outreach-fixture.json` is actually reachable rather than assumed.

## Run context

- **Agent:** Claude Code (Opus 5), invoking Person B's `scripts/generate_email.py` and `evals/run_evals.py` directly via Python 3
- **When:** 2026-08-28, during the build window, immediately before submission
- **Baseline without the skill:** Not run
