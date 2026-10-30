# Operations runbook

*Part of the product document set (`docs/product/`). Code claims cite repository paths. Written by the agent that built most of the code: a self-assessment, not independent review. Updated 2026-10-30.*

For the operator running a pilot. Commands assume the Docker image from `DEPLOYMENT.md`.

## Daily during an engagement

| When | Do | Check |
|---|---|---|
| Day 1 | `canon check` on the export | `intake_check.md`: every source found, parse failure rate; fix `canon.json` with `canon.suggested.json` |
| Day 1–2 | `canon pilot --as-of <today>` | `index.html` numbers plausible; `run.json` lists every input file |
| Day 3 | Send `review.html` to account owners | Answers come back as `overrides.json` |
| Day 4–5 | Rerun with `--overrides overrides.json` | Review queue shrinks; corrected values appear with "Confirmed by …" |
| Week 2 | New export → `canon pilot --compare <week1>/audit.json` | "Changes since the last audit" section |
| End | `canon purge --out out` (dry run), then `--yes --receipt …` | Receipt signed off with the client |

## If the agent server is running

- Liveness: `GET /health` → 200 `{"status": "ok"}`.
- Who asked what: `audit.jsonl` (one line per call: caller, tool, records cited, injections withheld).
- Revoke access: `canon token revoke --caller <id> --tokens …` (immediate).
- Restart: stop the container and start it again; the store is read at start-up.

## Incidents

| Symptom | Likely cause | Action |
|---|---|---|
| Many refused values of one reason | Date order or currency not set | Set `ingest.dayfirst` / `currency` in `canon.json`, rerun |
| A CRM source missing in the intake check | Column names not mapped | Copy suggestions from `canon.suggested.json` |
| Wrong merge reported by a user | Borderline pair | Add to `cannot_link` via `review.html`, rerun |
| Agent answers `partial_view` | Caller lacks access to some sources | Expected; confirm roles in `identities.json` |
| 401 from the server | Missing/revoked token or wrong OIDC audience | Reissue token; check `--oidc-*` flags |

## Backups

Keep `overrides.json` and each week's `audit.json` and `run.json` (with the client's agreement, on the client's
machine). Everything else is regenerated from the export.

## Support

During a pilot: named contact, response within one business day (to be agreed in the pilot proposal).
