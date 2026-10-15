# Fact scoring (Milestone 3)

`canon/score/facts.py` turns every observation of a business fact (owner, contract value,
renewal date, contract start/number, signatory, address) into a scored, explainable answer.
Golden records carry the result in `GoldenRecord.facts[field]` as a `ResolvedFact`:
`value`, `confidence`, `last_updated`, `sources` (evidence for the winner), `alternatives`
(every losing value with its own score and evidence), `conflict` and `explanation`.

## Model

For each observation *i* of a field:

* **authority** = `authority[source]` × `status_factor[status]`
  * sources: contract 0.95 > CRM 0.75 > email 0.6 > Slack 0.45
  * status: active 1.0, archived 0.3, superseded 0.2
  * per-field overrides: `field_authority={"owner": {"slack": 0.8}}`
* **freshness** = 0.5 ^ (age / half-life). Half-lives: owner 60 days; contract value, renewal and
  signatory 365; contract start/number and address 730. A fact asserted for a **validity period**
  (contract terms are valid until the renewal date) does not age until that period ends.
  Undated observations get 0.5.
* **weight** = authority × freshness ∈ [0, 1]

Observations are grouped by value (case/accent/whitespace-insensitive; numbers within 0.5%).

* value score = noisy-OR of its weights, 1 − Π(1 − wᵢ), so independent agreeing sources reinforce
* winner = highest score (ties → most recent)
* **confidence** = score × share, where share = score / Σ scores of all values.
  Agreement keeps it high, and a close contest roughly halves it.
* losers are **never deleted**. They stay in `alternatives`, ready for `list_conflicts` (M4).

Each `Evidence` carries the source record's ACL, so M4 can filter facts per caller rather than
per entity.

Run: `uv run canon resolve --report --as-of 2026-10-01` (default `as_of` is today).

## Results (seed 20261001, as of 2026-10-01)

| Field | Canon | Latest wins | Authority wins | Truth kept |
|---|---|---|---|---|
| owner | **0.923** | 1.000 | 0.846 | 1.000 |
| contract_value | **1.000** | 0.769 | 1.000 | 1.000 |
| renewal_date | **1.000** | 0.769 | 1.000 | 1.000 |
| contract_start / address / signatory | 0.962 | 0.962 | 0.962 | 0.962 |
| **overall** | **0.968** | 0.904 | 0.955 | |

* Mean confidence is 0.74 on correct answers and 0.09 on wrong ones. Every fact with confidence
  ≥ 0.3 is correct (140/140), and all wrong answers sit below 0.3.
* Held-out seeds 1–50: mean fact accuracy 0.971, min 0.887.
* The 0.962 rows are the unresolved `tmf` Slack singleton, which has no observations for those
  fields.

## Known gaps / honest caveats

* **Owner.** The two misses are Slack ownership announcements posted 4–8 weeks after the CRM
  record was last edited. CRM's higher authority still wins at a 60-day half-life. Both are
  flagged (confidence ≈ 0.09), and the true owner is kept as the alternative. "Latest wins"
  scores 1.0 on owner only because the generator always makes the newest statement true, so I
  did not tune defaults to it. Teams that announce changes in Slack should set a
  `field_authority` override.
* CRM `LastModifiedDate` is record-level, so it overstates the freshness of individual fields.
  Field-level history (CRM audit logs) would fix that.
* Weights and half-lives are domain judgments, not learned. Calibration needs labelled real data.
