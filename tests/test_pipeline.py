import json
from datetime import date
from pathlib import Path

import pytest

from canon.ingest import load_all
from canon.resolve.evaluate import blocking_quality, field_accuracy, pairwise
from canon.resolve.pipeline import ResolverConfig, resolve
from canon.resolve.report import render_report, seed_sweep
from canon.score import FactScoringConfig
from canon.store import read_golden, write_store

CONFIG = ResolverConfig(facts=FactScoringConfig(as_of=date(2026, 10, 1)))
DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"


@pytest.fixture(scope="module")
def run():
    truth = json.loads((DATA / "ground_truth" / "ground_truth.json").read_text(encoding="utf-8"))
    records = load_all(DATA)
    return records, resolve(records, CONFIG), truth


def test_f1_target_on_committed_dataset(run):
    _, res, truth = run
    m = pairwise(res.clusters, truth["records"])
    assert m.f1 >= 0.90, m
    assert m.precision >= 0.95, m


def test_blocking_keeps_true_pairs(run):
    _, res, truth = run
    q = blocking_quality(res.candidates, truth["records"])
    assert q["pair_completeness"] >= 0.98 and q["reduction_ratio"] >= 0.8


def test_golden_records_have_full_lineage(run):
    records, res, truth = run
    members = [m for g in res.golden for m in g.members]
    assert sorted(members) == sorted(r.record_id for r in records)
    acc = field_accuracy(res.golden, truth["records"], truth["entities"])
    assert acc["contract_value"] >= 0.9 and acc["owner"] >= 0.9


def test_f1_holds_on_held_out_seeds():
    sweep = seed_sweep(range(101, 106), CONFIG)
    assert min(f for _, f, _ in sweep) >= 0.90, sweep
    assert min(a for _, _, a in sweep) >= 0.85, sweep


def test_store_roundtrip(run, tmp_path):
    records, res, _ = run
    write_store(tmp_path / "canon.sqlite", records, res.golden)
    assert read_golden(tmp_path / "canon.sqlite") == res.golden


def test_report_renders(run):
    records, res, truth = run
    report = render_report(records, res, truth)
    assert (
        "# Entity resolution and fact scoring report" in report
        and "Fact scoring" in report
        and "Baseline" in report
    )
