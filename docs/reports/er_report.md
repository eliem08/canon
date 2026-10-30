# Entity resolution and fact scoring report

Dataset: 119 records, 25 true entities, 26 predicted clusters.

## Clustering quality

| Method | Precision | Recall | F1 |
|---|---|---|---|
| Canon — pairwise | 1.000 | 0.983 | **0.991** |
| Canon — B-cubed | 1.000 | 0.987 | **0.993** |
| Baseline (exact normalized name) — pairwise | 1.000 | 0.534 | **0.696** |

## Blocking

- candidate pairs: 444 of 7021 (reduction ratio 0.937)
- pair completeness (true pairs kept): 1.000

## Golden-record field accuracy (survivorship vs. ground truth current values)

| Field | Accuracy |
|---|---|
| owner | 0.923 |
| contract_value | 1.000 |
| renewal_date | 1.000 |
| domain | 0.962 |
| phone | 0.962 |
| tax_id | 0.962 |
| address | 0.962 |

## Robustness: held-out seeds

Regenerated the dataset with seeds 1–50 (same generator, different randomness) — pairwise F1 mean **0.991**, min **0.972**, 50/50 seeds ≥ 0.90. Fact accuracy mean **0.967**, min **0.887**.

## Errors

- **missed link** (E13, split into 2): `tmf` [slack:C0K57K0ZF0]

## Fact scoring (freshness x authority)

Accuracy of the winning value per field against ground-truth *current* values, compared with two naive resolvers over the same clusters. `truth kept` = the true value is the winner or one of the retained alternatives.

| Field | Canon | Latest wins | Authority wins | Truth kept | Conflicts |
|---|---|---|---|---|---|
| owner | **0.923** | 1.000 | 0.846 | 1.000 | 22/26 |
| contract_value | **1.000** | 0.769 | 1.000 | 1.000 | 25/26 |
| renewal_date | **1.000** | 0.769 | 1.000 | 1.000 | 25/26 |
| contract_start | **0.962** | 0.962 | 0.962 | 0.962 | 25/26 |
| address | **0.962** | 0.962 | 0.962 | 0.962 | 6/26 |
| signatory | **0.962** | 0.962 | 0.962 | 0.962 | 0/26 |
| **overall** | **0.968** | 0.904 | 0.955 | | |

Mean confidence: 0.7397 when correct, 0.09 when wrong.

| Confidence | Facts | Accuracy |
|---|---|---|
| 0.0-0.3 | 13 | 0.846 |
| 0.3-0.6 | 29 | 1.000 |
| 0.6-1.0 | 111 | 1.000 |

### Fact failures

- E13 `contract_start`: expected `2026-06-01`, got `None` (no observation)
- E13 `address`: expected `Tanger Med Port Zone, Building B4`, got `None` (no observation)
- E13 `signatory`: expected `Hicham Amrani`, got `None` (no observation)
- E14 `owner`: expected `Leila Bennani`, got `Youssef Benali` (2 conflicting values; kept 'Youssef Benali' (score 0.17, best source crm/active from 2026-05-26) over 'Leila Bennani' (score 0.13))
- E11 `owner`: expected `Nadia Berrada`, got `Omar Fassi` (2 conflicting values; kept 'Omar Fassi' (score 0.16, best source crm/active from 2026-05-19) over 'Nadia Berrada' (score 0.14))
