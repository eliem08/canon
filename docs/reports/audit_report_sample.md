# MCP Readiness Audit: findings

*Facts as of 2026-10-01. Every number below comes from the exported data; the record ids let you check each one.*

## 1. Prioritized fix list

| # | Finding | Count | Impact | Who fixes it |
|---|---|---|---|---|
| 1 | CRM contract value disagrees with a more reliable or more recent source | 20 | 60 | Sales ops / CRM admin |
| 2 | CRM renewal date disagrees with a more reliable or more recent source | 20 | 60 | Sales ops / CRM admin |
| 3 | CRM account owner disagrees with a more reliable or more recent source | 15 | 45 | Sales ops / CRM admin |
| 4 | Customers with more than one active CRM account | 19 | 38 | CRM admin (merge accounts) |
| 5 | Borderline duplicate decisions a person should confirm | 23 | 23 | Account owners (answer in overrides.json) |
| 6 | Facts Canon could only answer with low confidence (sources disagree) | 13 | 13 | Sales ops (confirm the current value once) |
| 7 | CRM address disagrees with a more reliable or more recent source | 5 | 8 | Sales ops / CRM admin |
| 8 | Account owner changed in Slack but not in the CRM | 2 | 6 | Account owners / sales ops |

Examples:

- *stale_crm_contract_value*: Marjana Distribution: CRM says `830000.0`, current is `959000.0` (contract:CN-2024-142_v2)
- *stale_crm_contract_value*: Nour Packaging: CRM says `1335000.0`, current is `1706000.0` (contract:CN-2024-156_v2)
- *stale_crm_contract_value*: Bab Rayan Consulting: CRM says `385000.0`, current is `487000.0` (contract:CN-2023-226_v2)
- *stale_crm_renewal_date*: Marjana Distribution: CRM says `2026-03-01`, current is `2027-09-01` (contract:CN-2024-142_v2)
- *stale_crm_renewal_date*: Nour Packaging: CRM says `2026-01-01`, current is `2027-07-01` (contract:CN-2024-156_v2)
- *stale_crm_renewal_date*: Bab Rayan Consulting: CRM says `2025-04-01`, current is `2027-09-01` (contract:CN-2023-226_v2)
- *stale_crm_owner*: Marjana Distribution: CRM says `Salma El Idrissi`, current is `Imane Chraibi` (crm:0015g00007K2RCW)
- *stale_crm_owner*: Bab Rayan Consulting: CRM says `Omar Fassi`, current is `Youssef Benali` (crm:0015g0000ZS34AB)
- *stale_crm_owner*: Sahara Tours: CRM says `Salma El Idrissi`, current is `Omar Fassi` (crm:0015g00008WTTPY)
- *review_merges*: Kasbah Hospitality Group S.A ~ khg (0.56)
- *review_merges*: Kasbah Hospitality Group S.A. ~ khg (0.56)
- *review_merges*: Sté Kasbah Hospitality Group ~ khg (0.56)
- *stale_crm_address*: Atlas Tours: CRM says `55 Rue Allal Ben Abdellah`, current is `45 Avenue Mohammed V` (contract:CN-2024-114_v2)
- *stale_crm_address*: Atlas Logistique: CRM says `21 Rue Ibn Batouta`, current is `112 Boulevard Zerktouni` (contract:CN-2024-107_v2)
- *stale_crm_address*: Medina Pharma: CRM says `19 Rue Oued Sebou`, current is `86 Boulevard Zerktouni` (contract:CN-2023-198_v2)
- *owner_change_slack_only*: Fennec Software: CRM `Youssef Benali`, Slack says `Imane Chraibi`
- *owner_change_slack_only*: Rif Ciment: CRM `Imane Chraibi`, Slack says `Youssef Benali`

Impact = count × weight (3 for facts agents are asked about most: contract value, renewal date, owner; 2 for duplicates and unreadable values; 1 for review items). It is a ranking aid, not a measured cost.

## 2. What was ingested

119 source records: 50 contract, 50 crm, 19 slack (88 active, 6 archived, 25 superseded).

## 3. Duplicates

- 119 records describe **26 customers**; 25 customers appear more than once and 25 appear in more than one system.
- 19 customers have more than one live record **inside crm**.
- 4 customers have more than one live record **inside slack**.

Largest groups:

