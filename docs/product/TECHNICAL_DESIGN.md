# Technical design

*Part of the product document set (`docs/product/`). Code claims cite repository paths. Written by the agent that built most of the code: a self-assessment, not independent review. Updated 2026-10-30.*

## Decision: keep the architecture, harden the edges

The current design (batch pipeline → SQLite store → MCP service, all in one process, run inside the client's
network) fits the product: a two-week on-premise engagement with a few thousand to tens of thousands of records.
No rewrite, no microservices, no hosted database. Changes are targeted:

| Area | Keep | Changed in this round | Later (only with a customer reason) |
|---|---|---|---|
| Ingest | File connectors, read-only CRM pull, refusal-based parsing | — | Email connector, Dynamics preset |
| Resolution | Fellegi–Sunter scoring, blocking, average-linkage clustering | Neighbour-map clustering (decision 92) | Incremental re-runs |
| Scoring | Authority × freshness, lineage per fact, confirmed facts | — | — |
| Storage | SQLite file + JSON in `out/` | `run.json` manifest | Encryption at rest if a client requires it beyond disk encryption |
| Serving | MCP (stdio / streamable HTTP), ACL before scoring | `/health` | Rate limiting inside the app if exposed beyond a proxy |
| Delivery | Static offline HTML + CSV | `index.html` dashboard; correction form | — |
| Ops | Docker, CI | `canon purge`, pip-audit, browser test job | Signed images, SBOM |

## Components

See `PRODUCT_ARCHITECTURE.md` for the diagram and journeys. Module boundaries:

- `canon/ingest/*`: source → `SourceRecord` with `facts`, `acl`, `issues`. No network except `pull.py`.
- `canon/resolve/*`: records → clusters → `GoldenRecord` (`pipeline.resolve`, `Overrides`).
- `canon/score/facts.py`: evidence → `ResolvedFact` with confidence and alternatives (`FactScoringConfig`).
- `canon/audit.py`, `canon/deliver.py`, `canon/pilot.py`, `canon/purge.py`: engagement outputs.
- `canon/mcp_server/*`: identity (`auth.py`), ACL + scoring per request (`service.py`), tools (`server.py`), audit log.
- `canon/evals/*`: before/after measurement; the only code that may read ground truth, with the evaluation modules.

## Data model

`SourceRecord` (record id, source type, identity attributes, `facts[]`, `acl[]`, `issues[]`) → `Fact` (field, value,
`observed_at`, `valid_until`, `source_ref`, `quote`) → `ResolvedFact` / MCP `Answer` (value, confidence, sources,
alternatives, conflict). Human decisions: `Overrides` (`must_link`, `cannot_link`, `facts[]` of `FactOverride`).
Store schema: `canon/store.py`. There are no migrations: the store is rebuilt from the export on every run, and
`read_lineage` carries entity ids over from the previous store.

## Interfaces

- CLI: `generate, check, pilot, audit, resolve, serve, token, pull, eval, purge` (`canon/cli.py`).
- MCP tools: `get_customer, find_contract_terms, who_owns, list_conflicts, list_renewals` (`docs/MCP_SERVER.md`).
- HTTP: `POST /mcp` (bearer or OIDC), `GET /health` (no auth, no data).
- Files: `canon.json` (deployment), `identities.json` (callers → groups, SSO map), `overrides.json` (human decisions).

## Error handling

Bad values become `ParseIssue` records (never exceptions, never guesses); unreadable documents are listed; the
intake check fails fast with a non-zero exit; `purge` refuses unsafe targets; pull errors report status codes only.

## Observability

`run.json` (versions, settings, input hashes, duration), `intake_check.md`, the MCP audit log (`audit.jsonl`: caller,
tool, query, records cited, injections withheld), `/health`.

## Backup and recovery

The export is the source of truth; outputs are reproducible from it plus `overrides.json`. Back up
`overrides.json` and each week's `audit.json` (needed for `--compare`); everything else can be regenerated.

## Scaling

Measured: 47k records in 31 s, lookups ~0.1 s (`docs/reports/scale_report.md`). Beyond ~200k records the in-memory
service and the full rebuild per run are the limits; address with incremental runs only when a client needs it.
