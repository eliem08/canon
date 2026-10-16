# Fact extraction from messages

`canon/ingest/extract.py` reads owner, contract value and renewal date from chat messages. The Slack
connector uses it today; any free-text source (e-mail bodies) can use it too.

## Rules (default)
A field is extracted only if the message has a **cue** for it and no **blocker**. Patterns are FR / EN /
Darija / Arabic, matched on accent-folded text (`ExtractionRules`, overridable via `SlackConfig.rules`).

| Field | Cues (examples) | Blockers (examples) |
|---|---|---|
| owner | account owner, KAM, takes over, reprend le compte, prend le relais, géré par, passation, réattribué, katgeri | tâche/task/ticket/action/relance, was/until/ancien, à confirmer |
| contract_value | contrat, deal, signé/signed/closed, montant annuel, par an, /an, ACV, avenant, tla3, عقد | facture/invoice, remise/discount/avoir, MRR/mensuel, budget/proposition/devis, pénalité/acompte/paiement, si on/if we, concurrent, pas signé |
| renewal_date | renouvel-, renew-, échéance, expire, end date, jusqu'au, tajdid, تجديد | call/réunion/meeting/point/démo, facture/paiement, livraison, signé le |

Questions (`?`, `chkon`, `wach`, `est-ce que`, `who`) assert nothing. The owner is the single known user
the message names (a `<@U..>` mention, else a unique first name); two candidates means no owner. Values
go through the hardened parsers (`docs/PARSING.md`): counts and durations (`3 ans`, `40 utilisateurs`) are
removed first, and an ambiguous value is quarantined, not guessed.

## Optional LLM extractor
`extract_message(..., llm=model)` asks a model (`complete(prompt) -> str`) only for fields the rules left
empty. Its answer is **validated, never trusted**:
- `contract_value` must equal an amount the parsers find in the message;
- `renewal_date` must equal the date the parsers read from the message;
- `owner` must be the known user the message names.

Anything else is dropped and logged as `llm_value_not_in_source`. Off by default; no client data goes to
a model without the client's written consent (`docs/AUDIT_SCOPE.md`).

## Lineage
Every fact carries `source_ref` and `quote`, and both are returned by the MCP tools in each source:
- Slack: `<export>/<channel>#ts=<message ts>` plus the message text.
- Contracts: `<file>#p<page>:L<line>` (pages split on form feeds, as `pdftotext` emits them) plus the line.
- CRM: `<file>#id=<row id>`.

## Results
`tests/fixtures/slack_messages.json`: 92 hand-written messages, 26 **dev** (used while writing the rules)
and 66 **held-out** (33 assert nothing: invoices, discounts, proposals, task owners, meetings, questions).

| Set | Extractor | P | R | F1 | Negatives with a false fact |
|---|---|---|---|---|---|
| held-out | v1 (keyword `elif` chain) | 0.600 | 0.324 | 0.421 | 8 / 33 |
| held-out | **v2 rules** | **1.000** | **0.973** | **0.986** | **0 / 33** |
| dev | v1 | 0.857 | 0.750 | 0.800 | 2 / 11 |
| dev | v2 rules | 1.000 | 1.000 | 1.000 | 0 / 11 |

The held-out messages were written before the v2 rules, but by the same person, who then saw them while
debugging. One held-out miss exposed two general parser bugs, which were fixed: a date followed by a comma
was read as amounts, and `<@U07>` was read as 7. Treat 0.986 as optimistic. The remaining miss (H09,
"l'interlocutrice principale côté commercial") is left unfixed on purpose: adding its cue would just tune to
the test. The real check is a client's messages labelled by the client.
