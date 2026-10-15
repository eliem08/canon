# Synthetic messy dataset (Milestone 1)

Fully fictional, seeded (`canon generate`, default seed `20261001`, reference date 2026-10-01).
Regenerating with the same seed reproduces these files byte-for-byte (checked in CI).

| Path | Format | What is messy |
|---|---|---|
| `crm/accounts.json` | Salesforce-like account export | duplicates per customer, typos, ALL-CAPS, `SARL`/`S.A.R.L.`/`Société Anonyme`/`Ltd`/`Limited` variants, Arabic-script and Darija ("Chrikat …") names, free-mail emails, 6 phone formats, money as numbers or strings (`450k MAD`, `1.200.000 DH`), mixed date formats, stale owner / value / renewal / address on older duplicates |
| `slack/` | Slack workspace export (`users.json`, `channels.json`, `<channel>/<day>.json`) | per-account channels named with informal aliases (`acc-atlaslog`, `client-khg`), Darija/French chatter, `<@U..>` owner mentions, archived `old-*` channels with outdated owner/value |
| `contracts/*.txt` | text extracted from contract PDFs (FR or EN) | 2 versions per contract; v2 "annule et remplace" / "supersedes" v1; legal name variants; Arabic party line; moved addresses |
| `ground_truth/ground_truth.json` | **hidden answer key** | `records`: record_id → entity id; `entities`: current correct facts; `record_notes`: why each record is messy |

Record ids: `crm:<Id>`, `slack:<channel id>`, `contract:<file stem>`.

25 customers, 119 records, each customer appearing 3–6 times. Deliberate confusers:
Atlas Logistique / Atlas Tours, Sahara Tech / Sahara Tours, Nour Énergie / Nour Packaging,
and two customers on the same boulevard in Casablanca.
