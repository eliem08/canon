# Canon

Agent-ready data layer. Canon ingests messy company data (CRM exports or a read-only HubSpot/Salesforce pull,
Slack/Teams/WhatsApp exports, folders of contracts in PDF, Word or scans), resolves
duplicate entities into golden records with lineage, scores facts by freshness and authority,
and exposes them through a permission-aware MCP server.

**Start here:** [`BUILD_STATUS.md`](BUILD_STATUS.md) (what works, what doesn't, readiness gates),
[`docs/product/`](docs/product) (architecture, implementation audit, requirements, roadmap, technical design,
security review, testing report, deployment, operations runbook, market and buyer research) and
[`docs/sales/`](docs/sales) (brief, deck outline, demo script, pilot proposal, pricing, objections, outreach).

See [`docs/PLAN.md`](docs/PLAN.md) for the original architecture and milestones and
[`docs/DECISIONS.md`](docs/DECISIONS.md) for recorded design choices.

Selling it: [`docs/sales/`](docs/sales) (one-pager, 10-minute demo script, outreach email in EN/FR),
[`docs/AUDIT_SCOPE.md`](docs/AUDIT_SCOPE.md) (the MCP Readiness Audit, draft) and
[`docs/DATA_REQUEST.md`](docs/DATA_REQUEST.md) (what to ask a design partner for). Ingestion refuses values it
cannot read safely and lists them for review: [`docs/PARSING.md`](docs/PARSING.md). Facts in messages are
extracted by cue/blocker rules, and every fact cites its message, page or row: [`docs/EXTRACTION.md`](docs/EXTRACTION.md).

## Quickstart

```bash
uv sync
uv run pytest -q
uv run canon generate          # (re)build data/synthetic from the seed
uv run canon resolve --report  # ingest + entity resolution -> out/ (golden records, SQLite, report)
uv run canon resolve --report --seeds 20   # also sweep 20 held-out generator seeds
uv run canon serve                         # MCP server over stdio (see docs/MCP_SERVER.md)
uv run python examples/mcp_client.py       # example client: same questions, four callers
uv run canon eval --seeds 10               # before/after eval (stub model; --model claude for real)
uv run canon pull hubspot --out export/crm/accounts.json   # optional: read-only CRM pull (or salesforce)
uv run canon check --data export/          # day-1 intake check of a client export (+ suggested canon.json)
uv run canon audit                         # audit -> report (.md/.html), review.html, crm_fixes.csv, quarantine.csv
uv run canon pilot --data export/          # the whole engagement: check + audit + out/index.html + out/run.json
uv run canon purge --out out               # end of engagement: dry run; add --yes to delete (prints a receipt)
docker build -t canon .                    # client-side image; see docs/DEPLOY.md
```

## Results so far

**Before/after eval** (four open models on Baseten, same model and prompt for every agent):

| | Keyword RAG | Strong RAG | **Canon** |
|---|---|---|---|
| 40 synthetic questions | 55–60% | 92.5% | **97.5%** |
| 30 hand-written questions | 70–73% | 93–97% | **96.7%** |
| as a sales rep: answers that read text the rep may not see | 27/40 | **35/40** | **0/40** |
| context the model reads per answer | 2.0k chars | 3.7k chars | **1.3k chars** |

Canon beats keyword retrieval by about 40 points. A well-built RAG over the same raw files gets within
0–5 points of Canon, and none of those differences is significant. Canon's difference is that it never
reads what the caller may not see, it cites every fact, it gives the model a third of the text, and it
produces the audit report.
Details and caveats: [`docs/EVALS.md`](docs/EVALS.md). Permission leaks at scale (4,400 answers, 110 callers,
10 datasets): strong RAG 87%, keyword RAG 70%, **Canon 0%**
([`docs/reports/permission_report.md`](docs/reports/permission_report.md)). All measured claims in one place:
[`docs/sales/PROOF.md`](docs/sales/PROOF.md).

Entity resolution on the synthetic set (119 records, 25 customers): **pairwise F1 0.991**
(P 1.000 / R 0.983), versus 0.696 for exact-name matching; mean F1 0.991 over 50 held-out seeds;
50 adversarial pairs (generic shop names, other cities, FR/AR translations): P 1.000 / R 0.962.
Details: [`docs/ENTITY_RESOLUTION.md`](docs/ENTITY_RESOLUTION.md),
[`docs/reports/er_report.md`](docs/reports/er_report.md).

Contracts on **real data** (CUAD: 510 public SEC-filed contracts, lawyer answers; held-out half):
parties found in 57% at 99% precision, agreement date 66% at 94%, effective date 60% at 95%, end date
28% at 90%, up from 0% for the template-only reader. Details: [`docs/DOCUMENTS.md`](docs/DOCUMENTS.md).

Entity resolution on **real listings** (Fodors–Zagat, held-out half): F1 **0.948** (P 0.902 / R 1.000)
vs 0.825 for exact names. On **real French companies** (SIRENE registry vs shop signs): 29% of shop signs
linked automatically and 28% sent to a person, precision 0.91. **Arabic ↔ Latin names** (23k real names):
97.8% of true pairs at similarity 0.85 with 0.10% false matches. OCR on **real scanned receipts** (SROIE, 361): dates 63% correct, 2% wrong,
the rest withheld (76% / 4% if unsure digits are not withheld). Details: [`docs/ENTITY_RESOLUTION.md`](docs/ENTITY_RESOLUTION.md),
[`docs/DOCUMENTS.md`](docs/DOCUMENTS.md).

Fact scoring (freshness × authority, losers kept as alternatives): **0.968** of current facts
correct, versus 0.904 for "latest wins". Contract value and renewal date are 1.00, owner is 0.92,
and both owner misses are flagged at confidence ≈ 0.09. Details: [`docs/FACT_SCORING.md`](docs/FACT_SCORING.md).

MCP server: `get_customer`, `find_contract_terms`, `who_owns`, `list_conflicts`. Each answer
carries value, sources, last_updated, confidence and alternatives, computed only from the
sources the caller may see. Unauthorized callers get nothing. Over HTTP, identity comes from a bearer
token. Private Slack channels are visible to their members only, injected instructions in source
text are withheld, and every call is audited. Connect it to Claude:
[`docs/MCP_SERVER.md`](docs/MCP_SERVER.md).

Contracts can be PDF (text or scanned, via tesseract OCR in French, Arabic and English), DOCX or
images. Every fact cites `file#p<page>:L<line>`. On 50 synthetic scans, every contract field is
read correctly, and unreadable files are listed rather than skipped:
[`docs/DOCUMENTS.md`](docs/DOCUMENTS.md).

## Layout

```
canon/ingest       connectors -> SourceRecord (CRM JSON/CSV, Slack/Teams/WhatsApp, contracts: txt/PDF/DOCX/OCR),
                   hardened value parsing, message fact extraction
canon/guard.py     prompt-injection screening of source text
canon/resolve      normalize, block, score, cluster, golden records, evaluation
canon/store.py     SQLite persistence (records, facts, golden fields, lineage)
canon/synth        seeded synthetic data generator (tooling)
canon/score        fact freshness, authority, confidence, conflicts
canon/mcp_server   permission-aware MCP server (service, schemas, MCPServer tools)
canon/evals        before/after eval harness (questions, baseline/oracle/Canon agents, models, stats)
scripts            OCR benchmark
examples           runnable MCP client
data/synthetic     generated dataset + hidden ground truth
data/eval          hand-written eval questions
docs               plan, decisions, method notes, reports
```

## Status

| Milestone | Status |
|---|---|
| 1. Synthetic messy dataset | done — [`data/synthetic`](data/synthetic/README.md) |
| 2. Entity resolution | done: F1 0.991 ([report](docs/reports/er_report.md)) |
| 3. Fact scoring | done: fact accuracy 0.968 ([method](docs/FACT_SCORING.md)) |
| 4. MCP server | done: 4 permission-aware tools ([docs](docs/MCP_SERVER.md)) |
| 5. Eval harness | done: keyword RAG 55–60%, strong RAG 92.5%, Canon 97.5% (4 real models); permission leaks 35/40 vs 0/40 ([evals](docs/EVALS.md)) |
