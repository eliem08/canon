# Canon

Agent-ready data layer. Canon ingests messy company data (CRM, Slack, Drive, PDFs), resolves
duplicate entities into golden records with lineage, scores facts by freshness and authority,
and exposes them through a permission-aware MCP server.

See [`docs/PLAN.md`](docs/PLAN.md) for the architecture and milestones and
[`docs/DECISIONS.md`](docs/DECISIONS.md) for recorded design choices.

Selling it: [`docs/AUDIT_SCOPE.md`](docs/AUDIT_SCOPE.md) (the MCP Readiness Audit, draft) and
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
docker build -t canon .                    # client-side image; see docs/DEPLOY.md
```

## Results so far

**Before/after eval** (same model for every agent, four open models on Baseten): on 40 synthetic
questions, an agent with keyword retrieval over the raw files answers **55–58%** correctly, and the
same agent using Canon's MCP tools answers **97.5%** (McNemar p ≤ 1e-04). On 30 hand-written
questions that name the customer mid-sentence: 67–73% → **96.7%**. **Caveat:** given *perfect*
retrieval over the raw files (every record of the right customer, taken from the answer key), the same
models reach 90–95%. On this data, most of Canon's value is *finding the right records*; reconciling
stale values adds the last few points. Details: [`docs/EVALS.md`](docs/EVALS.md).

Entity resolution on the synthetic set (119 records, 25 customers): **pairwise F1 0.991**
(P 1.000 / R 0.983), versus 0.696 for exact-name matching; mean F1 0.991 over 50 held-out seeds;
50 adversarial pairs (generic shop names, other cities, FR/AR translations): P 1.000 / R 0.962.
Details: [`docs/ENTITY_RESOLUTION.md`](docs/ENTITY_RESOLUTION.md),
[`docs/reports/er_report.md`](docs/reports/er_report.md).

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
canon/ingest       connectors -> SourceRecord (CRM JSON/CSV, Slack, contracts: txt/PDF/DOCX/OCR),
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
| 5. Eval harness | done: 55–58% → 97.5% with 4 real models; oracle retrieval 92.5–95% ([evals](docs/EVALS.md)) |
