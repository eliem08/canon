"""`canon purge`: deletes only Canon output folders and accounts for every file."""

import json
from pathlib import Path

import pytest

from canon.cli import main
from canon.purge import PurgeError, purge


def _out(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    (out / "sub").mkdir(parents=True)
    (out / "audit.json").write_text("{}", encoding="utf-8")
    (out / "sub" / "x.csv").write_text("a,b\n", encoding="utf-8")
    return out


def test_dry_run_lists_without_deleting(tmp_path):
    out = _out(tmp_path)
    receipt = purge(out, dry_run=True)
    assert {f["path"] for f in receipt["files"]} == {"audit.json", "sub/x.csv"}
    assert (out / "sub" / "x.csv").exists() and receipt["deleted"] is False


def test_purge_deletes_and_writes_a_receipt_outside_the_folder(tmp_path, capsys):
    out = _out(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    main(["purge", "--out", str(out), "--yes", "--receipt", str(receipt_path)])
    assert out.exists() and not any(out.iterdir())
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["deleted"] and len(receipt["files"]) == 2 and receipt["total_bytes"] == 6


def test_refuses_folders_that_are_not_canon_outputs(tmp_path):
    (tmp_path / "photos").mkdir()
    (tmp_path / "photos" / "a.jpg").write_bytes(b"x")
    with pytest.raises(PurgeError):
        purge(tmp_path / "photos")
    with pytest.raises(PurgeError):
        purge(Path.home())
    assert (tmp_path / "photos" / "a.jpg").exists()
