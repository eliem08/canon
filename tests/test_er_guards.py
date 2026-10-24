"""Adversarial pair suite, stable ids, human overrides and the review queue."""

import json
from pathlib import Path

import pytest

from canon.ingest import load_all
from canon.models import SourceRecord
from canon.resolve.lexicon import business_types, name_concepts
from canon.resolve.pipeline import Overrides, resolve, stable_ids

FIXTURE = Path(__file__).parent / "fixtures" / "er_pairs.json"
DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"
PAIRS = json.loads(FIXTURE.read_text(encoding="utf-8"))["pairs"]


def _records(pair: dict) -> list[SourceRecord]:
    return [
        SourceRecord(record_id=f"{pair['id']}:{k}", source="crm", locator="x", **pair[k])
        for k in ("a", "b")
    ]


def test_adversarial_pairs_precision_and_recall():
    tp = fp = fn = 0
    for pair in PAIRS:
        merged = len(resolve(_records(pair)).clusters) == 1
        tp += pair["same"] and merged
        fn += pair["same"] and not merged
        fp += (not pair["same"]) and merged
    assert tp / (tp + fp) >= 0.95, (tp, fp)
    assert tp / (tp + fn) >= 0.8, (tp, fn)


@pytest.mark.parametrize("pair", [p for p in PAIRS if not p["same"]], ids=lambda p: p["id"])
def test_no_false_merge(pair):
    assert len(resolve(_records(pair)).clusters) == 2


def test_lexicon_maps_languages_to_one_concept():
    assert name_concepts("Pharmacie Al Amal")[0] == name_concepts("صيدلية الأمل")[0]
    assert business_types(name_concepts("Boulangerie Atlas")) != business_types(
        name_concepts("Pharmacie Atlas")
    )


@pytest.fixture(scope="module")
def records():
    return load_all(DATA)


def test_stable_ids_survive_new_records(records):
    base = sorted(records, key=lambda r: r.record_id)
    held_out = base[::10]  # ~10% arrive later
    first = resolve([r for r in base if r not in held_out])
    previous = {g.entity_id: g.members for g in first.golden}
    second = resolve(base, previous=previous)
    kept = {g.entity_id: set(g.members) for g in second.golden}
    for eid, members in previous.items():
        assert eid in kept and set(members) <= kept[eid], eid


def test_ids_do_not_depend_on_order():
    clusters = [["b", "c"], ["a"]]
    assert stable_ids(clusters) == list(reversed(stable_ids(list(reversed(clusters)))))
    assert stable_ids([["a", "z"]], {"E-old": ["a"]}) == ["E-old"]


def test_overrides_win(records):
    res = resolve(records)
    big = next(g for g in res.golden if len(g.members) >= 2)
    a, b = big.members[:2]
    split = resolve(records, overrides=Overrides(cannot_link=[(a, b)]))
    cluster_of = {m: i for i, c in enumerate(split.clusters) for m in c}
    assert cluster_of[a] != cluster_of[b]

    other = next(g for g in res.golden if a not in g.members)
    c = other.members[0]
    joined = resolve(records, overrides=Overrides(must_link=[(a, c)]))
    cluster_of = {m: i for i, c_ in enumerate(joined.clusters) for m in c_}
    assert cluster_of[a] == cluster_of[c]
    assert all({a, c} != {i.left, i.right} for i in joined.review)


def test_review_queue_lists_uncertain_pairs(records):
    review = resolve(records).review
    assert review, "synthetic data has borderline pairs"
    assert all(i.decision in {"merged", "kept apart"} and i.why for i in review)
    margins = [abs(i.probability - 0.5) for i in review]
    assert margins == sorted(margins)
