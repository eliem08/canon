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
* **Acronyms** of Latin names (`Tanger Med Freight` → `tmf`), with and without company nouns
  (`Atlantic Fishing Company` → `afc` and `af`).

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

**Concept channel** (`lexicon.py`): name tokens map to bilingual concepts (`pharmacie` = `pharmacy` =
`صيدلية`, `banque` = `bank` = `بنك`, ...), so a French name and its Arabic *translation* can match.
Concept overlap scores × 0.95 when both names have ≥ 2 tokens.

**Guards** (log-odds, `ScoringConfig`), which apply when no identifier agrees (domain, tax id,
address, or a phone backed by name similarity ≥ 0.8):

| Guard | Weight | Catches |
|---|---|---|
| `type_mismatch`: both names have a business type and the types are disjoint | −6 | `Boulangerie Atlas` vs `Pharmacie Atlas` |
| `generic_name_no_identifier`: shared type is a local shop (pharmacy, café, hotel, garage...) | −4 | two `Pharmacie Al Amal`s |
| `city_conflict_no_identifier` | −2 | same name, different city |

A shared phone counts only +2 (not +5) when names are dissimilar: switchboards and agencies share
numbers.

## Human in the loop — `pipeline.py`
* **Review queue** (`out/review_queue.json`): pairs with probability in [0.2, 0.8), or near-identical
  names (≥ 0.9) a guard kept apart, most uncertain first, with the evidence and the decision taken.
* **Overrides** (`canon resolve --overrides overrides.json`, `{"must_link": [[a, b]], "cannot_link": [[a, b]]}`):
  a person's decisions win on every run, and decided pairs leave the queue.
* **Stable ids**: a cluster inherits the previous run's entity id (read from the existing
  `canon.sqlite`) it shares the most records with; new clusters get `E` + sha1 of their smallest record
  id. Adding records never renames existing entities.

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

Held-out seeds 1–50: mean pairwise F1 0.991, min 0.972 (0.994/0.975 before the guards; the guards
trade a little recall on synthetic data for precision on adversarial pairs). Golden field accuracy: owner,
contract value and renewal date 1.00; domain/phone/tax id/address 0.96 (the one unresolved record).

Adversarial pair suite (`tests/fixtures/er_pairs.json`, 50 hand-written pairs: generic names in other
cities, different business types, FR/AR translations, shared switchboards): precision 0.621 → **1.000**,
recall 0.783 → **0.962**.

## Real data: Fodors–Zagat
`uv run --with pyarrow python scripts/er_benchmark.py --split all`
([`reports/er_real_report.md`](reports/er_real_report.md)). This is the Magellan Fodors–Zagat
benchmark (from `lighteval/EntityMatching` on Hugging Face): restaurant listings from two guides, with
name, street address, city and phone, like CRM accounts written by different people. The resolver runs
with its default settings. Listings are split by entity into dev (used to find the fixes below) and
test (reported only).

| test half: 211 listings, 55 true matches | precision | recall | F1 |
|---|---|---|---|
| exact normalized name | 0.952 | 0.727 | 0.825 |
| Canon before the fixes below | 0.843 | 0.782 | 0.811 |
| **Canon now** | **0.902** | **1.000** | **0.948** |

The first run was worse than exact-name matching, and the reason was in the parsers, not the matcher.
* **Phones were all refused.** US numbers are dialled without a trunk `0` (`212-260-6660`), which the
  phone parser treated as "missing country or trunk prefix". Without phones, two restaurants at the same
  casino address merged, and the same restaurant with a new address split. Countries without a trunk
  prefix (`NANP`, Spain) now read national numbers when the deployment sets that `default_country`.
  `212/260 -6660` is also one number, not two, when no part of it is a phone on its own.
* **`new york` vs `new york city`** was a city conflict. The word for "city" (`city`, `ville de`) is no
  longer part of a city's name.

What's left on test: 6 false merges out of 61 merged pairs, mostly look-alike names at nearby
addresses with no phone or a shared switchboard. The dataset is US-only and English. It tests the
matching machinery on real spelling variation, not the French/Arabic lexicon.

