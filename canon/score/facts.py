"""Fact scoring: freshness x authority -> confidence, with explicit conflict resolution.

For every field of an entity:

1. Each observation gets
   * **authority** from its source (contract > CRM > email > Slack) times a status
     multiplier (superseded and archived sources are heavily discounted);
   * **freshness** = 0.5 ** (age / half_life), with a per-field half-life. A fact
     asserted for a validity period (a contract term) does not age until that
     period ends.
   * **weight** = authority x freshness, in [0, 1].
2. Observations are grouped by normalized value. A value's score is the noisy-OR of
   its supporting weights: independent sources agreeing reinforce each other.
3. The highest-scoring value wins. confidence = score x share, where share is the
   winner's fraction of the total score across values. Agreement keeps confidence
   high, and a close contest halves it.
4. Every losing value is kept as an alternative with its own sources and score.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from canon.models import Evidence, ResolvedFact, ScoredValue, SourceRecord

DEFAULT_AUTHORITY = {"contract": 0.95, "crm": 0.75, "email": 0.6, "slack": 0.45}
DEFAULT_STATUS_FACTOR = {"active": 1.0, "archived": 0.3, "superseded": 0.2}
DEFAULT_HALF_LIFE_DAYS = {
    "owner": 60,  # account ownership rotates within quarters
    "contract_value": 365,
    "renewal_date": 365,
    "contract_start": 730,
    "contract_number": 730,
    "signatory": 365,
    "address": 730,
    # identity attributes (scored at query time by the MCP service) change rarely
    "phone": 1095,
    "domain": 1095,
    "city": 1095,
    "tax_id": 3650,
}
FACT_FIELDS = (
    "owner", "contract_value", "renewal_date", "contract_start", "contract_number",
    "signatory", "address",
)  # fmt: skip


@dataclass(frozen=True)
class FactScoringConfig:
    as_of: date | None = None  # None -> today
    authority: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_AUTHORITY))
    # Per-field overrides, e.g. {"owner": {"slack": 0.8}} where a team announces changes in Slack.
    field_authority: dict[str, dict[str, float]] = field(default_factory=dict)
    status_factor: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_STATUS_FACTOR))
    half_life_days: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_HALF_LIFE_DAYS))
    default_half_life_days: float = 365
    undated_freshness: float = 0.5
    numeric_tolerance: float = 0.005  # values within 0.5% are the same value

    def reference_date(self) -> date:
        return self.as_of or date.today()


def freshness(
    observed_at: date | None,
    as_of: date,
    half_life_days: float,
    valid_until: date | None = None,
    undated: float = 0.5,
) -> float:
    if observed_at is None:
        return undated
    start = observed_at
    if valid_until is not None:
        if as_of <= valid_until:
            return 1.0
        start = max(observed_at, valid_until)
    age = max((as_of - start).days, 0)
    return 0.5 ** (age / half_life_days)


def authority(
    source: str, status: str, config: FactScoringConfig, field_name: str | None = None
) -> float:
    base = config.field_authority.get(field_name or "", {}).get(source)
    if base is None:
        base = config.authority.get(source, 0.3)
    return base * config.status_factor.get(status, 1.0)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


def _same(a, b, tol: float) -> bool:
    if isinstance(a, int | float) and isinstance(b, int | float):
        return math.isclose(float(a), float(b), rel_tol=tol)
    return _fold(str(a)) == _fold(str(b))


def _noisy_or(weights: list[float]) -> float:
    p = 1.0
    for w in weights:
        p *= 1 - w
    return 1 - p


def score_field(
    name: str, records: list[SourceRecord], config: FactScoringConfig
) -> ResolvedFact | None:
    as_of = config.reference_date()
    half_life = config.half_life_days.get(name, config.default_half_life_days)
    groups: list[list[Evidence]] = []
    for r in records:
        for f in r.facts:
            if f.field != name:
                continue
            a = authority(r.source, r.status, config, name)
            fr = freshness(f.observed_at, as_of, half_life, f.valid_until, config.undated_freshness)
            ev = Evidence(
                record_id=r.record_id, source=r.source, status=r.status, value=f.value,
                observed_at=f.observed_at, authority=round(a, 4), freshness=round(fr, 4),
                weight=round(a * fr, 4), acl=list(r.acl), source_ref=f.source_ref, quote=f.quote,
            )  # fmt: skip
            for g in groups:
                if _same(g[0].value, f.value, config.numeric_tolerance):
                    g.append(ev)
                    break
            else:
                groups.append([ev])
    if not groups:
        return None
    scored = []
    for g in groups:
        g.sort(key=lambda e: (e.weight, e.observed_at or date.min), reverse=True)
        dated = [e.observed_at for e in g if e.observed_at]
        scored.append(
            ScoredValue(
                value=g[0].value,  # representative: the strongest observation's spelling
                score=round(_noisy_or([e.weight for e in g]), 4),
                last_updated=max(dated) if dated else None,
                sources=g,
            )
        )
    scored.sort(key=lambda s: (s.score, s.last_updated or date.min), reverse=True)
    win, losers = scored[0], scored[1:]
    total = sum(s.score for s in scored)
    share = win.score / total if total else 0.0
    confidence = round(win.score * share, 4)
    if losers:
        top = win.sources[0]
        explanation = (
            f"{len(scored)} conflicting values; kept {win.value!r} "
            f"(score {win.score:.2f}, best source {top.source}/{top.status} "
            f"from {top.observed_at}) over {losers[0].value!r} (score {losers[0].score:.2f})"
        )
    else:
        explanation = f"{len(win.sources)} source(s) agree"
    return ResolvedFact(
        field=name,
        value=win.value,
        confidence=confidence,
        last_updated=win.last_updated,
        sources=win.sources,
        alternatives=losers,
        conflict=bool(losers),
        explanation=explanation,
    )


def score_entity(
    records: list[SourceRecord],
    config: FactScoringConfig | None = None,
    fields: tuple[str, ...] = FACT_FIELDS,
) -> dict[str, ResolvedFact]:
    config = config or FactScoringConfig()
    out = {}
    for name in fields:
        resolved = score_field(name, records, config)
        if resolved is not None:
            out[name] = resolved
    return out
