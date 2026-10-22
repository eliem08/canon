"""Real-contract benchmark: the contract connector on CUAD v1 (510 public commercial contracts from
SEC filings, labelled by lawyers; CC BY 4.0, https://huggingface.co/datasets/theatticusproject/cuad).

    uv run python scripts/cuad_benchmark.py [--split dev|test|all] [--out <report.md>]

The files are downloaded at a pinned revision into a cache outside the repo (`$CANON_CACHE`, default
`~/.cache/canon`); nothing from CUAD is committed. Only aggregate numbers go in the report.

Contracts are split by a hash of their name into a dev half (rules may be tuned on it) and a test
half (looked at only through this report). Each contract's text goes through `parse_contract`, the
production path, and is compared with the lawyers' normalized answers:

| CUAD answer      | Canon field                         | correct when                         |
|------------------|-------------------------------------|--------------------------------------|
| Parties          | record name (+ alt names)           | matches one of the listed parties    |
| Agreement Date   | signature date (record updated_at)  | same day                             |
| Effective Date   | `contract_start`                    | same day                             |
| Expiration Date  | `renewal_date`                      | same day                             |
| Renewal Term     | `renewal_period_months`             | same number of months                |
| Notice Period... | `renewal_notice`                    | same period (week=7 days, year=12 mo) |

CUAD's renewal term also counts renewals that need an action (options to renew); Canon only reads
automatic renewal, so those count against its recall, not as wrong answers.

"wrong" counts values Canon gave that differ from the answer, or that it gave where the lawyers
found none: that is the number that must stay near zero, since refusing is safe and a wrong date
is not. Partial CUAD dates (`[]/[]/2020`) and "perpetual" are not scored as dates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from canon.ingest.config import IngestConfig  # noqa: E402
from canon.ingest.contracts import parse_contract  # noqa: E402
from canon.resolve.normalize import normalize_name  # noqa: E402

REPO = "theatticusproject/cuad"
REVISION = "a3c393f5d103fd0c516374e4fdff676c8176dcb1"
FILES = ("CUAD_v1/CUAD_v1.json", "CUAD_v1/master_clauses.csv")
FIELDS = ("party", "agreement_date", "effective_date", "expiration_date")
PERIODS = ("renewal_period", "renewal_notice")
GOLD_COLUMN = {
    "party": "Parties-Answer",
    "agreement_date": "Agreement Date-Answer",
    "effective_date": "Effective Date-Answer",
    "expiration_date": "Expiration Date-Answer",
    "renewal_period": "Renewal Term-Answer",
    "renewal_notice": "Notice Period To Terminate Renewal- Answer",
}


def cache_dir() -> Path:
    return Path(os.environ.get("CANON_CACHE", Path.home() / ".cache" / "canon")) / "cuad" / REVISION


def fetch() -> Path:
    """Download the pinned files once; later runs read the cache (works offline)."""
    out = cache_dir()
    for name in FILES:
        path = out / Path(name).name
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{name}"
        print(f"downloading {url}", file=sys.stderr)
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=120) as r, tmp.open("wb") as fh:
            fh.write(r.read())
        tmp.rename(path)
    return out


def _key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\.pdf$", "", title.strip(), flags=re.I).lower())


def split_of(title: str) -> str:
    return "dev" if int(hashlib.sha1(_key(title).encode()).hexdigest(), 16) % 2 == 0 else "test"


def load(directory: Path) -> list[dict]:
    """One item per contract: title, split, text, gold answers."""
    squad = json.loads((directory / "CUAD_v1.json").read_text(encoding="utf-8"))
    texts = {_key(d["title"]): (d["title"], d["paragraphs"][0]["context"]) for d in squad["data"]}
    with (directory / "master_clauses.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    items = []
    for row in rows:
        key = _key(row["Filename"])
        if key not in texts:  # a few file names differ slightly between the two files
            best = max(texts, key=lambda k: fuzz.ratio(k, key))
            if fuzz.ratio(best, key) < 90:
                continue
            key = best
        title, text = texts[key]
        gold = {f: row[c].strip() for f, c in GOLD_COLUMN.items()}
        items.append({"title": title, "split": split_of(title), "text": text, "gold": gold})
    return items


_MDY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")


def gold_date(raw: str) -> tuple[int, int, int] | None:
    """(month, day, year % 100) from CUAD's M/D/YY answers; the century is not stated."""
    m = _MDY.match(raw.strip())
    if not m:
        return None
    month, day = int(m[1]), int(m[2])
    if month > 12 >= day:  # a few answers are written day first (31/01/2025)
        month, day = day, month
    return month, day, int(m[3]) % 100


def same_day(value, gold: tuple[int, int, int]) -> bool:
    d = date.fromisoformat(str(value)[:10])
    return (d.month, d.day, d.year % 100) == gold


_PERIOD = re.compile(
    r"^(?:\d+\s+)?(?:succ?ess?ive\s+)?\(?(\d{1,3})\)?\s*(days?|weeks?|months?|years?)$", re.I
)


