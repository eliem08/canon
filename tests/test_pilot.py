"""`canon pilot`: one command produces every deliverable, a dashboard and a run record."""

import json
import re
import shutil
from datetime import date
from pathlib import Path

from canon.cli import main
from canon.pilot import DELIVERABLES, file_hashes, render_index

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"


def test_pilot_writes_every_deliverable_and_a_dashboard_linking_them(tmp_path):
    out = tmp_path / "out"
    main(["pilot", "--data", str(DATA), "--out", str(out), "--as-of", "2026-10-01"])
    for name, _, _ in DELIVERABLES:
        assert (out / name).exists(), name
    page = (out / "index.html").read_text(encoding="utf-8")
    links = set(re.findall(r'href="([^"]+)"', page))
    assert links == {name for name, _, _ in DELIVERABLES}
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["as_of"] == "2026-10-01"
    assert run["inputs"] and not any(p.startswith("ground_truth/") for p in run["inputs"])


def test_input_hashes_change_when_an_input_changes(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(DATA / "crm", data / "crm")
    before = file_hashes(data)
    (data / "crm" / "accounts.json").write_text("[]", encoding="utf-8")
    assert file_hashes(data)["crm/accounts.json"] != before["crm/accounts.json"]


def test_dashboard_escapes_source_text(tmp_path):
    from canon.audit import Audit, Finding, Renewal

    evil = '<img src=x onerror="alert(1)">'
    audit = Audit.model_construct(
        records_by_source={"crm": 1}, entities=1, stale_crm=[], slack_only_owner_changes=[],
        quarantine_by_reason={}, same_source_duplicates={}, review_items=0,
        findings=[Finding(key="k", title=evil, count=1, weight=1, who_fixes=evil)],
        renewals=[Renewal(entity_id="e", customer=evil, renews_on=date(2027, 1, 1))],
    )  # fmt: skip
    manifest = {"as_of": "2026-10-01", "canon_version": evil, "inputs": {}, "seconds": 0}
    page = render_index(audit, tmp_path, manifest, intake_ok=False)
    assert "<img" not in page and "intake_check.md" in page
