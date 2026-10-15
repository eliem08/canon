# Entity resolution (Milestone 2)

```
SourceRecord[] ─▶ features ─▶ blocking ─▶ pairwise scoring ─▶ clustering ─▶ golden records
                 (normalize)   (keys)      (log-odds → p)      (avg-link)    (survivorship + lineage)
```

Run it: `uv run canon resolve --report [--seeds N]` → `out/golden_records.json`,
`out/canon.sqlite`, `out/er_report.md`. Latest report: [`reports/er_report.md`](reports/er_report.md).

## 1. Normalization — `canon/resolve/normalize.py`
* **Fold**: NFKD, strip accents, lowercase (`Énergie` → `energie`).
* **Legal forms** removed: `SARL`, `S.A.R.L.`, `SARL AU`, `SA`, `S.A.`, `SAS`, `Ltd`, `Limited`,
  `Société à Responsabilité Limitée`, `Société Anonyme`, `Sté`, Arabic `ش.م.م` / `ش.م` / `شركة`,
  Darija-in-Latin `chrika` / `chrikat`. Stopwords (`de`, `la`, `dyal`, …).
* **Cross-script skeleton**: Arabic is transliterated letter-by-letter; Latin spellings are
  mapped to sound classes (`qu`→k, `ch/sh`→sh, `g(e/i)`→j, `ou`→w, Darija digits `3`/`7`/`9`).
  Vowels, `h`, `w`, `y` and the article (`al`/`el`, attached `ال`/`لل`) are dropped, since Arabic
  does not write short vowels. `Atlas Logistique`, `atlas lojistik` and `أطلس لوجيستيك` all give
  `tls ljstk`.
* **Acronyms** of Latin names (`Tanger Med Freight` → `tmf`).

## 2. Blocking — `blocking.py`
Records are compared only if they share a key: 3-char prefix of any skeleton token, 4-char
whole-skeleton prefix, acronym / short bare token, business domain, phone, or tax id (ICE).
Keys with more than 40 members are dropped. On the synthetic set this keeps 100% of true pairs
while skipping 94% of all pairs.

## 3. Pairwise scoring — `scoring.py`
Fellegi–Sunter style: each feature present on both sides adds log-odds evidence, a missing
feature adds nothing, and `p = sigmoid(prior + Σ evidence)`. Defaults (`ScoringConfig`):

| Feature | agree | disagree |
|---|---|---|
| prior | −3 | |
| name similarity (piecewise: 0→−4, .55→−2.5, .7→+.5, .8→+2.5, .9→+4, 1→+5) | | |
| business domain | +6 | −5 |
| phone (last 9 digits) | +5 | −1 (switchboard vs mobile) |
| tax id (ICE) | +9 | −9 |
| address (token-sort ≥ .85) | +2 | −0.5 (companies move) |
| city | +0.5 | −2 |

Name similarity is the max over token-sort ratio, space-insensitive ratio, prefix
(`atlaslog` ⊂ `atlaslogistique`), token-subset (`fennec` ⊂ `fennec software`), skeleton
similarity (×0.97, or ×0.8 when a skeleton has < 4 consonants), and acronym match (0.85).
**Cannot-link**: different tax ids, or different domains *and* different phones.

## 4. Clustering — `cluster.py`
Average-linkage agglomerative clustering over scored pairs (unscored pairs are neutral),
stopping at p < 0.5, never merging clusters that contain a cannot-link pair. Unlike connected
components, one weak bridge cannot chain two companies together.

## 5. Golden records — `golden.py`
Per-field survivorship; every field stores `value`, the supporting `record_ids` and the `rule`;
`members` is the lineage to every source record; `acl` is the union of member ACLs.

| Field | Rule |
|---|---|
| legal_name / name | active contract party, else most frequent Latin CRM name; `name` drops the legal form |
| arabic_name | any Arabic-script name seen |
| domain, phone, tax_id | source-weighted vote (contract 3, CRM 2, Slack 1) |
| address, city | active contract > CRM, most recent |
| owner | most recent dated statement from a non-archived record |
| contract_number / value / start, renewal_date | active (non-superseded) contract, else latest fact |

These business-fact rules are placeholders for Milestone 3 (freshness × authority scoring,
alternatives kept).

## Results (seed 20261001)

| | P | R | F1 |
|---|---|---|---|
| Canon, pairwise | 1.000 | 0.983 | **0.991** |
| Canon, B-cubed | 1.000 | 0.987 | 0.993 |
| Baseline, exact normalized name | 1.000 | 0.534 | 0.696 |

Held-out seeds 1–50: mean pairwise F1 0.992, min 0.969. Golden field accuracy: owner,
contract value and renewal date 1.00; domain/phone/tax id/address 0.96 (the one unresolved record).

## Known gaps
* Weights are hand-set, not learned. The synthetic generator and the resolver were written by the same
  team, so these numbers are an upper bound. Real data needs a labelled sample and EM/logistic fitting.
* An acronym-only Slack channel with no domain/e-mail (`tmf`) stays a singleton. That's the right
  call on the evidence, but it is a recall loss.
* Arabic names that are *translations* rather than transliterations (`مخبزة البركة` vs `Boulangerie
  Al Baraka`) match only on shared words; they rely on phone/tax id/domain.
* Average linkage is O(n² log n) in the worst case per block. Fine for thousands of records, but
  millions need a block-local implementation.