def gold_periods(raw: str) -> set[str] | None:
    """CUAD's "successive 1 year" / "90 days" / "180 days / 6 months" as ISO 8601 durations
    (P12M, P90D); None when there is nothing to score (empty, "perpetual", dates, prose)."""
    out = set()
    for part in re.split(r"\s*[;/]\s*", raw.strip().lower()):
        m = _PERIOD.match(part.replace("three (3)", "3"))
        if not m:
            return None
        n, unit = int(m[1]), m[2][0]
        out.add({"d": f"P{n}D", "w": f"P{7 * n}D", "m": f"P{n}M", "y": f"P{12 * n}M"}[unit])
    return out or None


_GROUP = re.compile(r"\b(and|collectively|individually)\b.*\bpart(y|ies)\b", re.I)
_QUOTED = re.compile(r"\(([^)]*)\)|[\"“”]")


def gold_parties(raw: str) -> list[str]:
    names = []
    for part in raw.split(";"):
        part = _QUOTED.sub(" ", part).strip(" .,")
        if part and not _GROUP.search(part):
            names.append(part)
    return names


def party_match(name: str | None, parties: list[str]) -> bool:
    if not name:
        return False
    ours = normalize_name(name)
    return any(fuzz.token_set_ratio(ours, normalize_name(p)) >= 90 for p in parties)


# A US deployment's conventions: month-first numeric dates, US dollars, +1 phone numbers.
US = IngestConfig(dayfirst=False, currency="USD", default_country="1")


def predict(text: str) -> dict:
    rec = parse_contract(text, "c", "cuad", config=US)["record"]
    facts = {f.field: f.value for f in rec.facts}
    return {
        "party": [n for n in [rec.name, *rec.parties] if n],
        "agreement_date": rec.updated_at.isoformat() if rec.updated_at else None,
        "effective_date": facts.get("contract_start"),
        "expiration_date": facts.get("renewal_date"),
        "renewal_period": (
            f"P{facts['renewal_period_months']}M" if "renewal_period_months" in facts else None
        ),
        "renewal_notice": facts.get("renewal_notice"),
        "refused": Counter(i.field for i in rec.issues if i.severity == "quarantined"),
    }


def score(items: list[dict]) -> dict:
    out = {f: Counter() for f in FIELDS + PERIODS}
    for item in items:
        got, gold = predict(item["text"]), item["gold"]
        c = out["party"]
        parties = gold_parties(gold["party"])
        c["gold"] += bool(parties)
        c["answered"] += bool(got["party"])
        hit = any(party_match(n, parties) for n in got["party"])
        c["correct"] += hit
        c["wrong"] += bool(got["party"]) and not hit
        for f in FIELDS[1:]:
            c = out[f]
            g = gold_date(gold[f])
            c["gold"] += g is not None
            c["gold_partial_or_text"] += bool(gold[f]) and g is None
            c["answered"] += got[f] is not None
            c["refused"] += got["refused"][
                {"agreement_date": "signature_date", "effective_date": "contract_start"}.get(
                    f, "renewal_date"
                )
            ]
            if got[f] is None:
                continue
            if g is None:  # answered where the lawyers have no full date
                c["wrong" if not gold[f] else "unscored"] += 1
            elif same_day(got[f], g):
                c["correct"] += 1
            else:
                c["wrong"] += 1
        for f in PERIODS:
            c = out[f]
            g = gold_periods(gold[f])
            c["gold"] += g is not None
            c["answered"] += got[f] is not None
            if got[f] is None:
                continue
            if g is None:
                c["wrong" if not gold[f] else "unscored"] += 1
            else:
                c["correct" if got[f] in g else "wrong"] += 1
    return {f: dict(c) for f, c in out.items()}


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "-"


def render(results: dict[str, dict], counts: dict[str, int]) -> str:
    lines = [
        "# Contract connector on real contracts (CUAD v1)",
        "",
        "Generated by `scripts/cuad_benchmark.py` from CUAD v1 "
        f"(`{REPO}` at `{REVISION[:7]}`, CC BY 4.0): public commercial contracts filed with the "
        "SEC, "
        "answers normalized by lawyers. Aggregate numbers only; no contract text is in the repo.",
        "",
        "recall = correct / contracts with an answer; precision = correct / values Canon gave; "
        "wrong = values that differ from the lawyers' answer or that they did not find.",
        "",
    ]
    for split, res in results.items():
        lines += [
            f"## {split} ({counts[split]} contracts)",
            "",
            "| field | with answer | Canon answered | correct | wrong | recall | precision |",
            "|---|---|---|---|---|---|---|",
        ]
        for f in FIELDS + PERIODS:
            c = res[f]
            lines.append(
                f"| {f} | {c.get('gold', 0)} | {c.get('answered', 0)} | {c.get('correct', 0)} | "
                f"{c.get('wrong', 0)} | {_pct(c.get('correct', 0), c.get('gold', 0))} | "
                f"{_pct(c.get('correct', 0), c.get('answered', 0))} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    items = load(fetch())
    splits = ["dev", "test"] if args.split == "all" else [args.split]
    results = {s: score([i for i in items if i["split"] == s]) for s in splits}
    counts = {s: sum(i["split"] == s for i in items) for s in splits}
    report = render(results, counts)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
