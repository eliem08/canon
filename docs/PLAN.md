# Canon — Plan

Canon is an agent-ready data layer: it ingests messy company data, resolves
duplicate entities into golden records with lineage, scores every fact by
freshness and authority, and serves the result through a permission-aware MCP
server. The proof of value is a before/after eval of agent accuracy on raw
data vs. on Canon.

## Architecture

```
 raw sources                 canon.ingest            canon.resolve                 canon.score          canon.mcp_server
 ───────────                 ────────────            ─────────────                 ───────────          ────────────────
 CRM export (JSON)   ─┐                              normalize (case, accents,
 Slack export (JSON) ─┼──▶  SourceRecord[]  ──▶     translit, legal suffixes) ──▶ Fact[] with    ──▶  typed tools, ACL
 Contracts (text)    ─┘     (one schema,             block ─▶ pairwise score       freshness,          filtering per
                             ACL + timestamps)       ─▶ cluster ─▶ golden record   authority,          caller identity
                                                     (survivorship + lineage)      confidence,
                                                                                   alternatives
                                              ▼                    ▼                     ▼
                                          SQLite store (records, clusters, golden records, facts, lineage)
                                                                                                   ▲
                                                                     canon.evals: baseline agent (raw files) vs Canon agent (MCP)
```

Design principles

* **One record schema.** Every connector emits `SourceRecord`s: identity
  attributes (name, domain, phone, address, tax id), dated `Fact`s, status
  (active / archived / superseded), timestamps and an ACL. Everything
  downstream is source-agnostic.
* **Core is client-agnostic.** Connector quirks live in `canon.ingest`;
  thresholds, weights and source authority live in config objects with
  defaults, never in `if client == ...` branches.
* **Never delete evidence.** Clustering, survivorship and conflict resolution
  record *why*; losing values are kept as alternatives with lineage.
* **Deterministic and offline.** Seeded synthetic data, stdlib SQLite,
  no network or model calls in the core path; models are pluggable in evals.

## Data model (pydantic v2)

| Model | Key fields |
|---|---|
| `Fact` | `field`, `value`, `observed_at` (date the source asserts it), `record_id` |
| `SourceRecord` | `record_id` (`crm:<id>`, `slack:<channel>`, `contract:<file>`), `source`, `locator`, `name`, `alt_names`, `domain`, `phone`, `email`, `address`, `city`, `tax_id`, `status`, `updated_at`, `facts[]`, `acl[]` |
| `PairScore` | `left`, `right`, feature breakdown, `probability` |
| `Cluster` | `cluster_id`, `record_ids` |
| `GoldenRecord` | `entity_id`, `fields{name → FieldValue(value, record_ids, rule)}`, `members[]` (lineage to every record), `acl` (union of members) |
| `ResolutionReport` | pairwise P/R/F1, B-cubed P/R/F1, blocking pair-completeness & reduction ratio, golden-field accuracy |

SQLite tables: `records`, `facts`, `clusters`, `golden_fields`, `lineage`.

## Milestones

1. **Synthetic messy dataset** — seeded generator (`canon.synth`) producing
   25 fictional Moroccan/French/English customers, each appearing 3–6 times
   across a CRM JSON export, a Slack export (incl. archived channel with
   stale info) and contract texts (2 versions each, one superseded). Mixed
   French, Arabic script and Darija-in-Latin. Hidden ground truth maps every
   record to its entity and lists the current value of each fact.
2. **Entity resolution** — normalization (case, accents, Arabic↔Latin
   consonant skeleton, legal suffixes, street abbreviations), multi-key
   blocking, Fellegi–Sunter-style pairwise scoring (name, domain, phone,
   address, tax id), average-linkage clustering with cannot-link constraints,
   golden records with per-field survivorship and lineage.
   Target pairwise F1 ≥ 0.90.
3. **Fact scoring** — freshness (exponential age decay, per-field half-life),
   authority (contract > CRM > email > Slack, archived/superseded penalties),
   combined confidence in [0,1]; explicit conflict resolution keeping losers
   as alternatives.
4. **MCP server** — official MCP Python SDK; `get_customer`,
   `find_contract_terms`, `who_owns`, `list_conflicts`; each answer carries
   value, sources, last_updated, confidence, alternatives; caller identity →
   ACL filtering; example client + README for Claude.
5. **Eval harness** — 40 questions with ground truth; baseline agent (keyword
   / embedding retrieval over raw files) vs Canon agent (MCP tools);
   model-agnostic with a stub model for CI; markdown report by question type
   with failure analysis.

Each milestone: tests, green CI (ruff + pytest), docs, PR with what changed /
how to run / metrics / known gaps.

## Tooling

Python 3.12, uv, pytest, ruff, pydantic v2, rapidfuzz (string similarity),
SQLite (stdlib), official `mcp` SDK (M4). CLI entry point: `canon`.
