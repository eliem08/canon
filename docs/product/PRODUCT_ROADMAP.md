# Product roadmap

*Part of the product document set (`docs/product/`). Code claims cite repository paths; market statements are hypotheses unless a source is linked. Written by the agent that built most of the code: treat as a self-assessment, not independent review. Updated 2026-10-30.*

## Smallest sellable product

**"Customer-Data & AI-Readiness Audit"**, delivered in two weeks inside the client's network:

- **Inputs:** the CRM export or a read-only pull, contracts and an optional chat export.
- **Outputs:**
  - an audit report (HTML/PDF);
  - `crm_fixes.csv`, `quarantine.csv` and `renewals.csv`;
  - `review.html`;
  - a week-2 `--compare` report;
  - an optional before/after eval on 30 questions the client writes.

The MCP server is a **trial option**, not the core offer. All of this exists in code today. What's missing is real-data hardening.

## Backlog

| P | Item | Rationale | Acceptance criteria | Depends on | Effort | Risk |
|---|---|---|---|---|---|---|
| **P0** | Merge PR #1 to `main` and tag `v0.2.0` | Shipping from an unmerged branch isn't credible | `main` holds all the work, CI green, tag exists | — | S | Low |
| **P0** | Real-data dry run on a **consented** real or anonymised dataset (founder's own CRM, a friendly company, or a public CRM-like dataset) | Every pilot number so far is synthetic | Intake, audit and review run end to end; issues logged and fixed | Data access | M | **High** |
| **P0** | Data-handling pack: DPA template (GDPR-ready), deletion certificate, answers to a standard security questionnaire (e.g. SIG Lite / CAIQ), reviewed by a lawyer | The gatekeeper will ask | Documents exist; the lawyer has signed off on the position | Lawyer | M | Medium |
| **P0** | Pilot pricing and contract one-pager validated in 5 discovery calls | No price has been tested | ≥3 of 5 prospects accept the price range as plausible | Outreach | S | High |
| **P1** | `canon pilot`: one command running check, audit and an index page | Fewer operator errors on site | One command produces a deliverables folder with an index | — | S | Low |
| **P1** | Dynamics 365 CSV/XLSX column preset, plus HubSpot/Salesforce pull tested against a free developer account | Real APIs are unverified | Pull from a sandbox succeeds and the CSV round-trips | Sandbox accounts | M | Medium |
| **P1** | Correction entry in `review.html`, writing confirmed `facts` | Today corrections are typed into JSON | A user can enter a corrected value; it appears in `overrides.json` | — | S | Low |
| **P1** | Performance: 50k CRM records resolved in under 10 minutes | Mid-market CRMs | Benchmark report at 50k | — | M | Medium |
| **P1** | Run log and progress output, plus `serve` health and metrics endpoints | Supportability on site | `/health` returns 200; a structured log exists | — | S | Low |
| **P2** | Email connector (`.eml`/`.mbox`/PST export) | The source type already exists | Emails become records with lineage | — | M | Medium |
| **P2** | Read ACLs from source sharing (Slack membership exists; add SharePoint/Drive) | Strengthens the permission claim | ACLs derived, not hand-configured | APIs | L | Medium |
| **P2** | Incremental re-runs | Recurring subscription | Re-run time proportional to the change | — | L | Medium |
| **P3** | Hosted multi-tenant SaaS, write-back to the CRM, LLM-based contract reading | Speculative | — | — | L | High |

Done since this backlog was written (see `BUILD_STATUS.md`): merge, `canon pilot`, run record, `/health`, `canon purge`, corrections on the review page, clustering speed-up.

## 30/60/90 days

| Window | Work | Exit criteria |
|---|---|---|
| Days 1–30 | Merge and tag; real-data dry run; legal pack; 20 targeted conversations through 2 integrators and personal network | ≥8 discovery calls; ≥1 dataset run end to end; pricing reaction from ≥5 prospects |
| Days 31–60 | First paid audit (or a paid design partner at a discount); P1 items it surfaces | Signed pilot; audit delivered; client confirms ≥N fixes are real (agree N up front) |
| Days 61–90 | Second paid audit; week-2 `--compare` proof; case study; decide whether to convert to a subscription | 2 paid pilots, ≥1 referenceable; renewal or subscription conversation started |

**Kill or pivot signal at day 60:** fewer than 8 discovery calls, or nobody willing to pay for an audit at any tested price.
