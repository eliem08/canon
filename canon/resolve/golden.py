"""Golden records: per-field survivorship with lineage to every source record.

Identity fields use simple, explainable survivorship rules. Business facts
(owner, contract terms, address, ...) come from `canon.score`: freshness x
authority, with losing values kept as alternatives in `GoldenRecord.facts`.

| field | rule |
|---|---|
| legal_name | active contract party name, else most frequent Latin CRM name |
| name | legal_name without legal suffix |
| arabic_name | any Arabic-script name seen |
| domain, phone, tax_id | source-weighted vote (contract 3, CRM 2, Slack 1), ties -> recency |
| city | active contract, else most recently updated CRM record |
| owner, address, signatory, contract_*, renewal_date | scored fact (see `canon.score`) |
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from datetime import date

from canon.models import FieldValue, GoldenRecord, SourceRecord
from canon.resolve.normalize import has_arabic, strip_legal_suffix
from canon.score import FACT_FIELDS, FactScoringConfig, score_entity

SOURCE_PRIORITY = {"contract": 3, "crm": 2, "email": 1, "slack": 0}
VOTE_WEIGHT = {"contract": 3.0, "crm": 2.0, "email": 1.0, "slack": 1.0}


def _recency(r: SourceRecord) -> date:
    return r.updated_at or date.min


def _vote(records: Iterable[SourceRecord], get: Callable[[SourceRecord], object]) -> FieldValue:
    support: dict[object, list[SourceRecord]] = {}
    for r in records:
        v = get(r)
        if v not in (None, ""):
            support.setdefault(v, []).append(r)
    if not support:
        return FieldValue(value=None, rule="no source")

    def weight(recs: list[SourceRecord]) -> float:
        return sum(VOTE_WEIGHT.get(r.source, 1.0) for r in recs)

    value, recs = max(
        support.items(), key=lambda kv: (weight(kv[1]), max(_recency(r) for r in kv[1]))
    )
    total = sum(weight(v) for v in support.values())
    return FieldValue(
        value=value,
        record_ids=sorted(r.record_id for r in recs),
        rule=f"source-weighted vote ({weight(recs):g}/{total:g})",
    )


def _first_by_priority(records: list[SourceRecord], get, rule: str) -> FieldValue:
    ranked = sorted(
        (r for r in records if get(r)),
        key=lambda r: (r.status == "active", SOURCE_PRIORITY.get(r.source, 0), _recency(r)),
        reverse=True,
    )
    if not ranked:
        return FieldValue(value=None, rule="no source")
    return FieldValue(value=get(ranked[0]), record_ids=[ranked[0].record_id], rule=rule)


def build_golden(
    entity_id: str, records: list[SourceRecord], fact_config: FactScoringConfig | None = None
) -> GoldenRecord:
    fields: dict[str, FieldValue] = {}
    contracts = [r for r in records if r.source == "contract" and r.status == "active" and r.name]
    if contracts:
        best = max(contracts, key=_recency)
        legal = FieldValue(
            value=best.name.replace(", ", " ").removeprefix("Ste ").strip(),
            record_ids=[best.record_id],
            rule="active contract party",
        )
    else:
        latin = [r for r in records if r.source == "crm" and r.name and not has_arabic(r.name)]
        legal = _vote(latin or records, lambda r: r.name)
    fields["legal_name"] = legal
    fields["name"] = FieldValue(
        value=strip_legal_suffix(str(legal.value)) if legal.value else None,
        record_ids=legal.record_ids,
        rule="legal_name without legal form",
    )
    arabic = sorted(
        {n for r in records for n in r.all_names() if has_arabic(n)},
        key=lambda n: Counter(m for r in records for m in r.all_names())[n],
        reverse=True,
    )
    fields["arabic_name"] = FieldValue(
        value=strip_legal_suffix(arabic[0]) if arabic else None,
        record_ids=sorted(r.record_id for r in records if arabic and arabic[0] in r.all_names()),
        rule="any Arabic-script name",
    )
    fields["domain"] = _vote(records, lambda r: r.domain)
    fields["phone"] = _vote(records, lambda r: r.phone)
    fields["tax_id"] = _vote(records, lambda r: r.tax_id)
    fields["city"] = _first_by_priority(
        records, lambda r: r.city, "active contract > CRM, most recent"
    )
    facts = score_entity(records, fact_config)
    for name in FACT_FIELDS:
        fact = facts.get(name)
        fields[name] = FieldValue(
            value=fact.value if fact else None,
            record_ids=sorted(e.record_id for e in fact.sources) if fact else [],
            rule=f"scored fact (confidence {fact.confidence:.2f})" if fact else "no source",
        )
    acl = sorted({a for r in records for a in r.acl})
    return GoldenRecord(
        entity_id=entity_id,
        fields=fields,
        members=sorted(r.record_id for r in records),
        acl=acl,
        facts=facts,
    )
