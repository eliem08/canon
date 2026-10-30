# Build status

*Updated 2026-10-30. Every "done" item below was verified by a command run on that date; results are in
`docs/product/TESTING_REPORT.md`. Nothing has been deployed for a client, and no customer has used the product.*

## What the product is now

An on-premise tool for a two-week customer-data and AI-readiness engagement:

1. `canon check`: day-1 intake check of a client export.
2. `canon pilot`: ingest the CRM, chat and contracts, resolve customers, and score every fact. It writes:
   - a dashboard (`index.html`) and the full report;
   - CRM fix files and the review page;
   - a renewal calendar and a run record.
3. Account owners confirm merges and correct values in `review.html`; the next run applies them.
4. `canon pilot --compare`: the week-2 progress report.
5. `canon serve`: the MCP server for AI agents, with permissions applied before scoring.
6. `canon purge`: deletion with a receipt.

## Done in this round

| Change | Verified by |
|---|---|
| PR eliem08/canon#1 merged to `main` (all prior work) | GitHub |
| `canon pilot` with dashboard `index.html` and `run.json` (versions, settings, input hashes) | `tests/test_pilot.py`; screenshots at 390 px and 1200 px |
| `GET /health` on the HTTP server (no auth, no customer data) | `tests/test_security.py` |
| `canon purge`: dry run by default, refuses unsafe folders, deletion receipt | `tests/test_purge.py` |
| Review page: signed, validated value corrections saved into `overrides.json` | `tests/test_review_browser.py` in real Chromium; new CI job |
| Clustering rewritten with a neighbour map: identical output, 47k records in 31 s (was 52 s at 11.8k) | Equivalence check at 3 sizes; `docs/reports/scale_report.md` |
| Security: pillow 12.3.0 → 13.0.0 and pypdf 6.21.0 → 6.21.4 (15 advisories); `pip-audit` CI job | `pip-audit`: no known vulnerabilities |
| Product, engineering and sales document set | `docs/product/`, `docs/sales/` |

## Test results (2026-10-30)

- `uv run pytest -q`: **1263 passed, 1 skipped**. The skipped test is the browser test, which needs Playwright.
- The browser test with Playwright: **1 passed**.
- `ruff check` and `ruff format --check`: clean.
- `pip-audit` on the locked runtime dependencies: no known vulnerabilities.
- Docker image built locally and exercised. With networking off, `pilot` produced 14 files. `serve --http` answered `/health` with 200 and refused a request without a token with 401. `purge --yes` deleted 15 files and wrote a receipt.
- **CI has not run on these commits.** The workflow triggers on pushes to `main` and on pull requests only, and this branch has neither yet.

## Readiness gates

| Gate | Result | Evidence and caveat |
|---|---|---|
| Architecture | **PASS** | `docs/product/PRODUCT_ARCHITECTURE.md`, `TECHNICAL_DESIGN.md` match the code paths cited |
| Core functionality | **PARTIAL** | Every workflow runs end to end on the synthetic export and public datasets; **never run on a real client export** |
| Data | **PASS** | SQLite store rebuilt per run; values validated by refusal-based parsers with adversarial fixtures; human decisions persist in `overrides.json` |
| Frontend | **PARTIAL** | The UI is offline HTML: the dashboard, the report and the review page with forms. It is responsive (checked at 390 px and 1200 px), has a dark mode, and is browser-tested. There is no web app, by design; no formal accessibility audit |
| Backend | **PASS** | CLI and MCP service covered by 1,263 tests |
| Security | **PARTIAL** | Reviewed; vulnerable dependencies fixed; auth and leak tests pass. Accepted risks are listed in `SECURITY_REVIEW.md`. No external penetration test; single sign-on (OIDC) not tested against a real identity provider |
| Testing | **PASS** | Unit, integration, MCP API, auth, end-to-end browser and performance tests executed; results documented |
| Deployment | **PARTIAL** | Image built and run end to end locally (pilot → serve → health → purge); CI builds it on `main`. Not deployed for any client; no published or signed image |
| Operations | **PARTIAL** | Runbook, `/health`, audit log, run record, purge receipt. No metrics or alerting (unnecessary for an operator-run pilot) |
| Documentation | **PASS** | Install, user, operator and developer docs: `README.md`, `docs/DEPLOY.md`, `docs/product/*` |
| Commercial | **PARTIAL** | Positioning, pricing hypotheses, pilot proposal and outreach are written. **No price has been tested with a buyer** |
| Customer readiness | **PARTIAL** | Demo on synthetic data is ready (`docs/sales/DEMO_SCRIPT.md`); onboarding is the data request and intake check. No customer yet |

## Blockers (need a human)

1. **A consented real dataset** for a dry run: the founder's own business, a friendly company, or an anonymised export.
2. **Discovery calls and pricing validation.** Outreach drafts exist; sending them is the founder's decision. Nothing has been sent.
3. **Legal.** A one-hour review by a Moroccan lawyer of the Law 09-08 position, a data-processing agreement template and the deletion certificate.
4. **Real API and identity-provider tests.** These need HubSpot/Salesforce developer accounts and a test tenant with the client's identity provider.

## Pending (engineering, in order)

1. Run the first real export through `canon pilot`; fix what breaks, adding a fixture and a decision entry for each fix.
2. Dynamics 365 column preset.
3. Email connector (`.eml`/`.mbox`). The source type already exists; there is no loader.
4. An opt-in script to test the CRM pull against sandbox accounts.
5. Incremental runs, only if a client's volume needs them.

## Next exact action

The founder picks the dataset for the real-data dry run (blocker 1) and runs:
```bash
uv run canon pilot --data <export>
```
They then open `out/index.html` and send the intake check and any errors back for fixing.
