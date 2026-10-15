# Entity resolution report

Dataset: 119 records, 25 true entities, 26 predicted clusters.

## Clustering quality

| Method | Precision | Recall | F1 |
|---|---|---|---|
| Canon — pairwise | 1.000 | 0.983 | **0.991** |
| Canon — B-cubed | 1.000 | 0.987 | **0.993** |
| Baseline (exact normalized name) — pairwise | 1.000 | 0.534 | **0.696** |

## Blocking

- candidate pairs: 396 of 7021 (reduction ratio 0.944)
- pair completeness (true pairs kept): 1.000

## Golden-record field accuracy (survivorship vs. ground truth current values)

| Field | Accuracy |
|---|---|
| owner | 1.000 |
| contract_value | 1.000 |
| renewal_date | 1.000 |
| domain | 0.962 |
| phone | 0.962 |
| tax_id | 0.962 |
| address | 0.962 |

## Robustness: held-out seeds

Regenerated the dataset with seeds 1–50 (same generator, different randomness) — pairwise F1 mean **0.992**, min **0.969**, 50/50 seeds ≥ 0.90.

## Errors

- **missed link** (E13, split into 2): `tmf` [slack:C0K57K0ZF0]
