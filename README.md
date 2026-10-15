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
```

## Status

| Milestone | Status |
|---|---|
| 1. Synthetic messy dataset | done — [`data/synthetic`](data/synthetic/README.md) |
| 2. Entity resolution | in progress |
| 3. Fact scoring | planned |
| 4. MCP server | planned |
| 5. Eval harness | planned |
