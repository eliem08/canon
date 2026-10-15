"""Pairwise match scoring (Fellegi–Sunter style log-odds with hand-set weights).

Each comparable feature adds agreement or disagreement evidence; a missing
feature adds nothing. The sum (plus a prior) goes through a sigmoid to give a
match probability in [0, 1]. Weights live in `ScoringConfig` so they can be
re-tuned per deployment without code changes.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from canon.resolve.features import RecordFeatures


@dataclass(frozen=True)
class ScoringConfig:
    prior: float = -3.0
    # name similarity -> evidence, piecewise linear between these points
    name_curve: tuple[tuple[float, float], ...] = (
        (0.0, -4.0),
        (0.55, -2.5),
        (0.7, 0.5),
        (0.8, 2.5),
        (0.9, 4.0),
        (1.0, 5.0),
    )
    domain_agree: float = 6.0
    domain_disagree: float = -5.0
    phone_agree: float = 5.0
    phone_disagree: float = -1.0  # switchboard vs. contact mobile is common
    tax_agree: float = 9.0
    tax_disagree: float = -9.0
    address_agree: float = 2.0  # similarity >= address_threshold
    address_disagree: float = -0.5  # companies move; weak evidence
    address_threshold: float = 0.85
    city_agree: float = 0.5
    city_disagree: float = -2.0


@dataclass
class PairScore:
    left: str
    right: str
    evidence: dict[str, float] = field(default_factory=dict)
    name_similarity: float = 0.0
    probability: float = 0.0

    @property
    def total(self) -> float:
        return sum(self.evidence.values())


def _interp(x: float, curve: tuple[tuple[float, float], ...]) -> float:
    for (x0, y0), (x1, y1) in itertools.pairwise(curve):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return curve[-1][1]


def _pair_name_similarity(a: str, b: str) -> float:
    """Similarity of two normalized names in [0, 1]."""
    if not a or not b:
        return 0.0
    sort = fuzz.token_sort_ratio(a, b) / 100
    joined_a, joined_b = a.replace(" ", ""), b.replace(" ", "")
    joined = fuzz.ratio(joined_a, joined_b) / 100
    # one name is a prefix/abbreviation of the other ("atlaslog" ~ "atlas logistique")
    shorter, longer = sorted((joined_a, joined_b), key=len)
    prefix = 0.0
    if len(shorter) >= 4 and longer.startswith(shorter):
        prefix = 0.82 + 0.1 * len(shorter) / len(longer)
    # all tokens of the shorter name appear in the longer one ("fennec" ~ "fennec software")
    ta, tb = set(a.split()), set(b.split())
    subset = 0.0
    small, big = sorted((ta, tb), key=len)
    if small and small <= big:
        subset = 0.8 + 0.15 * len(small) / len(big)
    return max(sort, joined, prefix, subset)


def name_similarity(fa: RecordFeatures, fb: RecordFeatures) -> float:
    best = 0.0
    for a in fa.names:
        for b in fb.names:
            best = max(best, _pair_name_similarity(a, b))
    for a in fa.skeletons:
        for b in fb.skeletons:
            # Short skeletons ("brk" from both "brc" and "baraka") carry little information.
            informative = min(len(a.replace(" ", "")), len(b.replace(" ", ""))) >= 4
            best = max(best, (0.97 if informative else 0.8) * _pair_name_similarity(a, b))
    # acronym against a short single-token name ("khg" vs "Kasbah Hospitality Group")
    short_a = {n for n in fa.names if " " not in n and 2 <= len(n) <= 4}
    short_b = {n for n in fb.names if " " not in n and 2 <= len(n) <= 4}
    if (short_a & set(fb.acronyms)) or (short_b & set(fa.acronyms)):
        best = max(best, 0.85)
    return best


def score_pair(fa: RecordFeatures, fb: RecordFeatures, cfg: ScoringConfig) -> PairScore:
    s = PairScore(left=fa.record_id, right=fb.record_id)
    s.evidence["prior"] = cfg.prior
    s.name_similarity = name_similarity(fa, fb)
    s.evidence["name"] = _interp(s.name_similarity, cfg.name_curve)
    if fa.domain and fb.domain:
        s.evidence["domain"] = cfg.domain_agree if fa.domain == fb.domain else cfg.domain_disagree
    if fa.phone and fb.phone:
        s.evidence["phone"] = cfg.phone_agree if fa.phone == fb.phone else cfg.phone_disagree
    if fa.tax_id and fb.tax_id:
        s.evidence["tax_id"] = cfg.tax_agree if fa.tax_id == fb.tax_id else cfg.tax_disagree
    if fa.address and fb.address:
        sim = fuzz.token_sort_ratio(fa.address, fb.address) / 100
        s.evidence["address"] = (
            cfg.address_agree if sim >= cfg.address_threshold else cfg.address_disagree
        )
    if fa.city and fb.city:
        s.evidence["city"] = cfg.city_agree if fa.city == fb.city else cfg.city_disagree
    s.probability = 1 / (1 + math.exp(-s.total))
    return s


def is_cannot_link(fa: RecordFeatures, fb: RecordFeatures) -> bool:
    """Hard conflicts: two different tax ids, or different domains *and* phones."""
    if fa.tax_id and fb.tax_id and fa.tax_id != fb.tax_id:
        return True
    return bool(
        fa.domain and fb.domain and fa.domain != fb.domain
        and fa.phone and fb.phone and fa.phone != fb.phone
    )  # fmt: skip
