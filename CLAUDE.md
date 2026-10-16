# Canon — notes for Claude

Agent-ready data layer: ingest → resolve → score → serve (MCP) → eval. See `docs/PLAN.md`.

## Commands
- `uv sync` — install
- `uv run pytest -q` — tests (must pass before every commit)
- `uv run ruff check . && uv run ruff format --check .` — lint/format (CI runs both)
- `uv run canon generate` — regenerate `data/synthetic` (seeded; tests assert it matches the committed copy)
- `uv run canon resolve --report` — run entity resolution and print P/R/F1
- `uv run canon eval [--seeds N] [--model claude]` — before/after eval; refresh `docs/reports/eval_report.md` with
  `uv run canon eval --seeds 10 --out docs/reports/eval_report.md`
- `uv run canon serve` — MCP server over stdio; `uv run python examples/mcp_client.py` exercises it

## Rules
- Python 3.12, pydantic v2, stdlib SQLite, rapidfuzz. No heavy frameworks.
- Synthetic data only; never commit real client data or secrets (`.env.example` only).
- No client-specific logic in `canon/` core packages: connector quirks live in `canon/ingest`,
  tunables live in config objects with defaults.
- `data/synthetic/ground_truth/` is the answer key. Only `canon/evals`, the evaluation modules
  (`canon/resolve/evaluate.py`, `canon/score/evaluate.py`, which take it as an argument), the CLI report
  and tests may read it — never ingest/resolve/score logic.
- Ambiguity: choose the simplest option and record it in `docs/DECISIONS.md`.
- Small commits; never push to main.

## Where things are
- Method notes for ER: `docs/ENTITY_RESOLUTION.md`; latest metrics: `docs/reports/er_report.md`
  (regenerate with `uv run canon resolve --report --seeds 50 --as-of 2026-10-01 && cp out/er_report.md docs/reports/`).
- Fact scoring: `docs/FACT_SCORING.md`; tunables in `canon/score/facts.py::FactScoringConfig`.
- MCP server: `docs/MCP_SERVER.md`; ACLs are enforced in `canon/mcp_server/service.py` *before* scoring —
  never answer from precomputed golden facts in a caller-facing path.
