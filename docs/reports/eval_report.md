# Canon eval: agent accuracy on raw data vs. on Canon

- Questions: 40 from `ground_truth/eval_questions.json` (contract_value 10, renewal_date 10, owner 10, phone 5, address 5)
- Model: `stub` (same model and prompt for every agent)
- Canon caller: `revops.admin`; facts as of 2026-10-01
- Baseline: BM25 keyword retrieval over raw CRM rows, Slack messages and contract texts (top 5 chunks)
- Oracle: every raw chunk of the right customer and nothing else (perfect retrieval, from the answer key). It shows what raw data supports at best.
- Canon: MCP tools (`get_customer` for linking any span of the question, then `find_contract_terms` / `who_owns` / `get_customer`)

## Overall

| Agent | Correct | Accuracy | 95% CI (Wilson) |
|---|---|---|---|
| Baseline (BM25 over raw files) | 24/40 | 60.0% | 45%–74% |
| Oracle retrieval (every raw record of the right customer) | 20/40 | 50.0% | 35%–65% |
| **Canon (MCP tools)** | 39/40 | 97.5% | 87%–100% |

Lift, Canon vs. baseline: **+37.5 pts**. On the same questions, Canon alone is right on 16 and the baseline alone on 1 (exact McNemar p = 0.00027).
Canon vs. oracle retrieval: **+47.5 pts**. That is the part of the lift that better retrieval alone would not give.

## Accuracy by question type

| Type | Questions | baseline | oracle | canon |
|---|---|---|---|---|
| contract_value | 10 | 60% | 30% | 100% |
| renewal_date | 10 | 80% | 40% | 100% |
| owner | 10 | 40% | 50% | 100% |
| phone | 5 | 60% | 80% | 80% |
| address | 5 | 60% | 80% | 100% |

Held-out check: regenerating the dataset with seeds 1–10 gives baseline **45.8%** (range 32%–62%) vs. Canon **97.2%** (range 92%–100%).

## Failure analysis

| Failure | baseline | oracle | canon |
|---|---|---|---|
| stale / superseded value of the right customer | 2 | 18 | 1 |
| value belonging to a different customer | 4 | 0 | 0 |
| no answer found | 10 | 0 | 0 |
| other | 0 | 2 | 0 |

Accuracy by how the customer was named:

| Mention style | Questions | baseline | oracle | canon |
|---|---|---|---|---|
| alias | 7 | 14% | 43% | 100% |
| arabic | 4 | 50% | 50% | 100% |
| canonical | 9 | 100% | 33% | 89% |
| darija | 3 | 67% | 67% | 100% |
| legal | 7 | 86% | 57% | 100% |
| lower | 8 | 38% | 62% | 100% |
| typo | 2 | 50% | 50% | 100% |

### Every miss

