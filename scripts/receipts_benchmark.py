"""OCR on real scans: SROIE (ICDAR 2019), scanned shop receipts with transcriptions and labelled
company, date, address and total (CC BY 4.0, `jsdnrs/ICDAR2019-SROIE` on Hugging Face).

    uv run --with pyarrow python scripts/receipts_benchmark.py [--split dev|test] [--limit N]
        [--workers 4] [--out <report.md>]

Every receipt image goes through `canon.ingest.documents.ocr_image` (tesseract, English) and the
text through Canon's own parsers. Reported per receipt set:

- word recall: the share of the transcription's words that OCR also produced (order-independent:
  the transcription lists word boxes in its own order, so a character error rate would mostly
  measure layout, not reading);
- date: the first date `parse_date` reads in the text, with this deployment's conventions (day
  first, two-digit years in the 2000s, as on Malaysian receipts), compared with the label, as
  correct / wrong / refused;
- total: whether `find_amounts` reads the labelled total anywhere in the text;
- company: whether the labelled company name appears (fuzzy) in the text.

Each field is also measured on the human transcription, which separates what OCR loses from what
the parsers lose. Files are downloaded at a pinned revision into `$CANON_CACHE` (default
`~/.cache/canon`); nothing from the dataset is committed. dev = 60 receipts from the train split
(hash-sampled), test = the official test split.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rapidfuzz import fuzz  # noqa: E402

from canon.ingest.documents import OCRConfig, ocr_available, ocr_image  # noqa: E402
from canon.ingest.parsing import find_amounts, parse_date  # noqa: E402

REPO = "jsdnrs/ICDAR2019-SROIE"
REVISION = "bffe40c26759f3376ec2b3ae9031dbba54cd587c"
CONFIG = OCRConfig(languages="eng")
CENTURY: int | None = 20  # this deployment's stated convention for two-digit years
DEV_SIZE = 60


def cache_dir() -> Path:
    base = Path(os.environ.get("CANON_CACHE", Path.home() / ".cache" / "canon"))
    return base / "sroie" / REVISION


def fetch(split: str) -> Path:
    name = "train" if split == "dev" else "test"
    path = cache_dir() / f"{name}.parquet"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/data/{name}-00000-of-00001.parquet"
        print(f"downloading {url}", file=sys.stderr)
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=600) as r, tmp.open("wb") as fh:
            fh.write(r.read())
        tmp.rename(path)
    return path


def load(split: str, limit: int | None) -> list[dict]:
    import pyarrow.parquet as pq

    rows = pq.read_table(fetch(split), columns=["key", "entities", "words", "image"]).to_pylist()
    if split == "dev":
        rows = sorted(rows, key=lambda r: hashlib.sha1(r["key"].encode()).hexdigest())[:DEV_SIZE]
    return rows[:limit] if limit else rows


def first_date(text: str):
    """(date or None, refusal reason or None): the first line that reads as exactly one date."""
    reasons = []
    for line in text.splitlines():
        p = parse_date(line, dayfirst=True, century=CENTURY)
        if p.ok:
            return p.value, None
        if p.reason not in ("empty", "no_date"):
            reasons.append(p.reason)
    return None, (reasons[0] if reasons else "no_date")


def fields(text: str, gold: dict) -> dict:
    want_date = parse_date(gold.get("date", ""), dayfirst=True, century=CENTURY).value
    got_date, reason = first_date(text)
    if got_date is None:
        date_outcome = f"refused:{reason}"
    else:
        date_outcome = "correct" if got_date == want_date else "wrong"
    try:
        total = float(str(gold.get("total", "")).replace(",", ""))
    except ValueError:
        total = None
    amounts = {round(p.value.value, 2) for p in find_amounts(text) if p.ok}
    company = (gold.get("company") or "").lower()
    return {
        "date": date_outcome if want_date else "no_label",
        "total": None if total is None else round(total, 2) in amounts,
        "company": bool(company) and fuzz.partial_ratio(company, text.lower()) >= 90,
    }


def _words(text: str) -> Counter:
    return Counter(re.findall(r"[a-z0-9]+", text.lower()))


def word_recall(truth: str, text: str) -> float:
    want, got = _words(truth), _words(text)
    return sum((want & got).values()) / max(sum(want.values()), 1)


def one(row: dict) -> dict:
    t0 = time.time()
    text, conf, denoised = ocr_image(row["image"]["bytes"], CONFIG)
    truth = "\n".join(row["words"])
    return {
        "recall": word_recall(truth, text),
        "conf": conf,
        "denoised": denoised,
        "seconds": time.time() - t0,
        "ocr": fields(text, row["entities"]),
        "transcript": fields(truth, row["entities"]),
    }


def summarize(results: list[dict]) -> dict:
    n = len(results)
    out = {"n": n, "recall_mean": sum(r["recall"] for r in results) / n}
    out["recall_median"] = sorted(r["recall"] for r in results)[n // 2]
    out["seconds"] = sum(r["seconds"] for r in results) / n
    out["denoised"] = sum(r["denoised"] for r in results)
    for source in ("ocr", "transcript"):
        dates = Counter(r[source]["date"] for r in results)
        out[source] = {
            "date": dates,
            "total": sum(bool(r[source]["total"]) for r in results),
            "total_labelled": sum(r[source]["total"] is not None for r in results),
            "company": sum(r[source]["company"] for r in results),
        }
    return out


def render(split: str, s: dict) -> str:
    n = s["n"]

    def pct(k: int, d: int = n) -> str:
        return f"{k} ({100 * k / d:.0f}%)" if d else "-"

    def date_row(source: str) -> str:
        d = s[source]["date"]
        refused = sum(v for k, v in d.items() if k.startswith("refused"))
        return f"{pct(d['correct'])} | {pct(d['wrong'])} | {pct(refused)}"

    reasons = Counter(
        {k.split(":", 1)[1]: v for k, v in s["ocr"]["date"].items() if k.startswith("refused")}
    )
    return "\n".join(
        [
            "# OCR on real scanned receipts (SROIE)",
            "",
            f"Generated by `scripts/receipts_benchmark.py` from `{REPO}` at `{REVISION[:7]}` "
            "(ICDAR 2019 SROIE, CC BY 4.0). Aggregate numbers only; no receipt is in the repo.",
            "",
            f"## {split} ({n} receipts)",
            "",
            f"- words of the human transcription also read by OCR: mean {s['recall_mean']:.3f}, "
            f"median {s['recall_median']:.3f}",
            f"- {s['denoised']} receipts re-read with the median filter; {s['seconds']:.1f} s per "
            "receipt (one tesseract thread)",
            "",
            "| | date correct | date wrong | date refused | total read | company found |",
            "|---|---|---|---|---|---|",
            f"| from Canon's OCR | {date_row('ocr')} | "
            f"{pct(s['ocr']['total'], s['ocr']['total_labelled'])} | {pct(s['ocr']['company'])} |",
            f"| from the human transcription | {date_row('transcript')} | "
            f"{pct(s['transcript']['total'], s['transcript']['total_labelled'])} | "
            f"{pct(s['transcript']['company'])} |",
            "",
            "Dates refused from OCR text, by reason: "
            + ", ".join(f"{k} {v}" for k, v in reasons.most_common()),
            "",
        ]
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--out", default=None)
    ap.add_argument("--min-digit-confidence", type=float, default=None, help="0 = never mask")
    ap.add_argument("--reread-min-confidence", type=float, default=None, help="0 = no re-read")
    ap.add_argument("--no-century", action="store_true", help="refuse two-digit years")
    args = ap.parse_args()
    global CONFIG, CENTURY
    overrides = {}
    if args.min_digit_confidence is not None:
        overrides["min_digit_confidence"] = args.min_digit_confidence
    if args.reread_min_confidence is not None:
        overrides["reread_min_confidence"] = args.reread_min_confidence
    CONFIG = OCRConfig(languages="eng", **overrides)
    if args.no_century:
        CENTURY = None
    if not ocr_available(CONFIG):
        raise SystemExit("tesseract is not installed")
    rows = load(args.split, args.limit)
    with ProcessPoolExecutor(args.workers) as pool:
        results = list(pool.map(one, rows, chunksize=4))
    report = render(args.split, summarize(results))
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
