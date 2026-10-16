# Demo script (10 minutes, synthetic data)

Every command below was run on 2026-10-16 against the committed synthetic dataset (`aacf1f4`). Run them once before the
call: `uv sync && uv run canon resolve --as-of 2026-10-01` builds `out/`.

**Rule for the call:** this is synthetic data built by us. Say so at the start. Never present a number from it as a client
result.

## 0. Frame it (1 min)
"Your agents will answer from your CRM, Slack and contracts. I'll show you what goes wrong in a typical company's data, and
what we deliver in two weeks. This is a synthetic company, 25 customers, French, English and Darija, with Arabic names."

## 1. The mess (1 min)
```bash
python -c "import json; [print(r['Account Name'], '|', r['Owner'], '|', r['Annual Contract Value']) for r in json.load(open('data/synthetic/crm/accounts.json')) if 'atlas' in r['Account Name'].lower()]"
```
The output shows Atlas Logistique twice in the CRM: "Sté Atlas Logistique" (Nadia Berrada, 461,000 MAD) and "Atlas Log"
(Karim Tazi, "375.000 DH"). "Atlas Tours" is a *different* company with a similar name. Then open
`data/synthetic/contracts/CN-2024-107_v2.txt`: 461,000 MAD, and Article 12 "annule et remplace la version 1". Which
value and which owner should an agent give?

## 2. The audit (3 min): the deliverable
```bash
uv run canon audit --as-of 2026-10-01 | head -40
```
- Walk the **fix list**: stale contract values, stale renewal dates, stale owners, duplicate CRM accounts. Each item names who
  fixes it.
- Point at one example and open its source, e.g. *Marjana Distribution: CRM says 830,000, contract says 959,000*.
- Then **merges to confirm**: "we don't guess on borderline duplicates, we ask you."
- Then **quarantine**: "values we can't read safely are listed, never guessed."

## 3. Same question, different people (3 min): permissions
```bash
uv run python examples/mcp_client.py "Boulangerie Al Baraka"
```
- **Admin:** contract value 1,426,000 from the active contract; the stale 1,085,000 is shown as an alternative.
- **Sales rep:** 1,085,000 from the CRM, flagged *some sources are restricted*. She never sees the contract.
- **Legal:** sees the contract but not the owner. **Intern:** "No customer found."
- Say: "An agent built on the raw export would have shown the sales rep the legal-only contract. In our test that happened
  in 35 of 40 answers."

## 4. The honest numbers (1 min)
Open `docs/reports/eval_summary.md`.
- Canon vs keyword search: about +40 points.
- Canon vs a well-built RAG: **about the same accuracy**. Say it plainly.
- The difference that matters: **0 permission leaks against 35/40**, every fact cited, 3× less text read.
- "We'll measure all of this on *your* questions. That's what the audit is."

## 5. The ask (1 min)
"Two weeks, your export, 30 to 50 questions your team writes. It runs inside your network. You get the fix list, the
permission map and the before/after." Send `docs/DATA_REQUEST.md` after the call.

## If they ask
- **"Does it work on our data?"** Unknown until we run it. That's the point of the audit. OCR has been tested only on clean
  synthetic scans.
- **"Which AI do you use?"** None during ingestion and resolution. For the before/after test: whichever model you approve,
  including one you host.
- **"Why not just build RAG?"** You can, and it will be about as accurate. It won't enforce who may see what, cite facts,
  or tell you what's stale in your CRM.
- **"Security?"** It runs in your network with networking off. HTTP access uses per-user tokens stored as hashes, every call
  is logged, and instructions hidden in documents are withheld.

## Not verified yet (don't demo)
Connecting to Claude Desktop/Code (`docs/MCP_SERVER.md`) has not been tested on a real client machine.
