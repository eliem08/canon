"""`canon pilot`: the whole client engagement in one command.

Runs the intake check and the audit on an export, then writes two files next to the deliverables:
- `run.json`: what ran, on which inputs (sha256 of every file), with which settings, so an audit
  can be reproduced and two audits compared;
- `index.html`: an offline dashboard with the headline numbers and a link to every deliverable.
Nothing here reads the answer key or talks to the network.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import time
from datetime import UTC, date, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from canon.audit import Audit
from canon.deliver import _page

DELIVERABLES = [
    ("audit_report.html", "Audit report", "The full report. Open in a browser, print to PDF."),
    (
        "crm_fixes.csv",
        "CRM fixes",
        "One row per stale CRM value, in the CRM's own ids and columns.",
    ),
    ("review.html", "Merges to confirm", "Send to account owners; they answer same / different."),
    (
        "renewals.csv",
        "Renewal calendar",
        "Contracts renewing in 180 days, last day to give notice.",
    ),
    ("quarantine.csv", "Values refused", "Every value Canon would not guess, with what to do."),
    ("intake_check.md", "Intake check", "What was found in the export before resolution."),
    ("audit.json", "Audit data", "Keep it: next week's run compares against it (--compare)."),
    ("run.json", "Run record", "Versions, settings and input hashes of this run."),
]


def _version() -> str:
    try:
        return version("canon")
    except PackageNotFoundError:  # running from a source tree that is not installed
        return "unknown"


def file_hashes(root: Path) -> dict[str, str]:
    """sha256 of every input file, by path relative to the export root (sorted)."""
    out = {}
    for path in sorted(p for p in Path(root).rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("ground_truth/"):  # the synthetic answer key is not an input
            continue
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def write_manifest(out: Path, data: Path, as_of: date | None, options: dict, seconds: float):
    manifest = {
        "canon_version": _version(),
        "git_sha": os.environ.get("CANON_GIT_SHA"),
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seconds": round(seconds, 1),
        "as_of": (as_of or date.today()).isoformat(),
        "options": options,
        "inputs": file_hashes(data),
    }
    path = Path(out) / "run.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _card(n, label: str) -> str:
    return (
        f'<div class="card"><div class="n">{n}</div><div class="l">{html.escape(label)}</div></div>'
    )


def render_index(audit: Audit, out: Path, manifest: dict, intake_ok: bool) -> str:
    stale = len(audit.stale_crm) + len(audit.slack_only_owner_changes)
    held = sum(audit.quarantine_by_reason.values())
    dupes = audit.same_source_duplicates.get("crm", 0)
    records = sum(audit.records_by_source.values())
    cards = "".join(
        [
            _card(records, "source records read"),
            _card(audit.entities, "customers after resolution"),
            _card(stale, "stale CRM values to fix"),
            _card(dupes, "customers with duplicate CRM accounts"),
            _card(audit.review_items, "merges waiting for a person"),
            _card(held, "values refused (not guessed)"),
            _card(len(audit.renewals), "renewals in the next 180 days"),
        ]
    )
    files = []
    for name, title, what in DELIVERABLES:
        if (Path(out) / name).exists():
            link = f'<a href="{html.escape(name)}">{html.escape(title)}</a>'
            files.append(f"<tr><td>{link}</td><td>{html.escape(what)}</td></tr>")
        else:
            files.append(
                f'<tr><td class="missing">{html.escape(title)} (not produced)</td>'
                f"<td>{html.escape(what)}</td></tr>"
            )
    findings = "".join(
        f"<tr><td>{html.escape(f.title)}</td><td class='num'>{f.count}</td>"
        f"<td>{html.escape(f.who_fixes)}</td></tr>"
        for f in sorted(audit.findings, key=lambda f: -f.impact)[:8]
    )
    renewals = "".join(
        f"<tr><td>{html.escape(r.customer or r.entity_id)}</td><td>{r.renews_on}</td>"
        f"<td>{r.cancel_by or '—'}</td><td>{'yes' if r.automatic else 'no'}"
        f"{' · sources disagree' if r.contested else ''}</td></tr>"
        for r in audit.renewals[:10]
    )
    warn = (
        ""
        if intake_ok
        else '<p class="notice">The intake check found problems in the export: see '
        '<a href="intake_check.md">intake_check.md</a> before relying on the numbers.</p>'
    )
    body = (
        "<h1>Customer data audit</h1>"
        f"<p class='meta'>As of {html.escape(manifest['as_of'])} · Canon "
        f"{html.escape(manifest['canon_version'])} · {len(manifest['inputs'])} input files · "
        f"{manifest['seconds']} s. Processed on this machine; nothing was sent anywhere.</p>"
        f"{warn}<div class='cards'>{cards}</div>"
        "<h2>Files for you</h2><div class='table'><table class='files'>"
        "<tr><th>File</th><th>What it is</th></tr>" + "".join(files) + "</table></div>"
        "<h2>Biggest findings</h2><div class='table'><table>"
        "<tr><th>Finding</th><th>Count</th><th>Who fixes it</th></tr>"
        + (findings or "<tr><td colspan='3'>No findings.</td></tr>")
        + "</table></div><h2>Next renewals</h2><div class='table'><table>"
        "<tr><th>Customer</th><th>Renews on</th><th>Last day to give notice</th>"
        "<th>Automatic</th></tr>"
        + (renewals or "<tr><td colspan='4'>No contract renews in the next 180 days.</td></tr>")
        + "</table></div><h2>Next steps</h2><ol>"
        "<li>Load <code>crm_fixes.csv</code> with your CRM's bulk update after review.</li>"
        "<li>Send <code>review.html</code> to account owners; put the downloaded "
        "<code>overrides.json</code> next to the export.</li>"
        "<li>Next week, rerun with <code>--compare</code> on this <code>audit.json</code> to see "
        "what changed.</li></ol>"
    )
    return _page("Customer data audit", body)


def run_pilot(
    data: Path,
    out: Path,
    as_of: date | None = None,
    overrides: Path | None = None,
    identities: Path | None = None,
    compare: Path | None = None,
) -> tuple[Audit, dict, bool]:
    from canon.cli import run_audit
    from canon.intake import check_export, render_check

    data, out = Path(data), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    intake = check_export(data)
    (out / "intake_check.md").write_text(render_check(intake), encoding="utf-8")
    audit, _ = run_audit(data, out, as_of, overrides, identities, compare)
    options = {
        "overrides": str(overrides) if overrides else None,
        "compare": str(compare) if compare else None,
    }
    manifest = write_manifest(out, data, as_of, options, time.monotonic() - started)
    (out / "index.html").write_text(
        render_index(audit, out, manifest, bool(intake["ok"])), encoding="utf-8"
    )
    return audit, manifest, bool(intake["ok"])