| Customer | Records |
|---|---|
| Atlas Logistique | 6: contract:CN-2024-107_v1, contract:CN-2024-107_v2, crm:0015g0000M0HJ0E, crm:0015g0000RTBQLA, crm:0015g0000SKPBB3, slack:C0K57GT61H |
| Medina Pharma | 6: contract:CN-2023-198_v1, contract:CN-2023-198_v2, crm:0015g00008EEL0X, crm:0015g0000PNDMSR, crm:0015g0000WAX21R, slack:C0Q4KQF31N |
| Zitoun Cosmetics | 6: contract:CN-2023-205_v1, contract:CN-2023-205_v2, crm:0015g0000PXAUW0, crm:0015g0000W8BEM4, slack:C0JN8J0YGW, slack:C0R4KRZT1H |
| Sahara Tech Solutions | 6: contract:CN-2024-121_v1, contract:CN-2024-121_v2, crm:0015g0000HHFN7R, crm:0015g0000K3QV1Y, slack:C01L6YDM40, slack:C028SSZ5RD |
| Fennec Software | 6: contract:CN-2024-268_v1, contract:CN-2024-268_v2, crm:0015g000045GR4X, crm:0015g0000JVLW6D, crm:0015g0000VL83VJ, slack:C0G95VPQ4R |
| Oasis Agro Export | 6: contract:CN-2023-170_v1, contract:CN-2023-170_v2, crm:0015g00007L6BQX, crm:0015g0000MLGP7X, crm:0015g0000MS430H, slack:C0GRA3T02W |
| Argan d'Or | 5: contract:CN-2023-219_v1, contract:CN-2023-219_v2, crm:0015g00009CNXAW, slack:C04C8VQRYN, slack:C0M4SY6288 |
| Sahara Tours | 5: contract:CN-2024-128_v1, contract:CN-2024-128_v2, crm:0015g00008WTTPY, crm:0015g0000WELQ0F, slack:C0KFCE7RZT |
| Chefchaouen Textiles | 5: contract:CN-2023-177_v1, contract:CN-2023-177_v2, crm:0015g0000TB9NBR, crm:0015g0000VVTYHL, slack:C0Q8FYPBD1 |
| Al Massira Transport | 5: contract:CN-2023-261_v1, contract:CN-2023-261_v2, crm:0015g0000BGTWN2, crm:0015g0000NDR1ZL, slack:C0P1V6TFLJ |

## 4. Conflicting and stale facts

| Field | Customers with conflicting values | Low-confidence answers |
|---|---|---|
| address | 6 | 0 |
| contract_number | 0 | 0 |
| contract_start | 25 | 0 |
| contract_value | 25 | 0 |
| owner | 22 | 13 |
| renewal_date | 25 | 0 |
| signatory | 0 | 0 |

**Stale CRM values** (60): the CRM disagrees with the value Canon kept from a more authoritative or more recent source.

| Customer | Field | CRM says | Current value | From | Confidence |
|---|---|---|---|---|---|
| Marjana Distribution | owner | Salma El Idrissi | Imane Chraibi | crm:0015g00007K2RCW | 0.37 |
| Marjana Distribution | contract_value | 830000.0 | 959000.0 | contract:CN-2024-142_v2 | 0.73 |
| Marjana Distribution | renewal_date | 2026-03-01 | 2027-09-01 | contract:CN-2024-142_v2 | 0.73 |
| Nour Packaging | contract_value | 1335000.0 | 1706000.0 | contract:CN-2024-156_v2 | 0.56 |
| Nour Packaging | renewal_date | 2026-01-01 | 2027-07-01 | contract:CN-2024-156_v2 | 0.56 |
| Bab Rayan Consulting | owner | Omar Fassi | Youssef Benali | crm:0015g0000ZS34AB | 0.14 |
| Bab Rayan Consulting | contract_value | 385000.0 | 487000.0 | contract:CN-2023-226_v2 | 0.78 |
| Bab Rayan Consulting | renewal_date | 2025-04-01 | 2027-09-01 | contract:CN-2023-226_v2 | 0.78 |
| Sahara Tours | owner | Salma El Idrissi | Omar Fassi | crm:0015g00008WTTPY | 0.09 |
| Sahara Tours | contract_value | 920000.0 | 968000.0 | contract:CN-2024-128_v2 | 0.54 |
| Sahara Tours | renewal_date | 2026-02-01 | 2027-04-01 | contract:CN-2024-128_v2 | 0.54 |
| Atlas Tours | owner | Leila Bennani | Nadia Berrada | crm:0015g000098EZ1H | 0.23 |
| Atlas Tours | contract_value | 630000.0 | 708000.0 | contract:CN-2024-114_v2 | 0.54 |
| Atlas Tours | renewal_date | 2026-04-01 | 2027-10-01 | contract:CN-2024-114_v2 | 0.54 |
| Atlas Tours | address | 55 Rue Allal Ben Abdellah | 45 Avenue Mohammed V | contract:CN-2024-114_v2 | 0.68 |
| Atlas Logistique | owner | Karim Tazi | Nadia Berrada | slack:C0K57GT61H | 0.48 |
| Atlas Logistique | contract_value | 375000.0 | 461000.0 | contract:CN-2024-107_v2 | 0.66 |
| Atlas Logistique | renewal_date | 2026-02-01 | 2027-12-01 | contract:CN-2024-107_v2 | 0.67 |
| Atlas Logistique | address | 21 Rue Ibn Batouta | 112 Boulevard Zerktouni | contract:CN-2024-107_v2 | 0.68 |
| Medina Pharma | contract_value | 510000.0 | 600000.0 | contract:CN-2023-198_v2 | 0.72 |
| Medina Pharma | renewal_date | 2025-06-01 | 2027-08-01 | contract:CN-2023-198_v2 | 0.72 |
| Medina Pharma | address | 19 Rue Oued Sebou | 86 Boulevard Zerktouni | contract:CN-2023-198_v2 | 0.60 |
| Zitoun Cosmetics | owner | Imane Chraibi | Leila Bennani | crm:0015g0000W8BEM4 | 0.67 |
| Zitoun Cosmetics | contract_value | 1005000.0 | 1241000.0 | contract:CN-2023-205_v2 | 0.72 |
| Zitoun Cosmetics | renewal_date | 2025-05-01 | 2027-05-01 | contract:CN-2023-205_v2 | 0.72 |

