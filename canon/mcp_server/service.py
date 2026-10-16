"""Permission-aware query service behind the MCP tools (no MCP dependency).

Access control is applied to *source records before scoring*: a caller's answer is
computed only from the records whose ACL intersects the caller's groups. A value
that only a hidden source asserts can therefore never win, appear as an
alternative, or be inferred from confidence. Entity membership (which records
belong together) is resolved globally, but an entity is invisible to a caller who
can see none of its records, so name lookups return nothing for it.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from canon.guard import screen
from canon.models import Evidence, Fact, ResolvedFact, SourceRecord
from canon.resolve.features import features
from canon.resolve.golden import build_golden
from canon.resolve.normalize import has_arabic, normalize_name
from canon.resolve.scoring import name_similarity
from canon.score import FactScoringConfig, score_entity, score_field

from .audit import AuditLog
from .schemas import (
    Alternative,
    Answer,
    ConflictList,
    ContractTerms,
    CustomerMatch,
    CustomerProfile,
    OwnerAnswer,
    SourceRef,
)

CONTRACT_FIELDS = (
    "contract_number",
    "contract_value",
    "contract_start",
    "renewal_date",
    "signatory",
)
IDENTITY_FIELDS = ("domain", "phone", "tax_id", "city")
PROFILE_FIELDS = ("owner", "contract_value", "renewal_date", "address")


@dataclass(frozen=True)
class Caller:
    caller_id: str
    groups: frozenset[str]
    name: str = ""


def _principals(entry: dict) -> frozenset[str]:
    """A caller's ACL principals: their groups, plus `slack-user:<id>` for private channels."""
    groups = set(entry.get("groups", []))
    if entry.get("slack_user_id"):
        groups.add(f"slack-user:{entry['slack_user_id']}")
    return frozenset(groups)


@dataclass
class CallerDirectory:
    """Maps caller identities to ACL groups. Unknown callers get no groups."""

    callers: dict[str, Caller] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: Path) -> CallerDirectory:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            {
                cid: Caller(cid, _principals(c), c.get("name", ""))
                for cid, c in data["callers"].items()
            }
        )

    def resolve(self, caller_id: str) -> Caller:
        return self.callers.get(caller_id) or Caller(caller_id, frozenset())


@dataclass
class ServiceConfig:
    facts: FactScoringConfig = field(default_factory=FactScoringConfig)
    match_threshold: float = 0.8  # minimum name similarity to accept a lookup
    ambiguity_margin: float = 0.03  # top-2 matches closer than this -> ambiguous


