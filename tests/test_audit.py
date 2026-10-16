"""The readiness audit report: findings are right, complete enough, and need no answer key."""

import json
from datetime import date
from pathlib import Path

import pytest

from canon.audit import build_audit, render_audit
from canon.evals.scoring import is_correct
from canon.ingest import load_all
from canon.mcp_server import CallerDirectory
from canon.resolve.pipeline import ResolverConfig, resolve
from canon.score import FactScoringConfig

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"
TRUTH = json.loads((DATA / "ground_truth" / "ground_truth.json").read_text(encoding="utf-8"))
AS_OF = date(2026, 10, 1)


@pytest.fixture(scope="module")
def world():
    records = load_all(DATA)
    res = resolve(records, ResolverConfig(facts=FactScoringConfig(as_of=AS_OF)))
    directory = CallerDirectory.from_file(DATA / "identities.json")
    return records, build_audit(records, res, directory, [], AS_OF)


def test_stale_crm_findings_are_right_and_mostly_complete(world):
    records, audit = world
    found = audit.stale_crm + audit.slack_only_owner_changes
    for s in found:  # precision: the kept value is the truth and the CRM value is not
        truth = TRUTH["entities"][TRUTH["records"][s.stale_record]][s.field]
        assert is_correct(s.field, truth, s.current), s
        assert not is_correct(s.field, truth, s.stale), s
    flagged = {(s.stale_record, s.field) for s in found}
    actually_stale = {
        (r.record_id, f.field)
        for r in records
        if r.source == "crm" and r.status == "active"
        for f in r.facts
        if f.field in ("owner", "contract_value", "renewal_date", "address")
        and not is_correct(
            f.field, TRUTH["entities"][TRUTH["records"][r.record_id]][f.field], str(f.value)
        )
    }
    caught = {(rid, f) for rid, f in actually_stale if any(rid == x and f == y for x, y in flagged)}

    # one finding per customer and field, so count customers rather than records
    def by_customer(pairs):
        return {(TRUTH["records"][rid], f) for rid, f in pairs}

    assert len(by_customer(caught)) / len(by_customer(actually_stale)) >= 0.8


def test_findings_are_ranked_and_actionable(world):
    _, audit = world
    impacts = [f.impact for f in audit.findings]
    assert impacts == sorted(impacts, reverse=True)
    assert all(f.who_fixes and f.count > 0 for f in audit.findings)
    assert {"stale_crm_contract_value", "crm_duplicates", "review_merges"} <= {
        f.key for f in audit.findings
    }


def test_permission_view_per_caller(world):
    _, audit = world
    views = {v.caller: v for v in audit.callers}
    assert views["intern"].records_visible == 0
    assert views["revops.admin"].customers_partial == 0
    assert views["salma.el.idrissi"].customers_partial > 0  # contracts are legal-only


def test_report_renders_every_section(world):
    _, audit = world
    report = render_audit(audit)
    for heading in ("Prioritized fix list", "Duplicates", "Conflicting and stale facts",
                    "quarantine", "Merges to confirm", "Permissions", "Caveats"):  # fmt: skip
        assert heading in report


def test_audit_never_reads_the_answer_key():
    source = (Path(__file__).resolve().parents[1] / "canon" / "audit.py").read_text("utf-8")
    assert "ground_truth" not in source
