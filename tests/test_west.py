"""The Western demo dataset (US English, USD): reproducible, resolved correctly, permission-safe."""

import filecmp
import json
from datetime import date
from pathlib import Path

from canon.cli import build_store, main
from canon.ingest import load_all
from canon.mcp_server import CallerDirectory, CanonService, ServiceConfig
from canon.resolve.evaluate import pairwise
from canon.resolve.pipeline import ResolverConfig, resolve
from canon.score import FactScoringConfig
from canon.synth.west import generate_west

WEST = Path(__file__).resolve().parents[1] / "data" / "synthetic_west"
AS_OF = date(2026, 10, 1)
TRUTH = json.loads((WEST / "ground_truth" / "ground_truth.json").read_text(encoding="utf-8"))


def _same_tree(a: Path, b: Path) -> bool:
    cmp = filecmp.dircmp(a, b, ignore=["README.md"])
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return False
    return all(_same_tree(a / d, b / d) for d in cmp.common_dirs)


def test_committed_dataset_matches_the_generator(tmp_path):
    generate_west(tmp_path)
    assert _same_tree(tmp_path, WEST)


def test_resolution_and_current_facts_are_right():
    records = load_all(WEST)
    res = resolve(records, ResolverConfig(facts=FactScoringConfig(as_of=AS_OF)))
    truth = {rid: eid for rid, eid in TRUTH["records"].items()}
    assert pairwise(res.clusters, truth).f1 == 1.0
    for g in res.golden:
        (eid,) = {truth[m] for m in g.members}
        want = TRUTH["entities"][eid]
        for field in ("owner", "contract_value", "renewal_date"):
            assert g.facts[field].value == want[field], (eid, field)
    assert not [i for r in records for i in r.issues if i.severity == "quarantined"]


def test_pilot_runs_on_the_western_data(tmp_path):
    out = tmp_path / "out"
    main(["pilot", "--data", str(WEST), "--out", str(out), "--as-of", AS_OF.isoformat()])
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "stale CRM values to fix" in page and "MAD" not in page


def test_no_caller_sees_a_record_they_may_not_read(tmp_path):
    build_store(WEST, tmp_path, AS_OF)
    directory = CallerDirectory.from_file(WEST / "identities.json")
    service = CanonService.from_store(
        tmp_path / "canon.sqlite", directory, ServiceConfig(facts=FactScoringConfig(as_of=AS_OF))
    )
    names = [e["name"] for e in TRUTH["entities"].values()]
    for caller in directory.callers:
        groups = directory.resolve(caller).groups
        for name in names:
            for answer in (
                service.get_customer(name, caller),
                service.find_contract_terms(name, caller),
            ):
                for rid in answer.records:
                    assert groups & set(service.records[rid].acl), (caller, name, rid)


def test_auto_renewal_and_notice_reach_the_audit_and_the_agent(tmp_path):
    """Through the real pipeline (an earlier unit test built golden records by hand and missed
    that scoring dropped these fields)."""
    from canon.audit import build_audit

    records = load_all(WEST)
    res = resolve(records, ResolverConfig(facts=FactScoringConfig(as_of=AS_OF)))
    auto = [g for g in res.golden if "renewal_notice" in g.facts]
    assert auto and all("renewal_period_months" in g.facts for g in auto)
    audit = build_audit(records, res, None, [], AS_OF)
    assert any(r.automatic and r.cancel_by for r in audit.renewals)

    build_store(WEST, tmp_path, AS_OF)
    service = CanonService.from_store(
        tmp_path / "canon.sqlite",
        CallerDirectory.from_file(WEST / "identities.json"),
        ServiceConfig(facts=FactScoringConfig(as_of=AS_OF)),
    )
    terms = service.find_contract_terms(auto[0].entity_id, "revops.admin").terms
    assert {"renewal_period_months", "renewal_notice", "cancel_by"} <= set(terms)


def test_serve_reads_the_identities_of_the_export_it_serves():
    import argparse

    from canon.cli import identities_path

    args = argparse.Namespace(data=str(WEST), identities=None)
    assert identities_path(args) == WEST / "identities.json"
    args.identities = "/elsewhere/identities.json"
    assert identities_path(args) == Path("/elsewhere/identities.json")
