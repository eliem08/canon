"""SQLite persistence for source records, facts, golden records and lineage."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from canon.models import GoldenRecord, ResolvedFact, SourceRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    record_id TEXT PRIMARY KEY, source TEXT NOT NULL, locator TEXT, name TEXT,
    status TEXT, updated_at TEXT, acl TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    record_id TEXT NOT NULL REFERENCES records(record_id), field TEXT NOT NULL,
    value TEXT, observed_at TEXT
);
CREATE TABLE IF NOT EXISTS golden_fields (
    entity_id TEXT NOT NULL, field TEXT NOT NULL, value TEXT, rule TEXT,
    record_ids TEXT NOT NULL, PRIMARY KEY (entity_id, field)
);
CREATE TABLE IF NOT EXISTS lineage (
    entity_id TEXT NOT NULL, record_id TEXT NOT NULL REFERENCES records(record_id),
    PRIMARY KEY (entity_id, record_id)
);
CREATE TABLE IF NOT EXISTS entities (entity_id TEXT PRIMARY KEY, acl TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scored_facts (
    entity_id TEXT NOT NULL, field TEXT NOT NULL, value TEXT, confidence REAL,
    last_updated TEXT, conflict INTEGER NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY (entity_id, field)
);
"""


def write_store(path: Path, records: list[SourceRecord], golden: list[GoldenRecord]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.executemany(
            "INSERT INTO records VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    r.record_id,
                    r.source,
                    r.locator,
                    r.name,
                    r.status,
                    r.updated_at.isoformat() if r.updated_at else None,
                    json.dumps(r.acl),
                    r.model_dump_json(),
                )
                for r in records
            ],
        )
        db.executemany(
            "INSERT INTO facts VALUES (?,?,?,?)",
            [
                (
                    f.record_id,
                    f.field,
                    json.dumps(f.value),
                    f.observed_at.isoformat() if f.observed_at else None,
                )
                for r in records
                for f in r.facts
            ],
        )
        for g in golden:
            db.execute("INSERT INTO entities VALUES (?,?)", (g.entity_id, json.dumps(g.acl)))
            db.executemany(
                "INSERT INTO golden_fields VALUES (?,?,?,?,?)",
                [
                    (g.entity_id, name, json.dumps(fv.value), fv.rule, json.dumps(fv.record_ids))
                    for name, fv in g.fields.items()
                ],
            )
            db.executemany(
                "INSERT INTO lineage VALUES (?,?)", [(g.entity_id, m) for m in g.members]
            )
            db.executemany(
                "INSERT INTO scored_facts VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        g.entity_id,
                        name,
                        json.dumps(f.value),
                        f.confidence,
                        f.last_updated.isoformat() if f.last_updated else None,
                        int(f.conflict),
                        f.model_dump_json(),
                    )
                    for name, f in g.facts.items()
                ],
            )


def read_golden(path: Path) -> list[GoldenRecord]:
    with sqlite3.connect(path) as db:
        acl = dict(db.execute("SELECT entity_id, acl FROM entities"))
        fields: dict[str, dict] = {}
        for eid, name, value, rule, rids in db.execute("SELECT * FROM golden_fields"):
            fields.setdefault(eid, {})[name] = {
                "value": json.loads(value),
                "rule": rule,
                "record_ids": json.loads(rids),
            }
        facts: dict[str, dict] = {}
        for eid, name, payload in db.execute("SELECT entity_id, field, payload FROM scored_facts"):
            facts.setdefault(eid, {})[name] = ResolvedFact.model_validate_json(payload)
        members: dict[str, list[str]] = {}
        for eid, rid in db.execute("SELECT entity_id, record_id FROM lineage ORDER BY 1, 2"):
            members.setdefault(eid, []).append(rid)
    return [
        GoldenRecord(
            entity_id=eid,
            fields=fields[eid],
            members=members[eid],
            acl=json.loads(acl[eid]),
            facts=facts.get(eid, {}),
        )
        for eid in sorted(acl)
    ]