**Owner changes only Slack knows about** (2):

- Fennec Software: CRM `Youssef Benali` → `Imane Chraibi` (slack:C0G95VPQ4R)
- Rif Ciment: CRM `Imane Chraibi` → `Youssef Benali` (slack:C0ZNRV3PXG)

## 5. Values Canon refused to read (quarantine)

| Reason | Count |
|---|---|

Read under an assumption (kept, flagged): single_separator_read_as_thousands 16.


## 6. Merges to confirm

23 pair decisions are borderline (full list in `review_queue.json`; answers go in `overrides.json` and are applied on every run).

| Record | Record | Probability | Decision |
|---|---|---|---|
| Kasbah Hospitality Group S.A (contract:CN-2024-212_v1) | khg (slack:C0AQE7ZRNA) | 0.56 | merged |
| Kasbah Hospitality Group S.A. (contract:CN-2024-212_v2) | khg (slack:C0AQE7ZRNA) | 0.56 | merged |
| Sté Kasbah Hospitality Group (crm:0015g0000LQLZ0P) | khg (slack:C0AQE7ZRNA) | 0.56 | merged |
| Chrikat Sahara Tech (crm:0015g0000HHFN7R) | saharatour (slack:C0KFCE7RZT) | 0.43 | kept apart |
| Ste Sahara Tech Solutions SARL (contract:CN-2024-121_v1) | saharatech (slack:C01L6YDM40) | 0.40 | merged |
| Ste Sahara Tech Solutions SARL (contract:CN-2024-121_v2) | saharatech (slack:C01L6YDM40) | 0.40 | merged |
| أطلس لوجيستيك ش.م.م (crm:0015g0000RTBQLA) | atlaslog (slack:C0K57GT61H) | 0.61 | merged |
| saharatech (slack:C01L6YDM40) | saharatour (slack:C0KFCE7RZT) | 0.36 | kept apart |
| Sahara Tech Solutions S.A.R.L (crm:0015g0000K3QV1Y) | saharatech (slack:C01L6YDM40) | 0.64 | merged |
| saharatech (slack:C01L6YDM40) | sahara tech solutions (slack:C028SSZ5RD) | 0.64 | merged |

## 7. Permissions

Who can read which records (as configured; see the caveat below):

| Readable by | Records |
|---|---|
| exec, legal | 50 |
| exec, sales | 50 |
| sales | 19 |

| Caller | Groups | Records visible | Customers visible | Customers seen only in part |
|---|---|---|---|---|
| ceo | exec | 100 | 25 | 14 |
| hind.legal | legal | 50 | 25 | 25 |
| imane.chraibi | sales | 69 | 26 | 25 |
| intern | — | 0 | 0 | 0 |
| karim.tazi | sales | 69 | 26 | 25 |
| leila.bennani | sales | 69 | 26 | 25 |
| mehdi.alaoui | sales | 69 | 26 | 25 |
| nadia.berrada | sales | 69 | 26 | 25 |
| omar.fassi | sales | 69 | 26 | 25 |
| revops.admin | exec, legal, sales | 119 | 26 | 0 |
| salma.el.idrissi | sales | 69 | 26 | 25 |
| youssef.benali | sales | 69 | 26 | 25 |

A caller who sees a customer only in part gets answers from the sources they may read, flagged `partial_view`. An agent built on the raw export would read every source for everyone.

Possible prompt injections in source text: **0** (listed in `quarantine.json`).

## Caveats

- Permissions are what the export and the role mapping say, not a live read of each system's sharing settings.
- "Stale" means a more authoritative or more recent source disagrees, using the scoring rules in `docs/FACT_SCORING.md`. The value Canon keeps can itself be wrong; low-confidence items are the ones to confirm first.
- Duplicate counts depend on entity resolution; borderline decisions are listed in section 6.
