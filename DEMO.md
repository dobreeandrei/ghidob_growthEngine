# Run sheet

The organizer presents this repository for you, in 2 minutes, without having seen it before. Write every line for them. Replace every `TODO`. Keep it to one screen.

## Say this — 20 seconds

**Team:** Ghidob (Andrei Ghita, Andrei Dobre)

**Track:** personalized-growth-engines

**Who has the problem:** A founder or SDR at an early-stage B2B SaaS company, doing their own cold outreach

**The job this skill does:** Turns a set of sourced company facts into a short cold email that cites those facts, instead of generic filler

**Boundary — what it never does:** Never sends the email, never claims a fact that isn't present in the supplied evidence, and never fabricates or infers company details beyond the sourced input

## Run this — 60 seconds

1. Codex is open at the repository root.
2. Paste [`demo/seed-prompt.md`](demo/seed-prompt.md).
3. Watch for: the JSON result printed with a `subject`, `email_body` that quotes the sourced fact (Cal.com's Chief of Staff, GTM hiring post), an `evidence_ledger` mapping the claim to its source URL, and `limitations` stating the draft was not sent.
4. If nothing visible after 60 seconds, open the fallback: [`demo/output/personalized-outreach.json`](demo/output/personalized-outreach.json)

## Show this — 25 seconds

**Result:** A ready-to-review cold email draft (subject + body) addressed to Cal.com, referencing their public `/jobs` hiring post as the hook, plus an evidence ledger and claim audit a reviewer can check before sending anything

**Evidence:** The `evidence_ledger` and `claim_audit` fields in the output map the email's one factual claim to its exact source URL (`https://cal.com/jobs`); `limitations` states the draft is unsent and the fact is user-supplied, not independently re-verified at run time

**Fallback output was produced:** 2026-08-28, by running `python3 scripts/generate_email.py --pretty --strict demo/input/personalized-outreach.json` from the repository root against real data retrieved that day from `cal.com/jobs` via the Apify `website-content-crawler` actor

## Evals — 10 seconds

| Case | Result | Where |
| --- | --- | --- |
| Intended | Pass — grounded email produced, exit 0 | [`demo/evals.md`](demo/evals.md) |
| Insufficient evidence | Pass — empty facts abstained with a stated reason, exit 3 | [`demo/evals.md`](demo/evals.md) |
| Failure / exclusion | Pass — fact with an unlisted source was rejected, exit 2 | [`demo/evals.md`](demo/evals.md) |

## Close — 5 seconds

**Reusable on:** Any company for which someone supplies the same JSON schema (company name/domain, source URLs, sourced facts, contact, sender, tone/length preferences) — not limited to Cal.com

**Material limitation:** The skill never browses the web itself; it only drafts from facts a human or upstream pipeline already supplied and sourced, so its output is only as current and accurate as that input
