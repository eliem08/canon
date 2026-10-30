"""The review page in a real browser: answer a merge, add a correction, download overrides.json,
and the next run applies both. Skipped where Playwright/Chromium is not installed."""

import json
import os
from datetime import date
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
_path = os.environ.get("CANON_CHROMIUM", "/opt/pw-browsers/chromium")
CHROMIUM = _path if Path(_path).exists() else None  # None: Playwright's own download

from canon.cli import build_store, main  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"
AS_OF = date(2026, 10, 1)


def test_review_page_round_trip(tmp_path):
    out = tmp_path / "out"
    main(["audit", "--data", str(DATA), "--out", str(out), "--as-of", AS_OF.isoformat()])
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(executable_path=CHROMIUM)
        except Exception as exc:  # no browser installed for Playwright
            pytest.skip(f"cannot start Chromium: {exc}")
        page = browser.new_page(accept_downloads=True)
        page.goto((out / "review.html").as_uri())
        page.check("input[name=p0][value=different]")
        record = page.eval_on_selector("select[name=record]", "s => s.options[1].value")
        page.select_option("select[name=record]", record)
        page.select_option("select[name=field]", "renewal_date")
        page.fill("input[name=value]", "01/03/2031")  # not ISO: must be refused
        page.fill("input[name=by]", "Test Owner")
        page.click("#fix-form button[type=submit]")
        assert "YYYY-MM-DD" in page.inner_text("#fix-msg")
        page.fill("input[name=value]", "2031-03-01")
        page.click("#fix-form button[type=submit]")
        assert "Test Owner" in page.inner_text("#fixes")
        with page.expect_download() as dl:
            page.click("#download")
        saved = tmp_path / "overrides.json"
        dl.value.save_as(saved)
        browser.close()
    overrides = json.loads(saved.read_text(encoding="utf-8"))
    assert len(overrides["cannot_link"]) == 1
    assert overrides["facts"][0]["record_id"] == record
    assert overrides["facts"][0]["value"] == "2031-03-01"
    _, res, _ = build_store(DATA, tmp_path / "again", AS_OF, saved)
    golden = next(g for g in res.golden if record in g.members)
    assert golden.facts["renewal_date"].value == "2031-03-01"
