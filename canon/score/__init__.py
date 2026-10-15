"""Fact scoring: freshness, authority, confidence and conflict resolution."""

from canon.score.facts import (
    FACT_FIELDS,
    FactScoringConfig,
    authority,
    freshness,
    score_entity,
    score_field,
)

__all__ = [
    "FACT_FIELDS",
    "FactScoringConfig",
    "authority",
    "freshness",
    "score_entity",
    "score_field",
]