class CanonService:
    def __init__(
        self,
        records: list[SourceRecord],
        clusters: dict[str, list[str]],
        directory: CallerDirectory,
        config: ServiceConfig | None = None,
        audit: AuditLog | None = None,
    ) -> None:
        self.records = {r.record_id: r for r in records}
        self.clusters = clusters
        self.directory = directory
        self.config = config or ServiceConfig()
        self.audit = audit
        self._features = {rid: features(r) for rid, r in self.records.items()}

    # ------------------------------------------------------------- construction
    @classmethod
    def from_store(
        cls,
        path: Path,
        directory: CallerDirectory,
        config: ServiceConfig | None = None,
        audit: AuditLog | None = None,
    ) -> CanonService:
        with sqlite3.connect(path) as db:
            records = [
                SourceRecord.model_validate_json(p)
                for (p,) in db.execute("SELECT payload FROM records")
            ]
            clusters: dict[str, list[str]] = {}
            for eid, rid in db.execute("SELECT entity_id, record_id FROM lineage ORDER BY 1, 2"):
                clusters.setdefault(eid, []).append(rid)
        return cls(records, clusters, directory, config, audit)

    # ------------------------------------------------------------- access control
    def _visible(self, entity_id: str, caller: Caller) -> list[SourceRecord]:
        return [
            self.records[rid]
            for rid in self.clusters.get(entity_id, [])
            if caller.groups & set(self.records[rid].acl)
        ]

    def _partial(self, entity_id: str, visible: list[SourceRecord]) -> bool:
        return len(visible) < len(self.clusters.get(entity_id, []))

    # ------------------------------------------------------------- lookup
    def _match(self, query: str, caller: Caller) -> tuple[CustomerMatch | None, list, str]:
        query = query.strip()
        if query in self.clusters:  # exact entity id
            visible = self._visible(query, caller)
            if visible:
                return CustomerMatch(entity_id=query, name=_name(visible), match_score=1.0), [], ""
            return None, [], "No customer found."
        probe = features(SourceRecord(record_id="query", source="crm", locator="query", name=query))
        scored = []
        for eid in self.clusters:
            visible = self._visible(eid, caller)
            if not visible:
                continue
            best = max(name_similarity(probe, self._features[r.record_id]) for r in visible)
            if best >= self.config.match_threshold:
                scored.append(
                    CustomerMatch(entity_id=eid, name=_name(visible), match_score=round(best, 3))
                )
        scored.sort(key=lambda m: m.match_score, reverse=True)
        if not scored:
            return None, [], "No customer found."
        top, rest = scored[0], scored[1:]
        close = [m for m in rest if top.match_score - m.match_score < self.config.ambiguity_margin]
        if close:
            names = ", ".join(m.name or m.entity_id for m in [top, *close])
            return (
                None,
                [top, *close],
                f"Ambiguous name; candidates: {names}. Retry with entity_id.",
            )
        return top, rest[:3], ""

    # ------------------------------------------------------------- tools
    def get_customer(self, name: str, caller_id: str) -> CustomerProfile:
        return self._serve("get_customer", self._get_customer, name, caller_id)

    def find_contract_terms(self, customer: str, caller_id: str) -> ContractTerms:
        return self._serve("find_contract_terms", self._find_contract_terms, customer, caller_id)

    def who_owns(self, customer: str, caller_id: str) -> OwnerAnswer:
        return self._serve("who_owns", self._who_owns, customer, caller_id)

    def list_conflicts(self, customer: str, caller_id: str) -> ConflictList:
        return self._serve("list_conflicts", self._list_conflicts, customer, caller_id)

    def _serve(self, tool: str, impl, query: str, caller_id: str):
        """Run a tool, withhold injected source text, then write the audit line."""
        response = impl(query, caller_id)
        response.withheld = _screen(response)
        if self.audit is not None:
            known = caller_id in self.directory.callers
            self.audit.record(tool, caller_id, known, query, response, response.withheld)
        return response

    def _get_customer(self, name: str, caller_id: str) -> CustomerProfile:
        caller = self.directory.resolve(caller_id)
        match, candidates, msg = self._match(name, caller)
        if match is None:
            return CustomerProfile(found=False, message=msg, candidates=candidates)
        visible = self._visible(match.entity_id, caller)
        facts = self._facts(visible)
        fields = {"name": self._name_answer(visible)}
        for f in (*IDENTITY_FIELDS, *PROFILE_FIELDS):
            if f in facts:
                fields[f] = facts[f]
        aliases = sorted({n for r in visible for n in r.all_names() if n})
        return CustomerProfile(
            found=True,
            customer=match,
            candidates=candidates,
            partial_view=self._partial(match.entity_id, visible),
            aliases=aliases,
            fields=fields,
        )

    def _find_contract_terms(self, customer: str, caller_id: str) -> ContractTerms:
        caller = self.directory.resolve(caller_id)
        match, candidates, msg = self._match(customer, caller)
        if match is None:
            return ContractTerms(found=False, message=msg, candidates=candidates)
        visible = self._visible(match.entity_id, caller)
        facts = self._facts(visible)
        terms = {f: facts[f] for f in CONTRACT_FIELDS if f in facts}
        documents = [
            _record_ref(r)
            for r in sorted(visible, key=lambda r: r.record_id)
            if r.source == "contract"
        ]
        message = (
            "" if documents else "No contract visible to this caller; terms come from CRM/Slack."
        )
        return ContractTerms(
            found=True,
            customer=match,
            candidates=candidates,
            terms=terms,
            documents=documents,
            message=message,
            partial_view=self._partial(match.entity_id, visible),
        )

    def _who_owns(self, customer: str, caller_id: str) -> OwnerAnswer:
        caller = self.directory.resolve(caller_id)
        match, candidates, msg = self._match(customer, caller)
        if match is None:
            return OwnerAnswer(found=False, message=msg, candidates=candidates)
        visible = self._visible(match.entity_id, caller)
        owner = self._facts(visible).get("owner")
        return OwnerAnswer(
            found=True,
            customer=match,
            candidates=candidates,
            owner=owner,
            partial_view=self._partial(match.entity_id, visible),
            message="" if owner else "No owner information visible to this caller.",
        )

    def _list_conflicts(self, customer: str, caller_id: str) -> ConflictList:
        caller = self.directory.resolve(caller_id)
        match, candidates, msg = self._match(customer, caller)
        if match is None:
            return ConflictList(found=False, message=msg, candidates=candidates)
        visible = self._visible(match.entity_id, caller)
        conflicts = [a for a in self._facts(visible).values() if a.conflict]
        conflicts.sort(key=lambda a: a.confidence)
        return ConflictList(
            found=True,
            customer=match,
            candidates=candidates,
            partial_view=self._partial(match.entity_id, visible),
            conflicts=conflicts,
        )

    # ------------------------------------------------------------- helpers
    def _facts(self, visible: list[SourceRecord]) -> dict[str, Answer]:
        resolved = score_entity(visible, self.config.facts)
        attribute_records = [_attributes_as_facts(r) for r in visible]
        for f in IDENTITY_FIELDS:
            fact = score_field(f, attribute_records, self.config.facts)
            if fact is not None:
                resolved[f] = fact
        return {name: self._answer(fact) for name, fact in resolved.items()}

    def _ref(self, e: Evidence) -> SourceRef:
        return SourceRef(
            record_id=e.record_id,
            source=e.source,
            status=e.status,
            locator=self.records[e.record_id].locator,
            observed_at=e.observed_at,
            value=e.value,
            weight=e.weight,
            source_ref=e.source_ref,
            quote=e.quote,
        )

    def _answer(self, fact: ResolvedFact) -> Answer:
        return Answer(
            field=fact.field,
            value=fact.value,
            confidence=fact.confidence,
            last_updated=fact.last_updated,
            sources=[self._ref(e) for e in fact.sources],
            alternatives=[
                Alternative(
                    value=a.value,
                    score=a.score,
                    last_updated=a.last_updated,
                    sources=[self._ref(e) for e in a.sources],
                )
                for a in fact.alternatives
            ],
            conflict=fact.conflict,
            explanation=fact.explanation,
        )

    def _name_answer(self, visible: list[SourceRecord]) -> Answer:
        golden = build_golden("tmp", visible, self.config.facts)
        name = golden.fields["name"]
        key = normalize_name(str(name.value)) if name.value else ""
        latin = [r for r in visible if r.name and not has_arabic(r.name)]
        agree = [r for r in latin if normalize_name(r.name) == key]
        dates = [r.updated_at for r in agree if r.updated_at]
        return Answer(
            field="name",
            value=name.value,
            confidence=round(len(agree) / len(latin), 4) if latin else 0.0,
            last_updated=max(dates) if dates else None,
            sources=[_record_ref(r) for r in agree],
            explanation=f"{name.rule}; {len(agree)}/{len(latin)} Latin-script names agree",
        )


