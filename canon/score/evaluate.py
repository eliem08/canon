"""Fact-scoring metrics against ground-truth current values (dicts passed in, no file IO)."""

from __future__ import annotations

from collections import Counter
from datetime import date

from canon.models import GoldenRecord, SourceRecord
from canon.score.facts import DEFAULT_AUTHORITY

CONFIDENCE_BUCKETS = ((0.0, 0.3), (0.3, 0.6), (0.6, 1.01))
EVAL_FIELDS = ("owner", "contract_value", "renewal_date", "contract_start", "address", "signatory")


def _match(predicted, expected) -> bool:
    if predicted is None:
        return False
    if isinstance(expected, int | float):
        try:
            return abs(float(predicted) - float(expected)) < 0.5
        except (TypeError, ValueError):
            return False
    return str(predicted) == str(expected)


def _baseline(records: list[SourceRecord], name: str, strategy: str):
    """Naive resolvers: newest observation wins / most authoritative source wins."""
    obs = [(r, f) for r in records for f in r.facts if f.field == name]
    if not obs:
        return None
    if strategy == "latest":
        key = lambda rf: (rf[1].observed_at or date.min,)  # noqa: E731
    else:
        key = lambda rf: (DEFAULT_AUTHORITY.get(rf[0].source, 0), rf[1].observed_at or date.min)  # noqa: E731
    return max(obs, key=key)[1].value


def fact_report(
    golden: list[GoldenRecord],
    records: list[SourceRecord],
    truth_records: dict[str, str],
    truth_entities: dict[str, dict],
    fields: tuple[str, ...] = EVAL_FIELDS,
) -> dict:
    by_id = {r.record_id: r for r in records}
    rows = {f: Counter() for f in fields}
    calibration = {b: Counter() for b in CONFIDENCE_BUCKETS}
    conf_ok: list[float] = []
    conf_bad: list[float] = []
    failures = []
    for g in golden:
        eid = Counter(truth_records[m] for m in g.members).most_common(1)[0][0]
        members = [by_id[m] for m in g.members]
        for name in fields:
            expected = truth_entities[eid].get(name)
            fact = g.facts.get(name)
            got = fact.value if fact else None
            ok = _match(got, expected)
            row = rows[name]
            row["n"] += 1
            row["canon"] += ok
            row["latest"] += _match(_baseline(members, name, "latest"), expected)
            row["authority"] += _match(_baseline(members, name, "authority"), expected)
            if fact:
                row["conflicts"] += fact.conflict
                candidates = [fact.value, *(a.value for a in fact.alternatives)]
                row["truth_retained"] += any(_match(c, expected) for c in candidates)
                (conf_ok if ok else conf_bad).append(fact.confidence)
                bucket = next(b for b in CONFIDENCE_BUCKETS if fact.confidence < b[1])
                calibration[bucket]["n"] += 1
                calibration[bucket]["correct"] += ok
            if not ok:
                failures.append(
                    {
                        "entity": eid,
                        "cluster": g.entity_id,
                        "field": name,
                        "expected": expected,
                        "got": got,
                        "explanation": fact.explanation if fact else "no observation",
                    }
                )
    total = Counter()
    for row in rows.values():
        total.update(row)

    def acc(row: Counter, key: str) -> float:
        return round(row[key] / row["n"], 4) if row["n"] else 0.0

    per_field = {
        name: {k: acc(row, k) for k in ("canon", "latest", "authority", "truth_retained")}
        | {"conflicts": row["conflicts"], "n": row["n"]}
        for name, row in rows.items()
    }
    return {
        "per_field": per_field,
        "overall": {k: acc(total, k) for k in ("canon", "latest", "authority")},
        "mean_confidence_correct": round(sum(conf_ok) / len(conf_ok), 4) if conf_ok else None,
        "mean_confidence_wrong": round(sum(conf_bad) / len(conf_bad), 4) if conf_bad else None,
        "calibration": [
            {
                "bucket": f"{lo:.1f}-{min(hi, 1.0):.1f}",
                "n": c["n"],
                "accuracy": round(c["correct"] / c["n"], 4) if c["n"] else None,
            }
            for (lo, hi), c in calibration.items()
        ],
        "failures": failures,
    }