| Q | Question | Expected | baseline | oracle | canon |
|---|---|---|---|---|---|
| Q01 | Quel est le montant annuel actuel du contrat de Atlas Logistique ? | `461000` | ✓ | ✗ `375 MAD` (other) | ✓ |
| Q03 | Ch7al kaykhalsou f l3am daba, نسيج شفشاون? | `872000` | ✗ `800000 MAD` (stale_value) | ✗ `800 MAD` (other) | ✓ |
| Q04 | Quel est le montant annuel actuel du contrat de Rif Cement ? | `1666000` | ✗ `unknown` (no_answer) | ✗ `1380000 MAD` (stale_value) | ✓ |
| Q05 | Quel est le montant annuel actuel du contrat de Tanger Med Freight SARL ? | `1341000` | ✓ | ✗ `1215000 MAD` (stale_value) | ✓ |
| Q06 | Quel est le montant annuel actuel du contrat de مدينة فارما ? | `600000` | ✓ | ✗ `510000 MAD` (stale_value) | ✓ |
| Q07 | Ch7al kaykhalsou f l3am daba, Bab Rayan Consulting SARL? | `487000` | ✓ | ✗ `385000 MAD` (stale_value) | ✓ |
| Q08 | Ch7al kaykhalsou f l3am daba, atlantic fishing company? | `1858000` | ✗ `unknown` (no_answer) | ✓ | ✓ |
| Q09 | Ch7al kaykhalsou f l3am daba, Riad Digital Agency? | `1382000` | ✓ | ✗ `1300000 MAD` (stale_value) | ✓ |
| Q10 | Ch7al kaykhalsou f l3am daba, سوس فريش? | `536000` | ✗ `410000 MAD` (stale_value) | ✓ | ✓ |
| Q11 | When is the contract renewal date for Atlas Logisitque? | `2027-12-01` | ✗ `2026-06-01` (wrong_customer) | ✗ `2026-02-01` (stale_value) | ✓ |
| Q12 | Quelle est la date de renouvellement du contrat de Boulangerie Al Baraka ? | `2028-03-01` | ✓ | ✗ `2025-12-01` (stale_value) | ✓ |
| Q13 | Quelle est la date de renouvellement du contrat de Nour Packaging ? | `2027-07-01` | ✓ | ✗ `2026-01-01` (stale_value) | ✓ |
| Q14 | Quelle est la date de renouvellement du contrat de oasis agro export ? | `2027-06-01` | ✓ | ✗ `2025-12-01` (stale_value) | ✓ |
| Q15 | Imta ghadi ytjedded contrat dyal chrikat Medina Pharma? | `2027-08-01` | ✓ | ✗ `2025-06-01` (stale_value) | ✓ |
| Q17 | When is the contract renewal date for Argan d'Or S.A.? | `2027-09-01` | ✗ `2026-06-01` (wrong_customer) | ✓ | ✓ |
| Q20 | When is the contract renewal date for Yasmine Hotels? | `2027-05-01` | ✓ | ✗ `2025-08-01` (stale_value) | ✓ |
| Q21 | Chkoun l'owner dyal sahara tours? | `Omar Fassi` | ✗ `unknown` (no_answer) | ✗ `Salma El Idrissi` (stale_value) | ✓ |
| Q22 | Chkoun l'owner dyal marjana distribution? | `Imane Chraibi` | ✓ | ✗ `Salma El Idrissi` (stale_value) | ✓ |
| Q23 | Who is the account owner for chrikat Dar El Hana Immobilier? | `Salma El Idrissi` | ✗ `unknown` (no_answer) | ✓ | ✓ |
| Q24 | Chkoun l'owner dyal Rif Cement? | `Youssef Benali` | ✗ `unknown` (no_answer) | ✗ `Imane Chraibi` (stale_value) | ✓ |
| Q25 | Chkoun l'owner dyal Tanger Med Freight S.A.? | `Nadia Berrada` | ✓ | ✗ `Karim Tazi` (stale_value) | ✓ |
| Q27 | Qui est le responsable du compte argan d'or ? | `Nadia Berrada` | ✗ `unknown` (no_answer) | ✓ | ✓ |
| Q28 | Who is the account owner for Bab Rayan Consulting? | `Youssef Benali` | ✓ | ✗ `Omar Fassi` (stale_value) | ✓ |
| Q29 | Qui est le responsable du compte atlantic fishing company ? | `Mehdi Alaoui` | ✗ `unknown` (no_answer) | ✓ | ✓ |
| Q30 | Chkoun l'owner dyal Al Massira? | `Salma El Idrissi` | ✗ `unknown` (no_answer) | ✓ | ✓ |
| Q31 | What is the main phone number of Sahara Tech? | `+212592846751` | ✗ `unknown` (no_answer) | ✓ | ✓ |
| Q34 | Quel est le numéro de téléphone de Zitoun Cosmetics ? | `+212579101995` | ✓ | ✗ `+212670914607` (stale_value) | ✗ `+212670914607` (stale_value) |
| Q35 | Quel est le numéro de téléphone de AFC ? | `+212524415035` | ✗ `+212578098257` (wrong_customer) | ✓ | ✓ |
| Q37 | Quelle est l'adresse du siège social de dar el hana immobilier ? | `21 Avenue Hassan II` | ✗ `unknown` (no_answer) | ✓ | ✓ |
| Q40 | What is the registered office address of Yasmine? | `Avenue Mohammed VI, Malabata` | ✗ `Port de Dakhla` (wrong_customer) | ✗ `58 Rue Oued Sebou` (stale_value) | ✓ |

## Reading this report

- With the stub model, the answer is whatever the context literally contains first. This measures what each agent's *context* supports, not model reasoning. Run with a real model (`canon eval --model claude`) for the end-to-end number; the stub is a deterministic CI check. The stub's *oracle* number is not meaningful: given every record of a customer, it answers with the first value it finds, which is often the stale one. A real model weighs dates and sources.
- Confidence intervals are per agent; the McNemar test is the right comparison because both agents answer the same questions.
- The synthetic data and the questions were written by the same team that built Canon. Treat the lift as an upper bound until reproduced on a customer's data with the customer's questions.
