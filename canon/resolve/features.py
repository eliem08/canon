"""Per-record comparison features, computed once and reused by blocking and scoring."""

from __future__ import annotations

from dataclasses import dataclass

from canon.models import SourceRecord
from canon.resolve.lexicon import business_types, name_concepts
from canon.resolve.normalize import (
    acronyms as acronyms_of,
)
from canon.resolve.normalize import (
    normalize_address,
    normalize_city,
    normalize_name,
    skeleton,
)


@dataclass(frozen=True)
class RecordFeatures:
    record_id: str
    names: tuple[str, ...]  # normalized Latin forms of every name the record carries
    skeletons: tuple[str, ...]
    acronyms: tuple[str, ...]
    domain: str | None
    phone: str | None  # national significant number (last 9 digits)
    tax_id: str | None
    address: str
    city: str
    concepts: tuple[tuple[str, ...], ...] = ()  # per name: concept ids / skeletons (lexicon.py)
    types: frozenset[str] = frozenset()  # business types across all names


def features(record: SourceRecord) -> RecordFeatures:
    names = [n for n in record.all_names() if n]
    normalized = tuple(dict.fromkeys(x for x in (normalize_name(n) for n in names) if x))
    skeletons = tuple(dict.fromkeys(x for x in (skeleton(n) for n in names) if x))
    acronyms = tuple(sorted({a for n in names for a in acronyms_of(n) if len(a) >= 2}))
    concepts = tuple(dict.fromkeys(c for c in (name_concepts(n) for n in names) if c))
    phone = record.phone[-9:] if record.phone else None
    tax_id = "".join(c for c in record.tax_id if c.isdigit()) if record.tax_id else None
    return RecordFeatures(
        record_id=record.record_id,
        names=normalized,
        skeletons=skeletons,
        acronyms=acronyms,
        domain=record.domain,
        phone=phone,
        tax_id=tax_id or None,
        address=normalize_address(record.address),
        city=normalize_city(record.city),
        concepts=concepts,
        types=frozenset().union(*(business_types(c) for c in concepts))
        if concepts
        else frozenset(),
    )
