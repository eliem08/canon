"""Entity-resolution metrics against a ground-truth record -> entity mapping."""

from __future__ import annotations

from collections import Counter
from itertools import combinations

from pydantic import BaseModel

from canon.models import GoldenRecord


class PRF(BaseModel):
    precision: float
    recall: float
    f1: float

    @classmethod
    def from_counts(cls, tp: float, fp: float, fn: float) -> PRF:
        p = tp / (tp + fp) if tp + fp else 1.0
        r = tp / (tp + fn) if tp + fn else 1.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        return cls(precision=round(p, 4), recall=round(r, 4), f1=round(f, 4))


def _pairs(clusters: list[list[str]]) -> set[tuple[str, str]]:
    return {tuple(sorted(p)) for c in clusters for p in combinations(c, 2)}


def truth_clusters(truth: dict[str, str]) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    for rid, eid in truth.items():
        groups.setdefault(eid, []).append(rid)
    return [sorted(g) for g in groups.values()]


def pairwise(predicted: list[list[str]], truth: dict[str, str]) -> PRF:
    pred = _pairs(predicted)
    gold = _pairs(truth_clusters(truth))
    return PRF.from_counts(len(pred & gold), len(pred - gold), len(gold - pred))


def bcubed(predicted: list[list[str]], truth: dict[str, str]) -> PRF:
    cluster_of = {r: tuple(c) for c in predicted for r in c}
    p_sum = r_sum = 0.0
    gold_sizes = Counter(truth.values())
    for rid, eid in truth.items():
        cluster = cluster_of.get(rid, (rid,))
        correct = sum(1 for other in cluster if truth.get(other) == eid)
        p_sum += correct / len(cluster)
        r_sum += correct / gold_sizes[eid]
    n = len(truth)
    p, r = p_sum / n, r_sum / n
    f = 2 * p * r / (p + r) if p + r else 0.0
    return PRF(precision=round(p, 4), recall=round(r, 4), f1=round(f, 4))


def blocking_quality(candidates: set[tuple[str, str]], truth: dict[str, str]) -> dict:
    gold = _pairs(truth_clusters(truth))
    n = len(truth)
    total = n * (n - 1) // 2
    return {
        "candidate_pairs": len(candidates),
        "all_pairs": total,
        "reduction_ratio": round(1 - len(candidates) / total, 4) if total else 0.0,
        "pair_completeness": round(len(gold & candidates) / len(gold), 4) if gold else 1.0,
    }


def field_accuracy(
    golden: list[GoldenRecord], truth_records: dict[str, str], truth_entities: dict[str, dict]
) -> dict[str, float]:
    """Accuracy of survived golden-record fields, each golden record matched to the
    majority ground-truth entity of its members. Only entities reached by some
    cluster are scored; split entities count each cluster separately."""
    checks = {
        "owner": lambda g, t: g == t,
        "contract_value": lambda g, t: g is not None and abs(float(g) - float(t)) < 0.5,
        "renewal_date": lambda g, t: g == t,
        "domain": lambda g, t: g == t,
        "phone": lambda g, t: g == t,
        "tax_id": lambda g, t: g == t,
        "address": lambda g, t: g == t,
    }
    hits: Counter = Counter()
    for g in golden:
        eid = Counter(truth_records[m] for m in g.members).most_common(1)[0][0]
        for name, ok in checks.items():
            hits[name] += bool(ok(g.fields[name].value, truth_entities[eid][name]))
    return {name: round(hits[name] / len(golden), 4) for name in checks} if golden else {}
