"""`canon purge`: delete an engagement's outputs and print a deletion receipt.

The receipt lists every file removed with its size and sha256, so the client can check it against
what they were given. Files are unlinked, not overwritten: on SSDs and copy-on-write filesystems an
overwrite does not guarantee erasure, so disk encryption remains the client's control for that.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

# a folder is a Canon output folder only if it holds one of these
MARKERS = ("canon.sqlite", "audit.json", "run.json", "golden_records.json")


class PurgeError(RuntimeError):
    pass


def purge(out: Path, dry_run: bool = False) -> dict:
    out = Path(out).resolve()
    if not out.is_dir():
        raise PurgeError(f"not a folder: {out}")
    if out == Path(out.anchor) or out == Path.home().resolve():
        raise PurgeError(f"refusing to purge {out}")
    if not any((out / m).exists() for m in MARKERS):
        raise PurgeError(
            f"{out} does not look like a Canon output folder (no {', '.join(MARKERS)})"
        )
    files = []
    for path in sorted(p for p in out.rglob("*") if p.is_file()):
        files.append(
            {
                "path": path.relative_to(out).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    if not dry_run:
        for child in out.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    return {
        "folder": str(out),
        "deleted": not dry_run,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": files,
        "total_bytes": sum(f["bytes"] for f in files),
        "note": "Files were unlinked, not overwritten; erasure on disk relies on disk encryption.",
    }


def render_receipt(receipt: dict) -> str:
    return json.dumps(receipt, indent=2, ensure_ascii=False)