## Real data: French companies (SIRENE registry, Soissons)
`uv run --with pyarrow python scripts/french_er_benchmark.py --split all`
([`reports/er_french_report.md`](reports/er_french_report.md)). INSEE's SIRENE registry for Soissons
(Licence Ouverte), 12k establishments. Each active establishment appears twice:
- as a **registry** record: legal name, full address and SIREN;
- as a **sales** record: the shop sign, usual name or acronym, the abbreviated address ("1 SQ DU DOCTEUR
  SALMON") and no tax id.

The answer key is the SIREN. All the text is real; only the pairing into two sources is ours.

| test half: 1,845 records, 1,374 companies | precision | recall | F1 | sales records linked | sent to review |
|---|---|---|---|---|---|
| exact normalized name | 0.967 | 0.241 | 0.386 | | |
| Canon before | 0.896 | 0.279 | 0.426 | 24% | (few) |
| **Canon now** | **0.907** | **0.290** | **0.439** | **29%** | **28%** |

It is hard because most shop signs share nothing with the legal name ("TEEN FASHIONS" for "LES LOUSTICS"). Canon does not
merge on an address alone, so those can only reach a person. What changed:
* **Acronyms the French way:**
  - letter-by-letter ("A V E C", "A.E.S.");
  - with or without linking words ("Association Vie **Et** Cancer" = AVEC, "Conseil **aux** Entreprises" = CE);
  - up to six letters (GEGOS, ADICE);
  - an acronym followed by a place ("ASK Soissons" = Association Sportive de Karting de Soissons).
* **Initialisms are held to an exact match:** "J.C.E." ≠ "J.S.E", and "LP" no longer matches "Laon Primeurs".
  Two-letter acronyms never count.
* **Address blocking and abbreviations:** blocking includes the street address (with its number). The French postal
  abbreviations (SQ, PL, CHE, IMP, ALL, RTE, QUA, FG…) are expanded.
* **Same address, different names:** when two records are the only ones at a street address but share no name, the
  pair goes to the **review queue** ("the only two records at this street address"), not to an automatic merge.

  On test, 103 shop-sign records that would have been invisible now reach a person, so 57% of them are either linked
  or put in front of someone.

What is left: 43% of shop signs share neither a name nor a unique address with their company (several businesses
at one address). Only a client's own identifiers (tax id, phone, e-mail) can link those.

## Real data: Arabic ↔ Latin names
`uv run python scripts/arabic_names_benchmark.py --split all`
([`reports/arabic_names_report.md`](reports/arabic_names_report.md)). 23k Arabic names with their English
transliterations (CC0). Each Arabic name is compared with its own transliteration and with a random other name.
The resolver never merges on a name alone; this measures the name channel.

| test, 3,000 names | true pairs reaching it | false pairs reaching it |
|---|---|---|
| similarity ≥ 0.8 | 99.4% | 0.33% |
| similarity ≥ 0.85 | 97.8% | 0.10% |

Short single-word names ("جبير" / "Jubayr") stop at 0.8 by design: a three-consonant skeleton ("jbr") is shared by too
many names to count as strong evidence on its own. The names are historical and personal, not company names.
Moroccan company names often contain such names ("Boulangerie Ben Ali"), but a client corpus is still the real test.

## Known gaps
* Weights are hand-set, not learned. The synthetic generator and the resolver were written by the same
  team, so these numbers are an upper bound. Real data needs a labelled sample and EM/logistic fitting.
* An acronym-only Slack channel with no domain/e-mail (`tmf`) stays a singleton. That's the right
  call on the evidence, but it is a recall loss.
* Translations are matched only for concepts in the lexicon (~40 business words). A one-word Arabic
  name (`زيتون`) vs `Zitoun Cosmetics` with only a shared phone stays apart (pair P22).
* The 50 adversarial pairs were written by the same team as the guards; a client's labelled sample
  is the real test.
* Average linkage is O(n² log n) in the worst case per block. Measured on look-alike synthetic data
  ([`reports/scale_report.md`](reports/scale_report.md)): 2 s at 1.2k records, 15 s at 4.7k, 52 s at
  11.8k. That growth is superlinear. It is fine for an offline audit of tens of thousands of
  records; millions need a block-local implementation.
