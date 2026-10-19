"""`canon check`: day-1 preflight on a client export, before anything is resolved.

It answers "can we read this, and what will we lose?" in minutes:
- which sources were found and how big they are;
- for the CRM, which column feeds each field, and a suggested mapping for unmapped fields from
  common CRM/French column names (a suggestion only: it is written to `canon.suggested.json`
  for a person to confirm, never applied);
- for each CRM field, how many rows have a value and how many of those were refused, and why;
- Slack privacy (private channels need `groups.json`), document formats, OCR, ACL sidecars.

Reads nothing under `ground_truth/`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, fields, replace
from pathlib import Path

from rapidfuzz import fuzz

from canon.ingest.crm import CRMFieldMap, load_crm, read_rows
from canon.ingest.deployment import DEPLOYMENT_FILE, Deployment, load_deployment
from canon.ingest.documents import ACL_SIDECAR, DOCUMENT_SUFFIXES, ocr_available

REQUIRED = ("id", "name")  # without these no record can be built
IMPORTANT = ("owner", "contract_value", "renewal_date", "modified")  # the audit's core facts

# Column names seen in common exports (Salesforce, HubSpot, Zoho, Pipedrive, French CRMs).
# A false friend is left out on purpose: "Annual Revenue" is the company's revenue, not the
# contract's value; "Last Activity Date" is not when the record changed.
ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("id", "account id", "record id", "company id", "record id company", "id du compte"),
    "name": (
        "account name",
        "company name",
        "company",
        "organization name",
        "organisation",
        "name",
        "raison sociale",
        "nom du compte",
        "nom de l entreprise",
        "societe",
        "client",
    ),
    "website": ("website", "website url", "company domain name", "domain", "site web", "site"),
    "phone": ("phone", "phone number", "telephone", "tel", "numero de telephone", "standard"),
    "email": ("primary contact email", "email", "e mail", "contact email", "courriel"),
    "street": (
        "billing street",
        "street address",
        "address",
        "adresse",
        "adresse de facturation",
        "billing address",
    ),
    "city": ("billing city", "city", "ville"),
    "tax_id": ("ice", "tax id", "vat number", "vat", "numero ice", "identifiant fiscal"),
    "owner": (
        "owner",
        "account owner",
        "company owner",
        "deal owner",
        "responsable",
        "responsable du compte",
        "proprietaire",
        "proprietaire du compte",
        "commercial",
    ),
    "contract_value": (
        "annual contract value",
        "acv",
        "arr",
        "contract value",
        "montant annuel",
        "montant du contrat",
        "valeur du contrat",
        "valeur annuelle",
    ),
    "renewal_date": (
        "renewal date",
        "contract renewal date",
        "contract end date",
        "date de renouvellement",
        "echeance",
        "date d echeance",
    ),
    "currency": ("currency", "account currency", "devise", "monnaie"),
    "modified": (
        "lastmodifieddate",
        "last modified date",
        "last modified",
        "modified",
        "updated at",
        "date de modification",
        "derniere modification",
    ),
}
FUZZY_MIN = 90  # column/alias similarity needed for a suggestion

# Record fields each CRM field ends up in, to count refusals (ParseIssue.field).
_ISSUE_FIELD = {"modified": "updated_at"}
_RECORD_ATTR = {"street": "address", "modified": "updated_at"}


def fold_column(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def suggest_column(field: str, columns: list[str], taken: set[str]) -> tuple[str, str] | None:
    """(column, how) for an unmapped field: an exact alias match, else a close one."""
    free = [c for c in columns if c not in taken]
    folded = {c: fold_column(c) for c in free}
    for alias in ALIASES.get(field, ()):
        for col in free:
            if folded[col] == alias:
                return col, "alias"
    best = max(
        ((fuzz.ratio(folded[c], a), c) for c in free for a in ALIASES.get(field, ())),
        default=(0, None),
    )
    if best[0] >= FUZZY_MIN:
        return best[1], f"similar ({best[0]:.0f})"
    return None


def _crm_check(root: Path, dep: Deployment, path: Path) -> dict:
    rows = read_rows(path)
    columns = list(dict.fromkeys(k for r in rows for k in r))
    mapping = asdict(dep.crm_fields)
    report: dict = {"file": path.relative_to(root).as_posix(), "rows": len(rows)}
    report["columns"] = columns
    mapped, suggested, missing = {}, {}, []
    taken = {c for c in mapping.values() if c in columns}
    for name, column in mapping.items():
        if column in columns:
            mapped[name] = column
            continue
        hit = suggest_column(name, columns, taken)
        if hit:
            suggested[name] = {"column": hit[0], "how": hit[1]}
            taken.add(hit[0])
        else:
            missing.append(name)
    report.update(mapped=mapped, suggested=suggested, missing=missing)
    report["unused_columns"] = [c for c in columns if c not in taken]
    effective = replace(
        dep.crm_fields, **{k: v["column"] for k, v in suggested.items()}
    )  # what the numbers below assume; nothing is applied to the real run
    report["blocking"] = [f for f in REQUIRED if f not in mapped and f not in suggested]
    if report["blocking"]:
        return report
    ids = Counter(str(r.get(effective.id)) for r in rows)
    report["duplicate_ids"] = sorted(i for i, n in ids.items() if n > 1)[:10]
    report["blank_ids"] = sum(1 for r in rows if r.get(effective.id) in (None, ""))
    if report["blank_ids"]:
        report["blocking"] = ["id"]
        return report
    records = load_crm(path, fields=effective, acl=dep.crm_acl, config=dep.ingest)
    stats = {}
    for f in fields(CRMFieldMap):
        if f.name in ("id",):
            continue
        column = getattr(effective, f.name)
        filled = sum(1 for r in rows if r.get(column) not in (None, ""))
        issue_field = _ISSUE_FIELD.get(f.name, f.name)
        refused = Counter(
            i.reason
            for rec in records
            for i in rec.issues
            if i.field == issue_field and i.severity == "quarantined"
        )
        stats[f.name] = {
            "column": column if column in columns else None,
            "filled": filled,
            "refused": sum(refused.values()),
            "reasons": dict(refused.most_common(3)),
        }
    report["fields"] = stats
    currencies = Counter((r.get(effective.currency) or "").strip().upper() for r in rows)
    report["currencies"] = {k or "(blank)": v for k, v in currencies.most_common()}
    return report


def _slack_check(slack: Path) -> dict:
    out: dict = {"present": (slack / "channels.json").exists()}
    if not out["present"]:
        return out
    channels = json.loads((slack / "channels.json").read_text(encoding="utf-8"))
    groups_file = slack / "groups.json"
    groups = json.loads(groups_file.read_text(encoding="utf-8")) if groups_file.exists() else []
    out["public_channels"] = len(channels)
    out["private_channels"] = len(groups)
    out["users_file"] = (slack / "users.json").exists()
    days = sorted(p.stem for c in channels + groups for p in (slack / c["name"]).glob("*.json"))
    out["day_files"] = len(days)
    out["date_range"] = [days[0], days[-1]] if days else None
    out["warnings"] = []
    if not out["users_file"]:
        out["warnings"].append("users.json missing: messages cannot be attributed")
    if not groups_file.exists():
        out["warnings"].append(
            "no groups.json: private channels are absent or were exported as public; "
            "confirm with the client before serving anything"
        )
    return out


def _other_chat_check(root: Path) -> dict:
    """Teams (Graph export) and WhatsApp (chat .txt exports): what was found."""
    out = {}
    teams = root / "teams" / "channels.json"
    if teams.exists():
        channels = json.loads(teams.read_text(encoding="utf-8"))
        private = sum(c.get("membershipType", "standard") != "standard" for c in channels)
        no_members = sum(
            c.get("membershipType", "standard") != "standard" and not c.get("members")
            for c in channels
        )
        out["teams"] = {"channels": len(channels), "private": private, "no_members": no_members}
    wa = root / "whatsapp"
    if wa.is_dir():
        out["whatsapp"] = {"chats": sum(1 for p in wa.rglob("*.txt") if p.is_file())}
    return out


def _contracts_check(root: Path) -> dict:
    if not root.is_dir():
        return {"present": False}
    files = [p for p in root.rglob("*") if p.is_file() and not p.name.startswith(".")]
    docs = [p for p in files if p.suffix.lower() in DOCUMENT_SUFFIXES and not p.is_symlink()]
    by_suffix = Counter(p.suffix.lower() for p in docs)
    skipped = Counter(
        p.suffix.lower() or "(none)"
        for p in files
        if p.suffix.lower() not in DOCUMENT_SUFFIXES and p.name != ACL_SIDECAR
    )
    needs_ocr = by_suffix[".pdf"] + sum(by_suffix[s] for s in (".png", ".jpg", ".jpeg", ".tif"))
    return {
        "present": True,
        "documents": len(docs),
        "by_format": dict(sorted(by_suffix.items())),
        "skipped_formats": dict(skipped.most_common()),
        "symlinks_skipped": sum(1 for p in files if p.is_symlink()),
        "acl_sidecars": sum(1 for p in files if p.name == ACL_SIDECAR),
        "ocr_available": ocr_available(),
        "may_need_ocr": needs_ocr,
    }


def check_export(root: Path) -> dict:
    root = Path(root)
    dep = load_deployment(root)  # raises on a malformed canon.json: fix that first
    report: dict = {
        "data": str(root),
        "deployment_file": (root / DEPLOYMENT_FILE).exists(),
        "crm": [],
    }
    paths = dep.crm_paths(root)
    if not paths and (root / "crm").is_dir():
        report["crm_unnamed"] = sorted(
            p.relative_to(root).as_posix()
            for p in (root / "crm").iterdir()
            if p.suffix.lower() in (".json", ".csv", ".xlsx")
        )
    report["crm"] = [_crm_check(root, dep, p) for p in paths]
    report["slack"] = _slack_check(root / "slack")
    report["other_chat"] = _other_chat_check(root)
    report["contracts"] = _contracts_check(root / "contracts")
    report["identities"] = (root / "identities.json").exists()
    report["ok"] = bool(paths) and not any(c["blocking"] for c in report["crm"])
    return report


def suggested_deployment(report: dict) -> dict | None:
    """A canon.json to review: the current mapping plus the suggestions. None if nothing to add."""
    crm = report["crm"][0] if report["crm"] else None
    unnamed = report.get("crm_unnamed") or []
    if not (crm and crm["suggested"]) and len(unnamed) != 1:
        return None
    out: dict = {"crm": {}}
    if crm:
        columns = {**crm["mapped"], **{k: v["column"] for k, v in crm["suggested"].items()}}
        defaults = asdict(CRMFieldMap())
        out["crm"]["columns"] = {k: v for k, v in columns.items() if defaults.get(k) != v}
        out["crm"]["file"] = crm["file"]
    else:
        out["crm"]["file"] = unnamed[0]
    return out


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "-"


def render_check(report: dict) -> str:
    lines = [f"# Intake check: {report['data']}", ""]
    lines.append(
        f"- deployment file `{DEPLOYMENT_FILE}`: "
        + ("found" if report["deployment_file"] else "none (defaults)")
    )
    lines.append(f"- identities.json: {'found' if report['identities'] else 'MISSING'}")
    lines.append(f"- verdict: **{'readable' if report['ok'] else 'NOT READY'}**")
    lines += ["", "## CRM", ""]
    if not report["crm"]:
        unnamed = report.get("crm_unnamed")
        if unnamed:
            lines.append(f"No crm/accounts.* file. Candidates: {', '.join(unnamed)}.")
            lines.append(f'Set `"crm": {{"file": ...}}` in {DEPLOYMENT_FILE}.')
        else:
            lines.append("No CRM export found.")
    for crm in report["crm"]:
        lines.append(f"`{crm['file']}`: {crm['rows']} rows, {len(crm['columns'])} columns.")
        if crm["blocking"]:
            lines.append(f"**Blocking:** no usable column for {', '.join(crm['blocking'])}.")
        if crm["suggested"]:
            lines += ["", "Suggested mappings (confirm before use):", ""]
            for f, s in crm["suggested"].items():
                lines.append(f"- {f} <- `{s['column']}` ({s['how']})")
        if crm["missing"]:
            lines.append("")
            lines.append(f"Not found: {', '.join(crm['missing'])}.")
            core = [f for f in crm["missing"] if f in IMPORTANT]
            if core:
                lines.append(f"**Core audit facts with no column: {', '.join(core)}.**")
        if crm["unused_columns"]:
            lines.append("")
            lines.append(f"Unused columns: {', '.join(f'`{c}`' for c in crm['unused_columns'])}")
        if "fields" in crm:
            lines += [
                "",
                "| field | column | filled | refused | top reasons |",
                "|---|---|---|---|---|",
            ]
            for f, s in crm["fields"].items():
                reasons = ", ".join(f"{k} ({v})" for k, v in s["reasons"].items())
                lines.append(
                    f"| {f} | {s['column'] or '-'} | {_pct(s['filled'], crm['rows'])} | "
                    f"{s['refused']} ({_pct(s['refused'], s['filled'])}) | {reasons} |"
                )
            lines.append("")
            lines.append(f"Currencies: {crm['currencies']}")
            if crm.get("duplicate_ids"):
                lines.append(f"Duplicate record ids: {', '.join(crm['duplicate_ids'])}")
    s = report["slack"]
    lines += ["", "## Slack", ""]
    if not s["present"]:
        lines.append("No Slack export (slack/channels.json).")
    else:
        lines.append(
            f"{s['public_channels']} public and {s['private_channels']} private channels, "
            f"{s['day_files']} day files"
            + (f" from {s['date_range'][0]} to {s['date_range'][1]}." if s["date_range"] else ".")
        )
        lines += [f"- warning: {w}" for w in s["warnings"]]
    other = report.get("other_chat", {})
    if "teams" in other:
        t = other["teams"]
        lines += [
            "",
            "## Microsoft Teams",
            "",
            f"{t['channels']} channels, {t['private']} private.",
        ]
        if t["no_members"]:
            lines.append(
                f"- warning: {t['no_members']} private channels list no members: nobody will be "
                "able to read them until the export includes membership"
            )
    if "whatsapp" in other:
        lines += ["", "## WhatsApp", "", f"{other['whatsapp']['chats']} chat exports."]
        lines.append(
            "- readable by their participants only, unless canon.json gives them groups "
            '(`"whatsapp": {"acl": [...]}`)'
        )
    c = report["contracts"]
    lines += ["", "## Contracts", ""]
    if not c["present"]:
        lines.append("No contracts/ folder.")
    else:
        lines.append(f"{c['documents']} documents: {c['by_format']}.")
        if c["skipped_formats"]:
            lines.append(f"- not read (unsupported format): {c['skipped_formats']}")
        if c["symlinks_skipped"]:
            lines.append(f"- symlinks skipped: {c['symlinks_skipped']}")
        lines.append(f"- ACL sidecars ({ACL_SIDECAR}): {c['acl_sidecars']}")
        if c["may_need_ocr"]:
            lines.append(
                f"- {c['may_need_ocr']} PDFs/images may need OCR; tesseract "
                + (
                    "available"
                    if c["ocr_available"]
                    else "**NOT installed**: scans will be refused"
                )
            )
    return "\n".join(lines) + "\n"
