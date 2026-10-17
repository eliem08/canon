# Running Canon in the client's environment

The audit runs as an **offline batch** inside the client's machine or VPC (`docs/AUDIT_SCOPE.md`, option A).
One container image holds everything: Python 3.12, Canon, and tesseract (fra+ara+eng) for scans.

## Build
```bash
docker build -t canon .                       # Ubuntu 24.04 base, ~650 MB
```
Behind a corporate proxy that inspects TLS:
```bash
docker build --network host \
  --build-arg http_proxy=$PROXY --build-arg https_proxy=$PROXY \
  --secret id=ca,src=/path/to/proxy-ca.pem -t canon .
```
The proxy CA is trusted only during the build and removed from the final image. `--build-arg BASE_IMAGE=...`
selects a mirror of `ubuntu:24.04` if Docker Hub is unavailable.

## Lay out the export
```
export/
  canon.json                  per-client settings: CRM file and column names, ACLs, currency (optional)
  crm/accounts.csv            (or .json / .xlsx; any name if canon.json sets crm.file)
  slack/                      native Slack export: users.json, channels.json, groups.json, <channel>/<day>.json
  contracts/                  PDF / DOCX / scans / .txt, any folder depth
    board/_acl.json           {"acl": ["exec"]}: who may read this folder (default: legal, exec)
  identities.json             callers -> groups (+ optional slack_user_id), from the role spreadsheet
```

## 0. Intake check (day 1, minutes)
```bash
docker run --rm --network none -v "$PWD/export:/data:ro" -v "$PWD/out:/out" canon check
# -> out/intake_check.md, and out/canon.suggested.json when columns need mapping
```
It lists what was found, which column feeds each CRM field, how many values each field would lose and why,
and Slack/contract warnings (no `groups.json`, OCR missing, unsupported formats). It exits non-zero when no
CRM record can be built (no id or name column, blank ids). Column suggestions come from common CRM and
French names; **review them**, then copy the file to `export/canon.json`. Nothing is applied on its own.
A typo in `canon.json` (unknown key or field) stops every command instead of silently using a default.

## 1. Ingest and resolve, with no network
```bash
docker run --rm --network none \
  -v "$PWD/export:/data:ro" -v "$PWD/out:/out" \
  canon resolve [--overrides /data/overrides.json]
```
`--network none` means the client's data cannot leave the container during processing. Outputs in `out/`:

| File | What it is |
|---|---|
| `canon.sqlite` | records, facts, golden records, lineage, parse issues |
| `golden_records.json` | one record per customer with lineage |
| `quarantine.json` | values refused (with raw text and reason), unreadable documents, possible prompt injections |
| `review_queue.json` | borderline merges for the client to confirm; their answers go in `overrides.json` |

Re-running keeps entity ids stable. Send `quarantine.json` and `review_queue.json` to the client on day 3.

The readiness report (fix list, duplicates, stale CRM values, quarantine, merges to confirm, permission
map) is produced the same way:
```bash
docker run --rm --network none -v "$PWD/export:/data:ro" -v "$PWD/out:/out" canon audit
# -> out/audit_report.md, out/audit.json
```

## 2. Serve to an agent (optional trial)
```bash
docker run --rm --network none -v "$PWD/out:/out" canon token add --caller hind.legal --tokens /out/tokens.json
docker run -d --name canon -p 127.0.0.1:8765:8765 \
  -v "$PWD/export:/data:ro" -v "$PWD/out:/out" \
  canon serve --http --host 0.0.0.0 --tokens /out/tokens.json \
    --identities /data/identities.json --audit-log /out/audit.jsonl
```
Clients connect to `http://<host>:8765/mcp` with `Authorization: Bearer <token>`. Put TLS in front (the client's
reverse proxy). Only hashed tokens are stored. `canon token revoke --caller <id>` takes effect immediately.

## 3. Before/after eval on the client's questions
```bash
docker run --rm -v "$PWD/export:/data:ro" -v "$PWD/out:/out" \
  -e ANTHROPIC_API_KEY canon eval --questions /data/questions.xlsx --model claude --runs 3 --out /out/eval.md
```
The question sheet is the client's (CSV, XLSX or JSON) with columns `id, type, question, expected`; `type` is one
of contract_value, renewal_date, owner, phone, address. Expected answers are parsed like source values: an
amount that isn't one number or a date like `03/04/2027` stops the run with the row named, so the client
writes it unambiguously (YYYY-MM-DD). This is the only step that needs network, and only to reach the model provider. Use it only with the
client's written consent. Without consent, use a model the client hosts behind an OpenAI-compatible API
(vLLM, Ollama, TGI...), so no data leaves their network:
```bash
docker run --rm --network client-net -v "$PWD/export:/data:ro" -v "$PWD/out:/out" \
  canon eval --questions /data/questions.json --model openai-compatible \
    --base-url http://llm.internal:8000/v1 --model-id <served model name> --runs 3 --out /out/eval.md
```
No key is needed unless `--api-key-env` names a variable that is set.

## Verified
In the development environment (2026-10-16), the image built from this Dockerfile ran `resolve` with
`--network none` on the synthetic export plus a scanned PDF. The scan was OCR'd, its contract value
was read correctly, and it was merged into the right customer. `serve --http` refused a request
without a token (401) and answered as the token's caller although the request claimed another
identity. The call was written to the audit log. CI builds the image and runs `resolve` offline on
every push.

## Not done
* No image signing or SBOM, and no published registry image: the client builds from source.
* No at-rest encryption of `out/` beyond the client's own disk encryption.
* Data deletion at the end of the audit is a manual `rm -rf out/` plus removing the container. Confirm it
  in writing (`docs/DATA_REQUEST.md`).
