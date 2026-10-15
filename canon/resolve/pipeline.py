"""End-to-end entity resolution: features -> blocking -> scoring -> clustering -> golden."""

from __future__ import annotations

from dataclasses import dataclass, field

from canon.models import GoldenRecord, SourceRecord
from canon.resolve.blocking import candidate_pairs
from canon.resolve.cluster import cluster
from canon.resolve.features import RecordFeatures, features
from canon.resolve.golden import build_golden
from canon.resolve.scoring import PairScore, ScoringConfig, is_cannot_link, score_pair
from canon.score import FactScoringConfig


@dataclass(frozen=True)
class ResolverConfig:
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    match_threshold: float = 0.5
    max_block_size: int = 40
    facts: FactScoringConfig = field(default_factory=FactScoringConfig)


@dataclass
class Resolution:
    clusters: list[list[str]]
    golden: list[GoldenRecord]
    candidates: set[tuple[str, str]]
    scores: dict[tuple[str, str], PairScore]
    features: dict[str, RecordFeatures]


def resolve(records: list[SourceRecord], config: ResolverConfig | None = None) -> Resolution:
    config = config or ResolverConfig()
    feats = {r.record_id: features(r) for r in records}
    candidates = candidate_pairs(list(feats.values()), config.max_block_size)
    scores = {(a, b): score_pair(feats[a], feats[b], config.scoring) for a, b in candidates}
    cannot = {(a, b) for a, b in candidates if is_cannot_link(feats[a], feats[b])}
    clusters = cluster(
        list(feats),
        {pair: s.probability for pair, s in scores.items()},
        cannot,
        config.match_threshold,
    )
    by_id = {r.record_id: r for r in records}
    golden = [
        build_golden(f"C{i:04d}", [by_id[rid] for rid in members], config.facts)
        for i, members in enumerate(clusters, start=1)
    ]
    return Resolution(clusters, golden, candidates, scores, feats)
