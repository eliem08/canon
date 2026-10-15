# Decisions log

Ambiguities resolved by picking the simplest reasonable option.

| # | Date | Decision | Why |
|---|---|---|---|
| 1 | 2026-10-15 | One branch / one PR for Plan + M1 + M2 in this session, with one commit series per milestone. | The session is pinned to a single development branch; stacked PRs would need extra branches. Later milestones get their own PRs. |
| 2 | 2026-10-15 | Storage is stdlib SQLite (not DuckDB). | Zero extra dependency; data volumes are tiny; easy to swap later behind `canon.store`. |
| 3 | 2026-10-15 | Synthetic world: Moroccan B2B customers of a fictional vendor ("Tadamon Solutions"), amounts in MAD, reference date 2026-10-01. | Naturally mixes French, Arabic script and Darija-in-Latin, which is the hard case Canon targets. |
| 4 | 2026-10-15 | "Contracts/PDF" are stored as the text a PDF extractor would output (`.txt`), not binary PDFs. | Keeps the repo diffable and avoids a PDF dependency; a PDF→text step slots in front of the same parser. |
| 5 | 2026-10-15 | Slack records are per *account channel* (`client-*`, `acc-*`, `deal-*`, `ext-*`, archived `old-*`), not per message. Mentions in multi-customer channels are out of scope. | Account channels are the common real-world pattern; per-message mentions in shared channels need NER (later). |
| 6 | 2026-10-15 | Every customer has exactly one contract with exactly two versions (v2 supersedes v1); appearance count 3–6 = 2 contract versions + 1–3 CRM + 0–2 Slack channels. | Satisfies "2 versions per contract, one superseded" and "3–6 appearances" with the simplest structure. |
| 7 | 2026-10-15 | ACLs are assigned per source by the connector (CRM → sales+exec, Slack → sales, contracts → legal+exec), overridable via connector config. | Native exports do not carry ACLs; source-level policy is the simplest enforceable model. |
| 8 | 2026-10-15 | ER quality is reported as pairwise P/R/F1 (primary, the F1 ≥ 0.90 target) plus B-cubed. | Pairwise is the conventional ER metric; B-cubed is less sensitive to large clusters. |
| 9 | 2026-10-15 | Pairwise weights are hand-set log-odds in `ScoringConfig`, not learned. | No labelled real data yet; explainable and tunable per deployment. Learning (EM / logistic) is planned once labels exist. |
| 10 | 2026-10-15 | Match threshold p ≥ 0.5 with average-linkage clustering + cannot-link (tax id conflict, or domain *and* phone conflict). | Simplest scheme that prevents transitive chaining between confusers. |
| 11 | 2026-10-15 | Skeleton matches with < 4 consonants are discounted (×0.8). | Found on held-out seed 4: acronym `brc` and `baraka` share skeleton `brk`. General rule (short keys carry little information), not tuned to one record. |
| 12 | 2026-10-15 | Robustness is reported on held-out generator seeds (1–50) besides the committed seed. | Guards against tuning to one sample. It is still the same generator, so it is not a substitute for real data. |
| 13 | 2026-10-15 | Golden business fields (owner, contract value, renewal) use simple survivorship in M2; M3 replaces them with scored facts. | Keeps M2 focused on identity; lineage is already in place for M3. |
| 14 | 2026-10-15 | Slack facts are extracted with multilingual cue patterns (FR/EN/Darija keywords + `<@U..>` mentions), not an LLM. | Deterministic and testable in CI; an LLM extractor can sit behind the same `Fact` interface later. |
