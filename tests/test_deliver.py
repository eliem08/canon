"""Client deliverables: HTML audit report and the offline review page."""

import json
import re
from datetime import date
from pathlib import Path

from canon.audit import build_audit, render_audit
from canon.cli import build_store, write_deliverables
from canon.deliver import markdown_to_html, render_review_html
from canon.models import SourceRecord
from canon.resolve.pipeline import Overrides, ReviewItem

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"
EVIL = '</script><script>alert("x")</script><img src=x onerror=alert(1)>'


def _item(left="a", right="b") -> ReviewItem:
    return ReviewItem(
        left=left,
        right=right,
        left_name=EVIL,
        right_name="B",
        probability=0.56,
        name_similarity=0.5,
        evidence={},
        decision="merged",
        why=EVIL,
    )


def _embedded(page: str) -> dict:
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S)
    return json.loads(m.group(1))


def test_markdown_subset():
    out = markdown_to_html(
        "# Title\n\n*note* with `code` and **bold**\n\n| a | n |\n|---|---|\n| x | 12 |\n\n- item"
    )
    assert "<h1>Title</h1>" in out
    assert "<em>note</em>" in out and "<code>code</code>" in out and "<strong>bold</strong>" in out
    assert '<td class="num">12</td>' in out and "<li>item</li>" in out


def test_source_text_is_escaped_in_the_report():
    out = markdown_to_html(f"| name |\n|---|\n| {EVIL} |\n\n{EVIL}")
    assert "<script" not in out and "<img" not in out and "&lt;img" in out


def test_source_text_is_escaped_in_the_review_page():
    rec = SourceRecord(record_id="a", source="crm", locator="x", name=EVIL, city=EVIL)
    page = render_review_html([_item()], {"a": rec}, run="r1")
    # only the page's own two script blocks: the JSON data block and the page script
    assert page.count("<script") == 2 and "<img" not in page
    assert _embedded(page)["items"] == [{"left": "a", "right": "b"}]


def test_existing_overrides_are_carried_into_the_download():
    existing = Overrides(must_link=[("p", "q")], cannot_link=[("r", "s")])
    data = _embedded(render_review_html([_item()], {}, existing, run="r1"))
    assert data["existing"] == {"must_link": [["p", "q"]], "cannot_link": [["r", "s"]]}


def test_audit_writes_the_client_files_and_answers_close_the_loop(tmp_path):
    out = tmp_path / "out"
    as_of = date(2026, 10, 1)
    records, res, unreadable = build_store(DATA, out, as_of)
    report = render_audit(build_audit(records, res, None, unreadable, as_of))
    write_deliverables(out, report, res.review, records, None)
    page = (out / "review.html").read_text(encoding="utf-8")
    html_report = (out / "audit_report.html").read_text(encoding="utf-8")
    assert "<h2>1. Prioritized fix list</h2>" in html_report
    items = _embedded(page)["items"]
    assert len(items) == len(res.review) > 0
    assert "134000.0" not in page  # amounts are shown the way people write them

    # what the page's download produces for "same" on the first card, "different" on the second
    first, second = items[0], items[1]
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        json.dumps(
            {
                "must_link": [[first["left"], first["right"]]],
                "cannot_link": [[second["left"], second["right"]]],
            }
        )
    )
    _, res2, _ = build_store(DATA, tmp_path / "out2", as_of, overrides)
    pairs = {(i.left, i.right) for i in res2.review}
    assert (first["left"], first["right"]) not in pairs
    assert (second["left"], second["right"]) not in pairs
    cluster = {rid: i for i, members in enumerate(res2.clusters) for rid in members}
    assert cluster[first["left"]] == cluster[first["right"]]
    assert cluster[second["left"]] != cluster[second["right"]]


def test_fix_files_are_ready_for_a_crm_bulk_update(tmp_path):
    import csv
    from dataclasses import asdict

    from canon.deliver import write_fix_files
    from canon.ingest.crm import CRMFieldMap

    as_of = date(2026, 10, 1)
    records, res, unreadable = build_store(DATA, tmp_path / "out", as_of)
    audit = build_audit(records, res, None, unreadable, as_of)
    fixes, quarantine = write_fix_files(tmp_path, audit, records, unreadable, asdict(CRMFieldMap()))
    raw = fixes.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM so Excel opens UTF-8 (Arabic names) correctly
    rows = list(csv.DictReader(fixes.open(encoding="utf-8-sig")))
    assert len(rows) == len(audit.stale_crm) + len(audit.slack_only_owner_changes)
    by_id = {r.record_id: r for r in records}
    for row in rows:
        rec = by_id["crm:" + row["crm_record_id"]]  # the CRM's own id, as it appears in the CRM
        assert rec.source == "crm"
        assert row["crm_column"] in asdict(CRMFieldMap()).values()
        assert row["suggested_value"] and row["suggested_value"] != row["crm_value_now"]
        assert not row["suggested_value"].endswith(".0")
    q = list(csv.DictReader(quarantine.open(encoding="utf-8-sig")))
    issues = sum(len(r.issues) for r in records) + len(unreadable)
    assert len(q) == issues and all(r["what_to_do"] for r in q)


def test_every_refusal_code_in_the_parsers_has_a_specific_hint():
    """A new reason code needs a sentence a client can act on (canon/deliver.py REASON_HINTS)."""
    import re as _re

    from canon.deliver import REASON_HINTS

    root = Path(__file__).resolve().parents[1] / "canon" / "ingest"
    source = "\n".join(p.read_text(encoding="utf-8") for p in root.glob("*.py"))
    codes = set(_re.findall(r'reason="([a-z_]+)"', source))
    codes |= set(_re.findall(r'refuse\([^)]*?"([a-z_]+)"\)', source))
    absent = {"empty", "no_amount", "no_date", "no_phone", "unparseable", "llm_value_not_in_source"}
    missing = sorted(c for c in codes - absent if c not in REASON_HINTS)
    assert missing == [], missing
