# Canon

Agent-ready data layer. Canon ingests messy company data (CRM, Slack, Drive, PDFs), resolves
duplicate entities into golden records with lineage, scores facts by freshness and authority,
and exposes them through a permission-aware MCP server.

See [`docs/PLAN.md`](docs/PLAN.md) for the architecture and milestones and
[`docs/DECISIONS.md`](docs/DECISIONS.md) for recorded design choices.

## Quickstart

```bash
uv sync
uv run pytest -q
uv run canon generate          # (re)build data/synthetic from the seed
uv run canon resolve --report  # ingest + entity resolution -> out/ (golden records, SQLite, report)
uv run canon resolve --report --seeds 20   # also sweep 20 held-out generator seeds
```

## Results so far

Entity resolution on the synthetic set (119 records, 25 customers): **pairwise F1 0.991**
(P 1.000 / R 0.983), versus 0.696 for exact-name matching; mean F1 0.992 over 50 held-out seeds.
Details: [`docs/ENTITY_RESOLUTION.md`](docs/ENTITY_RESOLUTION.md),
[`docs/reports/er_report.md`](docs/reports/er_report.md).

## Layout

```
canon/ingest       connectors -> SourceRecord (CRM, Slack, contracts)
canon/resolve      normalize, block, score, cluster, golden records, evaluation
canon/store.py     SQLite persistence (records, facts, golden fields, lineage)
canon/synth        seeded synthetic data generator (tooling)
canon/score        M3   canon/mcp_server  M4   canon/evals  M5
data/synthetic     generated dataset + hidden ground truth
docs               plan, decisions, method notes, reports
```

## Status

| Milestone | Status |
|---|---|
| 1. Synthetic messy dataset | done — [`data/synthetic`](data/synthetic/README.md) |
| 2. Entity resolution | done: F1 0.991 ([report](docs/reports/er_report.md)) |
| 3. Fact scoring | planned |
| 4. MCP server | planned |
| 5. Eval harness | planned |
