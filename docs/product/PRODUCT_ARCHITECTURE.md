# Product architecture

*Part of the product document set (`docs/product/`). Code claims cite repository paths; market statements are hypotheses unless a source is linked. Written by the agent that built most of the code: treat as a self-assessment, not independent review. Updated 2026-10-30.*

## What the product is

Canon is a batch tool that runs inside a company's own network:

1. It reads exports of the **CRM**, **chat** (Slack, Teams, WhatsApp) and **contracts** (PDF, DOCX, scans via OCR, in French, Arabic and English).
2. It works out which records describe **the same customer**.
3. For each customer fact (owner, contract value, renewal date and so on) it decides **which value is current**. Each value comes with a confidence score, its sources and any conflicting alternatives.
4. It produces two things:
   - an **audit pack** for people: a stale-data fix list, duplicates, values it refused to read, a permission map and a renewal calendar;
   - a **permission-aware MCP server**, so that AI agents answer from the reconciled facts rather than from raw files, and only from what the asking person may see.

**User problem.** When a company points an AI assistant at its CRM, chat and contracts, the assistant repeats stale CRM values, confuses duplicate customers, and can quote documents the asker isn't allowed to see. Canon fixes the data first and enforces permissions before anything is scored or returned.

## Components and data flow

```
                    ┌──────────── client's network (docker --network none) ────────────┐
 Exports / pulls    │                                                                   │
 crm/*.json|csv|xlsx│  canon/ingest/*  ──►  canon/resolve/*  ──►  canon/score/facts.py   │
 slack/ teams/      │  (parse, refuse       (blocking, Fellegi-     (authority × freshness │
 whatsapp/          │   ambiguous values,    Sunter scoring,         → confidence,         │
 contracts/ (OCR)   │   ParseIssue)          clusters, golden)       conflicts, lineage)   │
 canon pull (GET    │          │                     │                       │              │
  HubSpot/SFDC API) │          └──────────► out/canon.sqlite + JSON ◄───────┘              │
                    │                                │                                       │
                    │   canon audit ─► audit_report.md/html, crm_fixes.csv, quarantine.csv,  │
                    │                   renewals.csv, review.html ─► overrides.json (loop)   │
                    │   canon serve ─► MCP (stdio | streamable HTTP + bearer/OIDC)           │
                    │                   5 tools, ACL filter → score → answer + audit.jsonl   │
                    │   canon eval  ─► RAG baselines vs Canon (needs model endpoint)         │
                    └───────────────────────────────────────────────────────────────────────┘
```

- **Clients/UI.** There is a CLI (`canon/cli.py`) and static offline HTML pages (`canon/deliver.py`). There is no web app.
- **Services.** One process. The MCP server is `canon/mcp_server/server.py` and the logic sits in `canon/mcp_server/service.py::CanonService`.
- **Storage.** SQLite in `canon/store.py`, plus JSON files in `out/`. The whole store is loaded into memory at serve time.
- **External services.** These are optional:
  - CRM APIs for `pull`, GET only (`canon/ingest/pull.py`);
  - an LLM endpoint for `eval` and the optional extractor (`canon/evals/models.py`).
- **Background jobs, queues and observability.** None, apart from a JSONL audit log (`canon/mcp_server/audit.py`).
- **Auth.**
  - Bearer tokens are stored as SHA-256 hashes (`canon/mcp_server/auth.py`).
  - OIDC JWT verification goes through the provider's published signing keys (`OIDCVerifier`).
  - Callers map to groups through `identities.json` (`CallerDirectory`).
- **Deployment.** A Dockerfile (Ubuntu 24.04, non-root uid 10001), run as `--network none` for ingest. A runbook is in `docs/DEPLOY.md`.

Added since that map: `canon pilot` (`canon/pilot.py`) wraps check and audit and writes `index.html` and `run.json`; `serve --http` exposes `GET /health`; `canon purge` (`canon/purge.py`) deletes outputs with a receipt; `review.html` collects signed value corrections.

## User journeys through the code

1. **Day-1 intake check.** `canon check --data DIR`
   → `cli.py:cmd_check`
   → `canon/intake.py`, which counts files, detects formats and samples parse failures
   → reads `<data>/canon.json` via `canon/ingest/deployment.py`.
   *Output:* a readiness summary, before any resolution runs.

2. **Readiness audit, the paid deliverable.** `canon audit --data DIR --out OUT [--overrides] [--compare]`. The code path runs in this order:
   - `cli.py:cmd_audit` calls `build_store`;
   - `canon/ingest/__init__.py:load_all` loads the CRM, Slack, Teams, WhatsApp and contracts. Values are parsed by `canon/ingest/parsing.py` and contract terms by `contract_terms.py`;
   - `Overrides.confirmed_records` adds values people have confirmed;
   - `canon/resolve/pipeline.py:resolve` runs blocking, `scoring.score_pair`, clustering and `golden.build_golden`;
   - `canon/audit.py:build_audit` builds the fix list (`_stale_values`, `_findings`, `_renewals`), and `compare_audits` handles `--compare`;
   - `canon/deliver.py` writes `render_audit_html`, `render_review_html`, `write_fix_files` and `write_renewals_csv`.

3. **An agent asks a question.** `canon serve [--http]`
   → `server.py` registers `get_customer`, `find_contract_terms`, `who_owns`, `list_conflicts` and `list_renewals`
   → `service.py:_serve` → `_match` (name blocking) → `_visible`, which filters by ACL **before** `_facts` and `score_entity`
   → `_screen` withholds text that looks like a prompt injection
   → `AuditLog.record`.

4. **Human review loop.**
   - `review.html` gives the client offline cards to judge;
   - their answers download as `overrides.json`, with `must_link`, `cannot_link` and confirmed `facts`;
   - the next run applies them in `resolve()` and `Overrides.confirmed_records`.

5. **Before/after proof.** `canon eval --questions client.xlsx --model ...`
   → `canon/evals/harness.py:run_eval`
   → agents in `canon/evals/agents.py`: BM25 RAG, hybrid "strong" RAG, and the Canon MCP agent
   → the report scores correctness and **"read restricted text"** leaks.

## Entities, contracts, boundaries

- **Core models** (`canon/models.py`):
  - `SourceRecord`: a record id, source type (`crm|slack|contract|email|confirmed`), identity attributes, `facts`, `acl`, `issues`;
  - `Fact`: field, value, `observed_at`, `valid_until`, `source_ref` and `quote`, which carry the lineage;
  - `ParseIssue`, `GoldenRecord` and `ResolvedFact`.
- **MCP contract** (`canon/mcp_server/schemas.py`):
  - `Answer`: value, confidence, `last_updated`, sources, alternatives, conflict and explanation;
  - `CustomerProfile`, `ContractTerms`, `OwnerAnswer`, `ConflictList`, `RenewalList`.
- **CLI contract:** `generate`, `resolve`, `serve`, `audit`, `check`, `pull`, `token` and `eval` (`cli.py`).
- **Per-client configuration:** `<data>/canon.json` (`canon/ingest/deployment.py`). It holds column maps, ACLs, date order, currency and the company's own names.
- **Integration boundary.** Integration is **file-based**, plus a read-only CRM pull. Nothing is ever written back to a client system.
