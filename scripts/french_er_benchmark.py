"""Entity resolution on real French company records: the official SIRENE registry for Soissons
(INSEE via data.gouv.fr, Licence Ouverte 2.0; `Data-Gouv-ML/base-sirene-v3-soissons` on Hugging
Face).

    uv run --with pyarrow python scripts/french_er_benchmark.py [--split dev|test|all] [--out <md>]

Each active establishment of a company appears twice, as two systems would hold it:
- the registry view: legal name ("SNC LIDL", "SAS BOULANGERIE DUPONT"), full street address,
  postcode and city, and the SIREN as tax id;
- a sales view: the name people use (shop sign / enseigne, usual name, or acronym), the address in
  the registry's abbreviated form ("1 SQ DU DOCTEUR SALMON"), the city, and no tax id.
The answer key is the SIREN: every record of the same company is the same customer. Both views are
real text from the registry; only the pairing into two sources is ours. Companies are split by a
hash of their SIREN into dev (tuning) and test (reported only). Files are cached outside the repo.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from canon.models import SourceRecord  # noqa: E402
from canon.resolve.evaluate import bcubed, pairwise  # noqa: E402
from canon.resolve.normalize import normalize_name  # noqa: E402
from canon.resolve.pipeline import resolve  # noqa: E402

REPO = "Data-Gouv-ML/base-sirene-v3-soissons"
REVISION = "7a4ec0d63c7ca1a8bfe4cfc403e6ecc9d5f92433"
LEGAL = "Dénomination de l'unité légale"
ALIASES = (
    "Enseigne de l'établissement 1",
    "Dénomination usuelle de l'établissement",
    "Dénomination usuelle de l'unité légale 1",
    "Sigle de l'unité légale",
)


def fetch() -> Path:
    base = Path(os.environ.get("CANON_CACHE", Path.home() / ".cache" / "canon"))
    path = base / "sirene_soissons" / REVISION / "base-sirene-v3.parquet"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = (
            f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/data/base-sirene-v3.parquet"
        )
        print(f"downloading {url}", file=sys.stderr)
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=120) as r, tmp.open("wb") as fh:
            fh.write(r.read())
        tmp.rename(path)
    return path


def split_of(siren: str) -> str:
    return "dev" if int(hashlib.sha1(siren.encode()).hexdigest(), 16) % 2 == 0 else "test"


def _street(row: dict) -> str:
    parts = (
        row.get("Numéro de voie de l'établissement"),
        row.get("Type de voie de l'établissement"),
        row.get("Libellé de la voie de l'établissement"),
    )
    return " ".join(p for p in parts if p)


def load() -> list[dict]:
    """Records of active establishments of companies with a legal name (not sole traders)."""
    import pyarrow.parquet as pq

    out = []
    for row in pq.read_table(fetch()).to_pylist():
        legal = (row.get(LEGAL) or "").strip()
        if row.get("Etat administratif de l'établissement") != "Actif" or not legal:
            continue
        siren, siret = row["SIREN"], row["siret"]
        city = row.get("Commune de l'établissement") or ""
        postcode = row.get("Code postal de l'établissement") or ""
        out.append(
            {
                "record_id": f"registry:{siret}",
                "siren": siren,
                "name": legal,
                "address": _street(row),
                "city": f"{postcode} {city}".strip(),
                "tax_id": siren,
            }
        )
        aliases = [row[c].strip() for c in ALIASES if row.get(c)]
        alias = next((a for a in aliases if a.lower() != legal.lower()), None)
        if alias:
            out.append(
                {
                    "record_id": f"sales:{siret}",
                    "siren": siren,
                    "name": alias,
                    "address": row.get("Adresse de l'établissement") or "",
                    "city": city,
                    "tax_id": None,
                }
            )
    return out


def to_record(item: dict) -> SourceRecord:
    return SourceRecord(
        record_id=item["record_id"],
        source="crm",
        locator="sirene",
        name=item["name"],
        address=item["address"] or None,
        city=item["city"] or None,
        tax_id=item["tax_id"],
    )


def exact_name(items: list[dict]) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    for it in items:
        groups.setdefault(normalize_name(it["name"]), []).append(it["record_id"])
    return list(groups.values())


def run(items: list[dict]) -> dict:
    truth = {it["record_id"]: it["siren"] for it in items}
    res = resolve([to_record(it) for it in items])
    sales = [it for it in items if it["record_id"].startswith("sales:")]
    linked = sum(
        1
        for it in sales
        for c in res.clusters
        if it["record_id"] in c
        and any(r.startswith("registry:") and truth[r] == it["siren"] for r in c)
    )
    queued = {frozenset((i.left, i.right)) for i in res.review}
    cluster = {rid: k for k, c in enumerate(res.clusters) for rid in c}
    to_review = sum(
        1
        for it in sales
        if not any(
            cluster[it["record_id"]] == cluster[r]
            for r in truth
            if r.startswith("registry:") and truth[r] == it["siren"]
        )
        and any(
            frozenset((it["record_id"], r)) in queued
            for r in truth
            if r.startswith("registry:") and truth[r] == it["siren"]
        )
    )
    return {
        "to_review": to_review,
        "records": len(items),
        "companies": len(set(truth.values())),
        "sales_records": len(sales),
        "linked": linked,
        "canon": pairwise(res.clusters, truth),
        "canon_bcubed": bcubed(res.clusters, truth),
        "exact_name": pairwise(exact_name(items), truth),
        "review": len(res.review),
    }


def render(results: dict) -> str:
    lines = [
        "# Entity resolution on real French company records (SIRENE, Soissons)",
        "",
        f"Generated by `scripts/french_er_benchmark.py` from `{REPO}` at `{REVISION[:7]}` (INSEE "
        "SIRENE via data.gouv.fr, Licence Ouverte 2.0). Each establishment appears as a registry "
        "record (legal name, full address, SIREN) and, when it has one, as a sales record (shop "
        "sign, usual name or acronym, abbreviated address, no tax id). The answer key is the "
        "SIREN.",
        "",
    ]
    for split, r in results.items():
        c, b, e = r["canon"], r["canon_bcubed"], r["exact_name"]
        lines += [
            f"## {split} ({r['records']} records, {r['companies']} companies)",
            "",
            "| method | precision | recall | F1 |",
            "|---|---|---|---|",
            f"| exact normalized name | {e.precision:.3f} | {e.recall:.3f} | {e.f1:.3f} |",
            f"| Canon (pairwise) | {c.precision:.3f} | {c.recall:.3f} | {c.f1:.3f} |",
            f"| Canon (B-cubed) | {b.precision:.3f} | {b.recall:.3f} | {b.f1:.3f} |",
            "",
            f"Sales records (trade name, no tax id) linked to their company's registry record: "
            f"{r['linked']} of {r['sales_records']} "
            f"({100 * r['linked'] / max(r['sales_records'], 1):.0f}%). "
            f"Not linked but sent to a person in the review queue: {r['to_review']}. "
            f"Review queue: {r['review']} pair decisions.",
            "",
        ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    items = load()
    splits = ["dev", "test"] if args.split == "all" else [args.split]
    results = {s: run([i for i in items if split_of(i["siren"]) == s]) for s in splits}
    report = render(results)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
