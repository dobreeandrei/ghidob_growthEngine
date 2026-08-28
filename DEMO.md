# Run sheet

The organizer presents this repository for you, in 2 minutes, without having seen it before. Write every line for them. Replace every `TODO`. Keep it to one screen.

## Say this — 20 seconds

**Team:** Ghidob (Andrei Ghita, Andrei Dobre)

**Track:** personalized-growth-engines

**Who has the problem:** A founder or SDR at an early-stage B2B SaaS company, doing their own cold outreach

**The job this skill does:** Scrapes a company's public site live, extracts sourced facts, and turns them into a short cold email that cites those facts, instead of generic filler

**Boundary — what it never does:** Never scrapes or targets a named individual (only a generic role like "Head of Go-to-Market"), never sends the email, never claims a fact that isn't present in the scraped evidence, and never fabricates or infers company details

## Run this — 60 seconds

1. Codex is open at the repository root.
2. Paste [`demo/seed-prompt.md`](demo/seed-prompt.md), which points at `demo/input/personalized-outreach.json` — a company URL (`https://cal.com`) with no sender identity pre-filled.
3. **Be ready to answer**: the skill will ask, in one short message, for your name, role, offer, and call-to-action (it has no idea who you are — that's the point). Answer briefly; it asks once, not back-and-forth.
4. Watch for: the skill running `scripts/scrape_company.py` live against that URL, then the result printed with a `subject`, `email_body` quoting a freshly scraped company fact and your own answers, an `evidence_ledger` mapping the claim to its exact source URL, and `limitations` stating the draft was not sent.
5. If nothing visible after 60 seconds, or the live scrape can't complete, open the fallback: [`demo/output/personalized-outreach.json`](demo/output/personalized-outreach.json) — the skill itself falls back automatically to the committed `demo/input/personalized-outreach-fixture.json` in that case (a scrape failure, unlike a sender question, isn't something the presenter can fix by answering), so it degrades gracefully rather than stalling.

## Show this — 25 seconds

**Result:** A ready-to-review cold email draft (subject + body) addressed to a generic role at Cal.com, built from a fact scraped live from their public site, plus an evidence ledger and claim audit a reviewer can check before sending anything

**Evidence:** The `evidence_ledger` and `claim_audit` fields in the output map the email's one factual claim to its exact scraped source URL; `limitations` states the draft is unsent and the fact was not independently re-verified beyond the scrape itself

**Fallback output was produced:** 2026-08-28, by running the full pipeline manually — `scripts/scrape_company.py --url https://cal.com` followed by `scripts/generate_email.py` on the merged result — from the repository root; this is the same command chain the skill runs live, captured once as a genuine, honest snapshot in case the live run stalls on stage

## Evals — 10 seconds

| Case | Result | Where |
| --- | --- | --- |
| Intended | Pass — grounded email produced, exit 0 | [`demo/evals.md`](demo/evals.md) |
| Insufficient evidence | Pass — empty facts abstained with a stated reason, exit 3 | [`demo/evals.md`](demo/evals.md) |
| Failure / exclusion | Pass — fact with an unlisted source was rejected, exit 2 | [`demo/evals.md`](demo/evals.md) |

## Close — 5 seconds

**Reusable on:** Any public company URL — swap `company_url` in the input for another company's site and it scrapes and drafts the same way, with no schema or code changes; it also accepts a fully pre-supplied facts JSON directly, for when scraping isn't available or desired

**Material limitation:** Without a working Apify connection, the scraper falls back to a plain HTTP fetch that can't render JavaScript-heavy sites cleanly, so fact quality on such sites is best-effort; the skill also never scrapes or targets a specific named individual, only a generic role