def _name(visible: list[SourceRecord]) -> str | None:
    contracts = [r for r in visible if r.source == "contract" and r.status == "active" and r.name]
    pool = contracts or [r for r in visible if r.name and not has_arabic(r.name)] or visible
    best = max(pool, key=lambda r: (r.updated_at is not None, r.updated_at))
    return best.name.replace(", ", " ").removeprefix("Ste ").strip() if best.name else None


def _record_ref(r: SourceRecord) -> SourceRef:
    return SourceRef(
        record_id=r.record_id,
        source=r.source,
        status=r.status,
        locator=r.locator,
        observed_at=r.updated_at,
        value=r.name or "",
        weight=1.0,
    )


def _attributes_as_facts(r: SourceRecord) -> SourceRecord:
    """Expose identity attributes as dated facts so they get the same scoring/conflicts."""
    facts = [
        Fact(field=f, value=getattr(r, f), observed_at=r.updated_at, record_id=r.record_id)
        for f in IDENTITY_FIELDS
        if getattr(r, f)
    ]
    return r.model_copy(update={"facts": facts})


_SCREENED = {"quote", "value", "name", "explanation"}


def _screen(obj: object) -> int:
    """Withhold source text that looks like a prompt injection, in place; returns the count."""
    hits = 0
    if isinstance(obj, BaseModel):
        for key, val in list(obj):
            if key in _SCREENED and isinstance(val, str):
                safe, rule = screen(val, max_chars=300 if key == "quote" else 10_000)
                if safe != val:
                    setattr(obj, key, safe)
                hits += rule is not None
            elif key == "aliases" and isinstance(val, list):
                kept = [a for a in val if screen(a)[1] is None]
                hits += len(val) - len(kept)
                setattr(obj, key, kept)
            else:
                hits += _screen(val)
    elif isinstance(obj, list):
        hits += sum(_screen(v) for v in obj)
    elif isinstance(obj, dict):
        hits += sum(_screen(v) for v in obj.values())
    return hits
