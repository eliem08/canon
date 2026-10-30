# Product requirements

*Part of the product document set (`docs/product/`). Code claims cite repository paths. Written by the agent that built most of the code: a self-assessment, not independent review. Updated 2026-10-30.*

## Vision and value

Canon makes a company's customer facts trustworthy before people or AI agents act on them. It reconciles the CRM,
contracts and chat exports inside the client's network, says which value is current and why, refuses values it
cannot read safely, and serves the result to agents with each person's permissions applied first.

## Users

| Persona | Job to be done | Surface |
|---|---|---|
| Operator (Canon's founder or the client's IT) | Run the engagement on an export | `canon check`, `canon pilot`, `canon purge` |
| Commercial director | Know what is wrong and what renews soon | `index.html`, `audit_report.html`, `renewals.csv` |
| Sales ops / CRM admin | Fix the CRM | `crm_fixes.csv`, `quarantine.csv`, `--compare` |
| Account owner | Confirm merges, correct values | `review.html` → `overrides.json` |
| AI agent (on behalf of a person) | Answer customer questions with sources | MCP tools via `canon serve` |
| DPO / security | Control data handling | `--network none`, hashed tokens, audit log, `canon purge` receipt |

## Core workflows and acceptance criteria

Status: **Done** = implemented and covered by an automated test that ran on 2026-10-30.

| ID | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| F1 | Intake check before any processing | `canon check` reports files, formats, parse failures; non-zero exit on a broken export | Done (`tests/test_intake.py`) |
| F2 | One command produces every deliverable | `canon pilot` writes audit report, fix files, review page, renewals, `index.html`, `run.json` | Done (`tests/test_pilot.py`) |
| F3 | Never guess a value | Ambiguous dates/amounts/phones are refused with a reason code and listed in `quarantine.csv` | Done (`tests/test_parsing.py`, adversarial fixtures) |
| F4 | Resolve duplicate customers across sources and scripts | Merges explained; borderline pairs go to review; human decisions persist | Done (`tests/test_pipeline.py`, `test_er_guards.py`) |
| F5 | Current value with confidence and lineage | Every answer cites record, location and quote; conflicts listed | Done (`tests/test_score.py`, `test_mcp.py`) |
| F6 | Renewal calendar | Renewals in 180 days, rolled forward for auto-renewal, with last notice day | Done (`tests/test_audit.py`, `test_contract_terms.py`) |
| F7 | Human review loop | Merge answers and signed value corrections round-trip through `review.html` into the next run | Done (`tests/test_review_browser.py`, real Chromium) |
| F8 | Week-2 comparison | `--compare` lists fixed and new stale values by CRM record id | Done (`tests/test_audit.py`) |
| F9 | Permission-aware agent access | ACL applied before scoring; no response cites a record the caller cannot read | Done (`tests/test_mcp.py`, `scripts/permission_benchmark.py`) |
| F10 | Authenticated HTTP access | Bearer tokens (hashed) or OIDC JWT; identity from the token, not the request | Done (`tests/test_security.py`, `test_sso.py`; no real IdP tested) |
| F11 | End-of-engagement deletion | `canon purge` dry-runs by default, refuses non-Canon folders, prints a receipt | Done (`tests/test_purge.py`) |
| F12 | Read-only CRM pull | HubSpot/Salesforce GET only, same-host pagination | Implemented; mocked HTTP only (`tests/test_pull.py`) |
| F13 | Email as a source | `.eml`/`.mbox` ingest | **Missing** |
| F14 | Incremental runs | Re-run cost proportional to change | **Missing** |

## Non-functional requirements

| Area | Requirement | Evidence today |
|---|---|---|
| Data residency | Processing works with no network | CI runs `resolve` in Docker with `--network none` |
| Performance | 50k CRM-scale records resolve in < 10 min on a laptop-class machine | 47k records in 31 s (`docs/reports/scale_report.md`, synthetic look-alikes) |
| Lookup latency | MCP answer < 1 s at pilot scale | 108 ms mean at 47k records (same report) |
| Accuracy honesty | Wrong values kept near zero; refusals explained | CUAD, SROIE, SIRENE reports in `docs/reports/` |
| Security | No secrets in repo; dependency scan clean | pip-audit in CI; history scan 0 hits (`SECURITY_REVIEW.md`) |
| Accessibility | Pages readable on phone and desktop, keyboard-usable forms, labelled inputs, light/dark | Checked at 390 px and 1200 px in Chromium; no formal WCAG audit |
| Reliability | Deterministic output for the same inputs and `as_of` | `run.json` input hashes; seeded synthetic data asserted in tests |
| Portability | Linux container, Python 3.12, tesseract fra/ara/eng | `Dockerfile`, CI |

## Constraints

- Synthetic data only in the repository; real data never committed (`CLAUDE.md`).
- No client-specific logic in core packages; per-client settings in `<data>/canon.json`.
- Ground truth read only by evaluation code.
