# Canon

**Canon makes a company's customer data trustworthy before people or AI agents act on it.**

It reads the places where customer facts actually live (the CRM, signed contracts, Slack/Teams/WhatsApp, email),
works out which records are the same customer, decides which value of each fact is current and why, and refuses
values it cannot read safely. The result is delivered two ways:

- **An audit for people**: a ranked fix list in the CRM's own record ids, duplicate accounts, a calendar of
  contracts that auto-renew with their notice deadlines, and a review page where account owners confirm merges
  and correct values.
- **A permission-aware MCP server for AI agents**: every answer carries its value, sources, date, confidence and
  conflicting alternatives, and is computed only from the sources the person asking may read.

Everything runs on the client's own machine, with networking off for ingestion. Nothing is written back to their
systems, and everything is deleted at the end with a receipt.

> **Status (2026-11-07):** working end to end on synthetic data and measured on public real datasets.
> **Not yet used by a customer.** What works, what doesn't and the readiness gates: [`BUILD_STATUS.md`](BUILD_STATUS.md).

---

## Contents

1. [The problem](#the-problem)
2. [How it works](#how-it-works)
3. [Quickstart: the 5-minute demo](#quickstart-the-5-minute-demo)
4. [Running it for a client](#running-it-for-a-client)
5. [What has been measured](#what-has-been-measured)
6. [Commands](#commands)
7. [Repository layout](#repository-layout)
8. [Design principles](#design-principles)
9. [Security and data handling](#security-and-data-handling)
10. [The business](#the-business)
11. [Limitations](#limitations)
12. [Development](#development)
13. [Documentation map](#documentation-map)

---

## The problem

Companies are connecting AI agents to their customer data. In practice that data disagrees with itself:

- The CRM says a contract is worth $1,190,000; the signed amendment says $1,468,000.
- The account owner changed in a Slack message, not in the CRM.
- The same customer exists three times ("Harbor Foods Corp", "Harbor - HQ", "HARBOR FOODS INC").
- A contract auto-renews next month unless notice is given, and nobody is tracking the deadline.

An agent connected to the raw sources repeats whichever value it finds first. It also doesn't know who is asking,
so a sales rep's question can be answered from a legal-only contract. Canon fixes the data first, and enforces
permissions before any fact is scored or returned.

## How it works

```
 exports / read-only pulls            canon (one process, on the client's machine)                   outputs
 ─────────────────────────            ─────────────────────────────────────────────                   ───────
 CRM (Salesforce, HubSpot,  ─┐
   CSV / JSON / XLSX)        │   1. ingest      parse every value; refuse ambiguous ones      ┐   index.html dashboard
 Slack / Teams / WhatsApp   ─┤                  (ParseIssue + reason), extract facts from     │   audit_report.html
 email (.eml / .mbox)       ─┤                  messages, cite every fact (file, page, line)  │   crm_fixes.csv
 contracts (PDF, DOCX,      ─┤   2. resolve     block → score pairs → cluster → golden record ├─► renewals.csv
   scans via OCR)            │                  (borderline pairs go to a person)             │   quarantine.csv
 overrides.json (people's   ─┘   3. score       authority × freshness → confidence,           │   review.html → overrides.json
   decisions & corrections)                     conflicts kept as alternatives                ┘   run.json, canon.sqlite
                                 4. serve       MCP tools; ACL applied *before* scoring   ──►  AI agents (stdio / HTTP)
                                 5. evaluate    before/after vs RAG baselines             ──►  eval report
```

1. **Ingest** (`canon/ingest/`). Connectors turn each source into `SourceRecord`s carrying identity attributes
   (name, domain, phone, tax id, address), dated facts (owner, contract value, renewal date, renewal period, notice
   period...) and an access list. Values are parsed by `canon/ingest/parsing.py`, which **refuses rather than
   guesses**: `03/04/2027` with no stated date order, `1.426,000`, an amount in the wrong currency, or an unsure OCR
   digit becomes a quarantined value with a reason code, never a wrong fact.
2. **Resolve** (`canon/resolve/`). Fellegi–Sunter-style pair scoring over blocking keys (name skeletons, domains,
   phones, tax ids, addresses; Arabic↔Latin transliteration; acronyms), average-linkage clustering with
   cannot-link guards, and golden records with lineage. Borderline pairs go to a review queue; human decisions in
   `overrides.json` are applied on every run, and entity ids stay stable between runs.
3. **Score** (`canon/score/facts.py`). Each candidate value gets authority (contract > CRM > email > Slack;
   values a person confirmed rank highest) × freshness (field-specific half-lives). The winner is returned with a
   confidence, and the losers stay as cited alternatives, flagged as a conflict.
4. **Serve** (`canon/mcp_server/`). Five MCP tools: `get_customer`, `find_contract_terms`, `who_owns`,
   `list_conflicts`, `list_renewals`. The caller's identity comes from a bearer token or an OIDC JWT, never from
   the request; records the caller cannot read are dropped *before* scoring; instruction-like source text is
   withheld; every call is logged.
5. **Audit and deliver** (`canon/audit.py`, `canon/deliver.py`, `canon/pilot.py`). The client-facing files listed
   above, plus a week-2 comparison (`--compare`) showing what was fixed since the last run.
6. **Evaluate** (`canon/evals/`). The same questions answered by a keyword RAG agent, a strong hybrid RAG agent, an
   oracle and the Canon agent, with any model, scoring accuracy and how often each one read text the caller may not see.

## Quickstart: the 5-minute demo

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). For scanned documents, tesseract (`fra`, `ara`, `eng`).

```bash
uv sync
uv run canon pilot --data data/synthetic_west --out out_west --as-of 2026-10-01
# open out_west/index.html in a browser
uv run python examples/mcp_client.py --west "Harbor Foods"   # same question, asked by four different people
```

`data/synthetic_west` is an invented US software vendor with 25 customers and realistic mess. The pilot command
takes about a second. You'll see:

- 59 stale CRM values, 16 customers with duplicate CRM accounts, 6 merges for a person to confirm, and 6 contracts
  renewing in the next 180 days, some with a "give notice by" date;
- in `crm_fixes.csv`, Harbor Foods' CRM contract value 1,190,000 → 1,468,000, with the signed contract as evidence;
- in the MCP demo: the RevOps admin sees the contract value; the sales rep sees only the CRM view, flagged as
  partial; legal sees the contract but not the owner; the intern sees nothing.

The full walkthrough for a sales call is [`docs/sales/DEMO_SCRIPT.md`](docs/sales/DEMO_SCRIPT.md).

## Running it for a client

The engagement is a two-week audit on the client's own machine. The full runbook, with Docker commands, is
[`docs/DEPLOY.md`](docs/DEPLOY.md); day-to-day operation is in
[`docs/product/OPERATIONS_RUNBOOK.md`](docs/product/OPERATIONS_RUNBOOK.md).

```
export/
  canon.json        per-client settings: CRM file and column names, currency, date order, own email domains, ACLs
  crm/              accounts.csv | .json | .xlsx   (or `canon pull hubspot|salesforce`, read-only)
  slack/ teams/ whatsapp/ email/   chat and email exports
  contracts/        PDF / DOCX / scans / .txt, any depth; _acl.json sidecars say who may read a folder
  identities.json   people → groups (from the client's role spreadsheet), optional SSO mapping
```

```bash
docker build -t canon .
docker run --rm --network none -v "$PWD/export:/data:ro" -v "$PWD/out:/out" canon check   # day 1
docker run --rm --network none -v "$PWD/export:/data:ro" -v "$PWD/out:/out" canon pilot   # the audit
# account owners answer review.html → overrides.json; rerun with --overrides; week 2: --compare
docker run --rm -v "$PWD/out:/out" -v "$PWD:/receipt" canon purge --out /out --yes \
  --receipt /receipt/deletion.json                                                         # the end
```

What to ask the client for: [`docs/DATA_REQUEST.md`](docs/DATA_REQUEST.md). Per-client differences are
configuration (`canon.json`), never code.

## What has been measured

All numbers are reproducible from the repository. "Real data" means public datasets Canon's authors did not write;
**no client data has been measured yet.** Everything in one place: [`docs/sales/PROOF.md`](docs/sales/PROOF.md).

| What | Data | Result |
|---|---|---|
| Permission leaks | Synthetic US company, 4,400 answers, 110 callers | Canon **0%**; keyword RAG 43%, strong RAG 87% ([report](docs/reports/permission_report_west.md)) |
| Answer accuracy | 40 synthetic questions, 4 open models | Canon 97.5%, strong RAG 92.5% (difference **not** significant), keyword RAG 55–58% ([summary](docs/reports/eval_summary.md)) |
| Contract terms | 267 held-out SEC-filed US contracts (CUAD), lawyer answers | Parties 57% found / 99% precision; agreement date 66% / 94%; end date 33% / 91%; renewal notice 37% / 100% ([report](docs/reports/cuad_report.md)) |
| **Same real company across three systems** | 966 held-out US-listed companies: Wikidata (CRM-like), SEC EDGAR (finance), GLEIF (legal registry), 3,238 records | F1 0.804 vs 0.755 for exact names; all records of a company together for 58%; 16 wrong merges ([report](docs/reports/company_er_report.md)) |
| **Renamed customers** | Stale CRM account under the company's real former name (e.g. a pre-rename filing name) | 72% linked automatically, 24% more sent to a person; exact-name matching: 0% (same report) |
| Duplicate customers | US business listings (Fodors–Zagat), held-out | F1 0.948 vs 0.825 for exact names ([report](docs/reports/er_real_report.md)) |
| Duplicate customers | French company registry vs shop signs (SIRENE) | 93% precision on automatic links; most shop signs need a person ([report](docs/reports/er_french_report.md)) |
| Arabic ↔ Latin names | 23k real names | 97.8% of true pairs at 0.85 similarity, 0.10% false matches ([report](docs/reports/arabic_names_report.md)) |
| OCR on scans | 361 real scanned receipts (SROIE) | Dates 63% right, 2% wrong, the rest withheld ([report](docs/reports/receipts_report.md)) |
| Synthetic regression set | 119 records, 25 customers; 50 regenerated seeds | ER F1 0.991 (mean over 50 seeds 0.991); current-fact accuracy 0.967 ([report](docs/reports/er_report.md)) |
| Scale | Synthetic look-alike customers | 47k records resolved in 31 s; lookups ~0.1 s ([report](docs/reports/scale_report.md)) |

The honest summary: Canon is **about as accurate as a well-built RAG**. What it adds is permissions enforced before
anything is read, a source for every fact, the refusal of unsafe values, and the fix list.

## Commands

| Command | What it does |
|---|---|
| `canon check --data DIR` | Day-1 intake check: what was found, parse failures, a suggested `canon.json` |
| `canon pilot --data DIR [--compare old/audit.json] [--overrides overrides.json]` | The whole engagement: check + audit + dashboard + run record |
| `canon audit` | The audit alone (report, fix files, review page, renewals) |
| `canon resolve [--report]` | Ingest + resolve into `out/`; `--report` scores against the synthetic answer key |
| `canon serve [--http --tokens ... \| --oidc-issuer ...]` | MCP server (stdio, or HTTP with bearer tokens / SSO); `GET /health` |
| `canon token add\|revoke --caller ID` | Issue or revoke HTTP tokens (stored hashed) |
| `canon pull hubspot\|salesforce` | Read-only CRM pull into the export format |
| `canon eval [--model ...] [--questions client.xlsx]` | Before/after evaluation against RAG baselines |
| `canon generate [--profile west]` | Regenerate the seeded synthetic datasets |
| `canon purge --out DIR [--yes]` | Delete an output folder (dry run by default) and print a deletion receipt |

## Repository layout

```
canon/
  ingest/        connectors (crm, slack, chat: Teams/WhatsApp, email, contracts + documents/OCR, pull),
                 parsing.py (refuse-don't-guess value parsing), extract.py (facts in messages),
                 contract_terms.py (free-form contract reader), deployment.py (canon.json)
  resolve/       normalize, features, blocking, scoring, cluster, golden, pipeline (+ overrides), evaluate
  score/         fact scoring: authority × freshness, conflicts
  mcp_server/    service (ACL before scoring), server (MCP tools, /health), auth (tokens, OIDC), audit log
  evals/         harness, agents (keyword RAG, hybrid RAG, oracle, Canon), questions, models, stats
  synth/         seeded synthetic generators (Moroccan profile; Western profile in west.py)
  audit.py       the audit (findings, stale values, renewals, week-2 comparison)
  deliver.py     HTML report, review page, CSV fix files
  pilot.py       `canon pilot`: dashboard and run record
  purge.py       `canon purge`: deletion with receipt
  intake.py      `canon check`
  guard.py       prompt-injection screening of source text
  store.py       SQLite persistence
  cli.py         the `canon` command
data/
  synthetic/       Moroccan-style dataset (French/Arabic, MAD): the main regression fixture
  synthetic_west/  US dataset (English, USD): for demos
  eval/            hand-written evaluation questions
scripts/         benchmarks on public real data (CUAD, Fodors–Zagat, SIRENE, SROIE, Arabic names), scale, permissions
examples/        a runnable MCP client
tests/           1,278 tests, including adversarial parsing fixtures and a browser test of the review page
docs/            method notes, decisions, reports, product and sales documents (see the map below)
```

## Design principles

- **Refuse rather than guess.** An ambiguous value is quarantined with a reason code and a hint for a person; a
  wrong value is never produced silently. Every new format gets adversarial test cases
  (`tests/fixtures/parsing_cases.json`).
- **Every fact cites its source**: file and page/line, CRM row, or message.
- **Permissions before scoring.** A record the caller may not read is never considered, so it cannot leak through a
  confidence score or an alternative.
- **People have the last word.** Merges and corrections in `overrides.json` are applied on every run, cited as
  "Confirmed by … on …", and still age like any other evidence.
- **Configuration, not code, per client.** Conventions and mappings live in `canon.json`; core packages contain no
  client-specific logic.
- **The answer key is only for evaluation.** `ground_truth/` is read by evaluation code and tests, never by the
  ingest, resolve or score logic.
- **Measure, and report honestly.** Tuning on a dev half, reporting a held-out half; rejected ideas are recorded
  too ([`docs/DECISIONS.md`](docs/DECISIONS.md), 98 decisions so far).

## Security and data handling

- Ingestion runs in Docker with `--network none`, as a non-root user, with the export mounted read-only.
- The HTTP server binds to localhost by default; TLS and rate limiting come from the client's reverse proxy.
- Tokens are stored as SHA-256 hashes; identity comes from the token or OIDC JWT, never from the request.
- Dependencies are scanned with `pip-audit` in CI; known vulnerabilities in pillow and pypdf were fixed.
- `canon purge` deletes outputs and prints a receipt. Files are unlinked, not overwritten, so disk encryption
  remains the client's control.
- **Not certified:** no SOC 2 report, no penetration test, no compliance claims (GDPR, CCPA, EU AI Act).
  Accepted risks are listed in [`docs/product/SECURITY_REVIEW.md`](docs/product/SECURITY_REVIEW.md).

## The business

- **Market:** US first, then the UK and EU.
- **Buyer (hypothesis):** VP RevOps or CRO at a 200–2,000 employee B2B company on Salesforce or HubSpot that is
  rolling out AI agents on customer data.
- **Offer:** a fixed-price, two-week paid audit (design partner $15–25k, standard $35–50k), then an optional
  subscription for recurring audits and the agent server ($2–5k/month).

**All prices are untested hypotheses. No customer, partnership or certification exists yet.** Market evidence and
its sources are in [`docs/product/MARKET_RESEARCH.md`](docs/product/MARKET_RESEARCH.md); the pilot offer is
[`docs/sales/PILOT_PROPOSAL.md`](docs/sales/PILOT_PROPOSAL.md).

## Limitations

- Never run on a real customer's data. Real CRM APIs (pull), real identity providers (SSO) and real Teams, WhatsApp
  and email exports are tested with fixtures only.
- Batch, not live: every run re-reads the export. No write-back to the CRM; no hosted service.
- Permissions are what `identities.json` and the source settings say, not a live read of each system's sharing.
- Most contract end dates that depend on events ("12 months after go-live") are not computed.
- OCR withholds about a third of dates on poor scans; Outlook `.pst` archives must be converted first.

## Development

```bash
uv sync
uv run pytest -q                                   # 1,278 tests (the browser test needs Playwright)
uv run ruff check . && uv run ruff format --check .
uv run canon generate                              # tests assert data/synthetic matches the generator
uv run canon generate --profile west --out data/synthetic_west
uv run python scripts/cuad_benchmark.py --split dev   # real-data benchmarks download to ~/.cache/canon
```

Conventions are in [`CLAUDE.md`](CLAUDE.md): Python 3.12, pydantic v2, stdlib SQLite, rapidfuzz; no heavy
frameworks; synthetic data only in the repository; small commits; never push to `main`.

## Documentation map

| Need | Read |
|---|---|
| Current status, gates, blockers, next action | [`BUILD_STATUS.md`](BUILD_STATUS.md) |
| Architecture and code paths | [`docs/product/PRODUCT_ARCHITECTURE.md`](docs/product/PRODUCT_ARCHITECTURE.md), [`TECHNICAL_DESIGN.md`](docs/product/TECHNICAL_DESIGN.md) |
| What is implemented vs claimed | [`docs/product/IMPLEMENTATION_AUDIT.md`](docs/product/IMPLEMENTATION_AUDIT.md) |
| Requirements and roadmap | [`PRODUCT_REQUIREMENTS.md`](docs/product/PRODUCT_REQUIREMENTS.md), [`PRODUCT_ROADMAP.md`](docs/product/PRODUCT_ROADMAP.md) |
| Security, tests, deployment, operations | [`SECURITY_REVIEW.md`](docs/product/SECURITY_REVIEW.md), [`TESTING_REPORT.md`](docs/product/TESTING_REPORT.md), [`DEPLOYMENT.md`](docs/product/DEPLOYMENT.md), [`OPERATIONS_RUNBOOK.md`](docs/product/OPERATIONS_RUNBOOK.md), [`docs/DEPLOY.md`](docs/DEPLOY.md) |
| Method notes | [Parsing](docs/PARSING.md), [extraction](docs/EXTRACTION.md), [entity resolution](docs/ENTITY_RESOLUTION.md), [fact scoring](docs/FACT_SCORING.md), [documents/OCR](docs/DOCUMENTS.md), [MCP server](docs/MCP_SERVER.md), [evals](docs/EVALS.md) |
| Why things are the way they are | [`docs/DECISIONS.md`](docs/DECISIONS.md) |
| Market, buyers, competitors, positioning | [`docs/product/`](docs/product) (`MARKET_RESEARCH`, `BUYER_PERSONAS`, `COMPETITOR_ANALYSIS`, `PRODUCT_POSITIONING`) |
| Selling it | [`docs/sales/`](docs/sales): brief, deck outline, demo script, pilot proposal, pricing, objections, outreach, proof sheet |
| Scope and data request for a pilot | [`docs/AUDIT_SCOPE.md`](docs/AUDIT_SCOPE.md), [`docs/DATA_REQUEST.md`](docs/DATA_REQUEST.md) |
| Original plan and history | [`docs/PLAN.md`](docs/PLAN.md), [`docs/STATUS.md`](docs/STATUS.md) (superseded) |
