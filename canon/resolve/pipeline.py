"""End-to-end entity resolution: features -> blocking -> scoring -> clustering -> golden.

Human-in-the-loop pieces:
* **review queue**: borderline or guard-blocked pair decisions, for a person to confirm;
* **overrides**: must-link / cannot-link decisions that a person made, applied on every run;
* **stable ids**: an entity keeps its id across runs when its records mostly stay together.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from canon.models import GoldenRecord, SourceRecord
from canon.resolve.blocking import candidate_pairs
from canon.resolve.cluster import cluster
from canon.resolve.features import RecordFeatures, features
from canon.resolve.golden import build_golden
from canon.resolve.scoring import PairScore, ScoringConfig, is_cannot_link, score_pair
from canon.score import FactScoringConfig

GUARDS = ("type_mismatch", "generic_name_no_identifier", "city_conflict_no_identifier")


@dataclass(frozen=True)
class ResolverConfig:
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    match_threshold: float = 0.5
    max_block_size: int = 40
    facts: FactScoringConfig = field(default_factory=FactScoringConfig)
    review_band: tuple[float, float] = (0.2, 0.8)  # pair probabilities a human should see
    review_name_similarity: float = 0.9  # also review near-identical names a guard kept apart


class Overrides(BaseModel):
    """Decisions made by a person; they win over the model on every run."""

    must_link: list[tuple[str, str]] = Field(default_factory=list)
    cannot_link: list[tuple[str, str]] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None) -> Overrides:
        if path is None or not Path(path).exists():
            return cls()
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


class ReviewItem(BaseModel):
    left: str
    right: str
    left_name: str | None
    right_name: str | None
    probability: float
    name_similarity: float
    evidence: dict[str, float]
    decision: str  # "merged" | "kept apart"
    why: str


@dataclass
class Resolution:
    clusters: list[list[str]]
    golden: list[GoldenRecord]
    candidates: set[tuple[str, str]]
    scores: dict[tuple[str, str], PairScore]
    features: dict[str, RecordFeatures]
    review: list[ReviewItem] = field(default_factory=list)


def _key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def stable_ids(
    clusters: list[list[str]], previous: dict[str, list[str]] | None = None
) -> list[str]:
    """One id per cluster. A cluster inherits the previous id of the entity it shares the
    most records with (each previous id used once, largest overlaps first); other clusters
    get a content-derived id that does not depend on cluster order."""
    ids: list[str | None] = [None] * len(clusters)
    if previous:
        owner = {rid: eid for eid, members in previous.items() for rid in members}
        overlaps = []
        for i, members in enumerate(clusters):
            counts: dict[str, int] = {}
            for rid in members:
                if rid in owner:
                    counts[owner[rid]] = counts.get(owner[rid], 0) + 1
            overlaps += [(n, eid, i) for eid, n in counts.items()]
        used: set[str] = set()
        for _, eid, i in sorted(overlaps, key=lambda t: (-t[0], t[1], t[2])):
            if ids[i] is None and eid not in used:
                ids[i] = eid
                used.add(eid)
    taken = {i for i in ids if i}
    for i, members in enumerate(clusters):
        if ids[i] is None:
            digest = hashlib.sha1(min(members).encode("utf-8")).hexdigest()
            candidate, n = f"E{digest[:10]}", 1
            while candidate in taken:
                candidate, n = f"E{digest[:10]}-{n}", n + 1
            ids[i] = candidate
            taken.add(candidate)
    return [i for i in ids if i]


def resolve(
    records: list[SourceRecord],
    config: ResolverConfig | None = None,
    overrides: Overrides | None = None,
    previous: dict[str, list[str]] | None = None,
) -> Resolution:
    config = config or ResolverConfig()
    overrides = overrides or Overrides()
    feats = {r.record_id: features(r) for r in records}
    candidates = candidate_pairs(list(feats.values()), config.max_block_size)
    scores = {(a, b): score_pair(feats[a], feats[b], config.scoring) for a, b in candidates}
    cannot = {(a, b) for a, b in candidates if is_cannot_link(feats[a], feats[b])}
    probabilities = {pair: s.probability for pair, s in scores.items()}
    must = {_key(a, b) for a, b in overrides.must_link if a in feats and b in feats}
    never = {_key(a, b) for a, b in overrides.cannot_link if a in feats and b in feats}
    for pair in must:
        probabilities[pair] = 1.0
        cannot.discard(pair)
    for pair in never:
        probabilities.pop(pair, None)
        cannot.add(pair)
    clusters = cluster(list(feats), probabilities, cannot, config.match_threshold)
    ids = stable_ids(clusters, previous)
    by_id = {r.record_id: r for r in records}
    order = sorted(range(len(clusters)), key=lambda i: ids[i])
    clusters = [clusters[i] for i in order]
    golden = [
        build_golden(ids[i], [by_id[rid] for rid in members], config.facts)
        for i, members in zip(order, clusters, strict=True)
    ]
    res = Resolution(clusters, golden, candidates, scores, feats)
    res.review = review_queue(res, by_id, config, must | never)
    return res


def review_queue(
    res: Resolution,
    by_id: dict[str, SourceRecord],
    config: ResolverConfig,
    decided: set[tuple[str, str]],
) -> list[ReviewItem]:
    """Pair decisions a person should confirm, most uncertain first."""
    cluster_of = {rid: i for i, members in enumerate(res.clusters) for rid in members}
    lo, hi = config.review_band
    # records per street address (with a number) and city: two records alone at an address are
    # worth a person's look even when their names share nothing ("Teen Fashions" / "Les Loustics")
    at_address: Counter = Counter(
        (f.address, f.city) for f in res.features.values() if f.address[:1].isdigit() and f.city
    )
    items = []
    for (a, b), s in res.scores.items():
        if (a, b) in decided:
            continue
        fa, fb = res.features[a], res.features[b]
        guarded = [g for g in GUARDS if g in s.evidence]
        borderline = lo <= s.probability < hi
        blocked = bool(guarded) and s.name_similarity >= config.review_name_similarity
        merged = cluster_of[a] == cluster_of[b]
        alone = (
            not merged
            and fa.address
            and (fa.address, fa.city) == (fb.address, fb.city)
            and at_address[(fa.address, fa.city)] == 2
            and not is_cannot_link(fa, fb)
        )
        if not (borderline or blocked or alone):
            continue
        if blocked and not merged:
            why = f"guard {', '.join(guarded)} kept near-identical names apart"
        elif borderline:
            why = f"match probability {s.probability:.2f} is in the review band"
        else:
            why = "the only two records at this street address; names differ, so kept apart"
        items.append(
            ReviewItem(
                left=a,
                right=b,
                left_name=by_id[a].name,
                right_name=by_id[b].name,
                probability=round(s.probability, 4),
                name_similarity=round(s.name_similarity, 4),
                evidence={k: round(v, 2) for k, v in s.evidence.items()},
                decision="merged" if merged else "kept apart",
                why=why,
            )
        )
    items.sort(key=lambda i: (abs(i.probability - 0.5), i.left, i.right))
    return items


def write_review_queue(path: Path, items: list[ReviewItem]) -> None:
    path.write_text(
        json.dumps([i.model_dump() for i in items], ensure_ascii=False, indent=2), encoding="utf-8"
    )
