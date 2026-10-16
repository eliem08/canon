# MCP Readiness Audit: scope (draft v0.1)

*Draft for the founder. Items marked **[FOUNDER DECISION]** are not decided. Capabilities marked
**(not built yet)** depend on roadmap tasks in `docs/STATUS.md` §5 and must not be promised to a client until they land.*

## The offer in one sentence
In about two weeks, using an export of your CRM, team chat and contracts, we measure how accurately an AI agent can answer
questions about your customers today, find what breaks it (duplicates, stale and conflicting facts, permission gaps), and show the
accuracy with a resolved, permission-aware data layer (Canon), backed by evidence for every number.

## What the client receives
1. **Readiness report** (PDF + markdown):
   - Customer duplicates found, and how many records merge into each customer.
   - Conflicting and stale facts, by field (owner, contract value, renewal date, address), with the winning value, the alternatives and their sources.
   - **Quarantine list:** values in their data that could not be read safely (ambiguous amounts, impossible dates, malformed phones), each with its raw text and location.
   - Permission map: which sources each role can see, and where answers differ by role.
2. **Before/after accuracy:** the client's own questions answered by the same model on raw exports vs. through Canon, per question type, with 95% confidence intervals, a strong baseline and every miss listed.
3. **Prioritized fix list:** the 10 data-quality issues that cost the most agent accuracy, with owners and effort.
4. *(Optional, [FOUNDER DECISION])* A working MCP server over their data for a 2-week trial, run in their environment.

## What we need from the client
See [`DATA_REQUEST.md`](DATA_REQUEST.md). In short:
- A CRM accounts export.
- A chat export (Slack, or whatever they really use).
- 50–200 contracts.
- Who can see what.
- 30–50 real questions with answers their team agrees on.
- One technical contact (2–3 hours in total).

## How it runs
- **Offline batch, not a hosted product.** We ingest an export, run resolution and scoring, and produce the report. There is no live connection to their systems.
- **Where the data is processed [FOUNDER DECISION]:**
  - (A) On the client's machine or VPC. We ship a container and run it with them. This is the strongest data posture. A container image runs ingestion with `--network none` ([`DEPLOY.md`](DEPLOY.md)).
  - (B) On our infrastructure under a signed DPA, with deletion at the end.
- **Third-party LLMs** are used only with written consent. Otherwise the eval uses a model the client hosts behind an OpenAI-compatible API (`--model openai-compatible --base-url ...`), and no data leaves their network. Ingestion, resolution and serving use no LLM at all.

## Proposed timeline (10 working days) [FOUNDER DECISION]

| Day | Step |
|---|---|
| 0 | Kickoff (1 h). Agree on the question set and the success criteria. Data handed over. |
| 1–3 | Ingest and resolve. Quarantine report sent to the client so they can fix or confirm entries. |
| 4–6 | Client confirms disputed merges and facts (≤ 2 h of their time). Baseline and Canon eval runs. |
| 7–9 | Report drafted. Review call. |
| 10 | Final report and readout (1 h). |

## Acceptance criteria (agreed at kickoff)
- Every number in the report traces to a source record or an eval run the client can rerun.
- The before/after eval uses only questions the client wrote or approved.
- **No silent wrong values:** every extracted value is either cited to its source or listed in the quarantine.
- **Data handling** follows the agreed option (A or B), including deletion at the end, confirmed in writing.

## Out of scope
- Live connectors, a production deployment, SSO, or a UI.
- Data cleanup in the client's systems (we report it; they fix it).
- Sources beyond the three agreed types.
- **Handwritten or badly degraded scans.** Canon reads PDFs (text layer or OCR), DOCX and images, but OCR accuracy is measured only on synthetic renders so far. Poor scans are listed as unreadable or low-confidence, not guessed.

## Pricing [FOUNDER DECISION]
The goal says $5–15k. One way to split it, for discussion only:
- **Core: about $5–7k.** CRM + one chat source + ≤ 100 text-based contracts, 30 questions.
- **Extended: about $10–15k.** Adds scanned and Arabic contracts (OCR built; accuracy on real scans to be measured on day 1), a second chat source, 50+ questions, and the 2-week MCP trial.

## Guardrail against the consulting trap
- **Per-client allowance:** connector field mappings and an `IngestConfig` (country, currency, date order).
- **Anything else is a product change:** custom per-client logic must instead ship as a reusable change to `canon/`.
- **Tracking:** we count client-specific lines per audit and stop if they exceed 30% (the Goal 4 metric).
