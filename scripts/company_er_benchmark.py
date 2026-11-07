"""Real companies, three independent systems: does Canon recognise the same customer?

    uv run python scripts/company_er_benchmark.py [--split dev|test|all] [--limit N] [--out <md>]

Every US-listed company that Wikidata links to both an SEC CIK and an LEI (about 2,200) appears as
the systems of a real business would hold it:

- **CRM-like** (Wikidata, CC0): the everyday name ("AMD", "Alcoa"), official website, HQ city;
- **billing/finance-like** (SEC EDGAR submissions, public domain): the filing name ("ADVANCED MICRO
  DEVICES INC"), business street address, city and phone;
- **legal-entity registry** (GLEIF, CC0): the legal name and legal headquarters address;
- **a stale CRM account** for companies that changed name: the most recent *former* name in SEC
  EDGAR ("FACEBOOK INC"), with the website the CRM would still have.

Every value is real; only the grouping into "systems" is ours. The answer key is the identifiers
(Wikidata QID, CIK, LEI), which Canon never sees: it must match on names, addresses, phones and
websites, as with a client's data. Companies are split by a hash of their QID into dev (tuning) and
test (reported). Downloads are cached in `$CANON_CACHE` (default `~/.cache/canon`); nothing
downloaded is committed, only aggregate results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from canon.models import SourceRecord  # noqa: E402
from canon.resolve.evaluate import bcubed, pairwise  # noqa: E402
from canon.resolve.normalize import normalize_name  # noqa: E402
from canon.resolve.pipeline import resolve  # noqa: E402

UA = "canon-benchmark/0.1 (research; contact via repository)"  # SEC refuses UAs with URLs
CACHE = Path(os.environ.get("CANON_CACHE", Path.home() / ".cache" / "canon")) / "company_er"
SPARQL = """SELECT ?item ?label ?cik ?lei ?site ?hqLabel WHERE {
  ?item wdt:P5531 ?cik; wdt:P1278 ?lei.
  ?item rdfs:label ?label FILTER(lang(?label) = "en")
  OPTIONAL { ?item wdt:P856 ?site }
  OPTIONAL { ?item wdt:P159 ?hq. ?hq rdfs:label ?hqLabel FILTER(lang(?hqLabel) = "en") }
}"""


def _get(url: str, data: dict | None = None, accept: str = "application/json") -> bytes:
    if data:
        url += "?" + urllib.parse.urlencode(data)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return b""
            if attempt == 3:
                raise
            if exc.code == 429:  # rate limited: wait as long as the server asks
                time.sleep(int(exc.headers.get("Retry-After") or 65))
                continue
        time.sleep(2**attempt)
    return b""


def _cached(name: str, fetch) -> dict | list:
    path = CACHE / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        data = fetch()
        path.write_text(json.dumps(data), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def wikidata() -> dict[str, dict]:
    def fetch():
        raw = _get("https://query.wikidata.org/sparql", {"query": SPARQL, "format": "json"})
        return json.loads(raw)["results"]["bindings"]

    rows = _cached("wikidata.json", fetch)
    out: dict[str, dict] = {}
    for b in rows:
        qid = b["item"]["value"].rsplit("/", 1)[1]
        e = out.setdefault(qid, {"qid": qid, "label": b["label"]["value"], "cik": set(),
                                 "lei": set(), "site": None, "city": None})  # fmt: skip
        e["cik"].add(b["cik"]["value"].zfill(10))
        e["lei"].add(b["lei"]["value"])
        e["site"] = e["site"] or (b.get("site") or {}).get("value")
        e["city"] = e["city"] or (b.get("hqLabel") or {}).get("value")
    # one CIK and one LEI per company: entries with several are ambiguous in the answer key
    return {q: e for q, e in out.items() if len(e["cik"]) == 1 and len(e["lei"]) == 1}


def sec(cik: str) -> dict:
    def fetch():
        time.sleep(0.15)  # SEC fair-access: well under 10 requests per second
        raw = _get(f"https://data.sec.gov/submissions/CIK{cik}.json")
        if not raw:
            return {}
        d = json.loads(raw)
        return {k: d.get(k) for k in ("name", "addresses", "phone", "website", "formerNames")}

    return _cached(f"sec/{cik}.json", fetch)


def gleif(leis: list[str]) -> dict[str, dict]:
    out = {}
    for i in range(0, len(leis), 100):
        chunk = leis[i : i + 100]
        key = hashlib.sha1(",".join(chunk).encode()).hexdigest()[:16]

        def fetch(chunk=chunk):
            raw = _get(
                "https://api.gleif.org/api/v1/lei-records",
                {"filter[lei]": ",".join(chunk), "page[size]": 100},
                accept="application/vnd.api+json",
            )
            return json.loads(raw)["data"]

        for rec in _cached(f"gleif/{key}.json", fetch):
            ent = rec["attributes"]["entity"]
            hq = ent.get("headquartersAddress") or ent.get("legalAddress") or {}
            out[rec["id"]] = {
                "name": ent["legalName"]["name"],
                "street": ", ".join(hq.get("addressLines") or []),
                "city": hq.get("city"),
            }
    return out


def split_of(qid: str) -> str:
    return "dev" if int(hashlib.sha1(qid.encode()).hexdigest(), 16) % 2 == 0 else "test"


def build(limit: int | None) -> tuple[list[SourceRecord], dict[str, str], set[str]]:
    """Records, record id -> QID (the answer key), and the ids of stale renamed-company records."""
    companies = dict(sorted(wikidata().items()))
    if limit:
        companies = dict(list(companies.items())[:limit])
    leis = sorted(next(iter(e["lei"])) for e in companies.values())
    registry = gleif(leis)
    records, truth, renamed = [], {}, set()

    def add(rid, qid, **kw):
        records.append(SourceRecord(record_id=rid, source="crm", **kw))
        truth[rid] = qid

    for n, (qid, e) in enumerate(companies.items()):
        if n % 200 == 0:
            print(f"  {n}/{len(companies)} companies", file=sys.stderr)
        cik, lei = next(iter(e["cik"])), next(iter(e["lei"]))
        add(f"crm:wd:{qid}", qid, locator="wikidata", name=e["label"], domain=e["site"],
            city=e["city"])  # fmt: skip
        s = sec(cik)
        if s.get("name"):
            biz = (s.get("addresses") or {}).get("business") or {}
            street = " ".join(x for x in (biz.get("street1"), biz.get("street2")) if x)
            add(f"crm:sec:{cik}", qid, locator="sec-edgar", name=s["name"],
                address=street or None, city=biz.get("city"), phone=s.get("phone") or None,
                domain=s.get("website") or None)  # fmt: skip
            former = sorted(s.get("formerNames") or [], key=lambda f: f.get("to") or "")
            if former and normalize_name(former[-1]["name"]) != normalize_name(s["name"]):
                rid = f"crm:old:{cik}"
                add(rid, qid, locator="stale-crm", name=former[-1]["name"], domain=e["site"])
                renamed.add(rid)
        g = registry.get(lei)
        if g:
            add(f"crm:lei:{lei}", qid, locator="gleif", name=g["name"], address=g["street"] or None,
                city=g["city"])  # fmt: skip
    return records, truth, renamed


def exact_name(records: list[SourceRecord]) -> list[list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for r in records:
        groups[normalize_name(r.name or "")].append(r.record_id)
    return list(groups.values())


def run(records, truth, renamed) -> dict:
    res = resolve(records)
    cluster = {rid: k for k, c in enumerate(res.clusters) for rid in c}
    by_entity: dict[str, list[str]] = defaultdict(list)
    for rid, q in truth.items():
        by_entity[q].append(rid)
    complete = sum(len({cluster[r] for r in rids}) == 1 for rids in by_entity.values())
    mixed = sum(len({truth[r] for r in c}) > 1 for c in res.clusters)
    linked_renamed = sum(
        any(cluster[o] == cluster[r] for o in by_entity[truth[r]] if o != r) for r in renamed
    )
    queued = {frozenset((i.left, i.right)) for i in res.review}
    renamed_review = sum(
        1
        for r in renamed
        if not any(cluster[o] == cluster[r] for o in by_entity[truth[r]] if o != r)
        and any(frozenset((r, o)) in queued for o in by_entity[truth[r]] if o != r)
    )
    return {
        "companies": len(by_entity),
        "records": len(records),
        "canon": pairwise(res.clusters, truth),
        "canon_bcubed": bcubed(res.clusters, truth),
        "exact": pairwise(exact_name(records), truth),
        "complete": complete,
        "mixed_clusters": mixed,
        "renamed": len(renamed),
        "renamed_linked": linked_renamed,
        "renamed_review": renamed_review,
        "review": len(res.review),
    }


def render(results: dict) -> str:
    lines = [
        "# Real companies across three systems (Wikidata, SEC EDGAR, GLEIF)",
        "",
        "Generated by `scripts/company_er_benchmark.py`. Each US-listed company with both an "
        "SEC CIK and an LEI in Wikidata appears as a CRM-like record (Wikidata: everyday name, "
        "website, HQ city), a finance-like record (SEC EDGAR: filing name, street address, "
        "phone) and a legal-entity record (GLEIF: legal name, address), plus a stale CRM "
        "account under the company's most recent former name when it changed name. All values "
        "are real (CC0 / public domain); the answer key is the identifiers, which Canon does "
        "not see.",
        "",
    ]
    for split, r in results.items():
        c, b, e = r["canon"], r["canon_bcubed"], r["exact"]
        lines += [
            f"## {split} ({r['companies']} companies, {r['records']} records)",
            "",
            "| method | precision | recall | F1 |",
            "|---|---|---|---|",
            f"| exact normalized name | {e.precision:.3f} | {e.recall:.3f} | {e.f1:.3f} |",
            f"| Canon (pairwise) | {c.precision:.3f} | {c.recall:.3f} | {c.f1:.3f} |",
            f"| Canon (B-cubed) | {b.precision:.3f} | {b.recall:.3f} | {b.f1:.3f} |",
            "",
            f"- Companies whose records all ended up together: {r['complete']} of "
            f"{r['companies']} ({100 * r['complete'] / r['companies']:.0f}%).",
            f"- Clusters that wrongly mix two companies: {r['mixed_clusters']}.",
            f"- Renamed companies: the stale account under the former name was linked for "
            f"{r['renamed_linked']} of {r['renamed']}; {r['renamed_review']} more were sent to a "
            "person.",
            f"- Review queue: {r['review']} pair decisions.",
            "",
        ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    ap.add_argument("--limit", type=int, default=None, help="first N companies (quick runs)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    records, truth, renamed = build(args.limit)
    splits = ["dev", "test"] if args.split == "all" else [args.split]
    results = {}
    for s in splits:
        keep = {rid for rid, q in truth.items() if split_of(q) == s}
        results[s] = run(
            [r for r in records if r.record_id in keep],
            {rid: q for rid, q in truth.items() if rid in keep},
            renamed & keep,
        )
    report = render(results)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
