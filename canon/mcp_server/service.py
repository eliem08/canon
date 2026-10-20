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
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import partial
from pathlib import Path

from pydantic import BaseModel

from canon.guard import screen
from canon.ingest.contract_terms import add_months
from canon.models import Evidence, Fact, ResolvedFact, SourceRecord
from canon.resolve.blocking import blocking_keys
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
    "renewal_period_months",
    "renewal_notice",
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
    """A caller's ACL principals: their groups, plus `<platform>-user:<id>` for private chats
    (`slack_user_id`, or `chat_ids: {"teams": "<aad id>", "whatsapp": "+2126..."}`)."""
    groups = set(entry.get("groups", []))
    if entry.get("slack_user_id"):
        groups.add(f"slack-user:{entry['slack_user_id']}")
    for platform, uid in (entry.get("chat_ids") or {}).items():
        groups.add(f"{platform}-user:{uid}")
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
    max_sources: int = 3  # sources listed per answer; the rest are counted in more_sources


def _next_renewal(facts: dict[str, Answer], today: date) -> Answer | None:
    """An auto-renewing contract whose end date has passed: roll it forward by the renewal period
    to the first date after today. Computed: it cites both facts and keeps the weaker
    confidence."""
    end, period = facts.get("renewal_date"), facts.get("renewal_period_months")
    if not end or not period or end.conflict or period.conflict:
        return None
    try:
        d, months = date.fromisoformat(str(end.value)), int(period.value)
    except (TypeError, ValueError):
        return None
    if d > today or months <= 0:
        return None
    steps = ((today.year - d.year) * 12 + today.month - d.month) // months
    nxt = add_months(d, months * steps)
    while nxt is not None and nxt <= today:
        steps += 1
        nxt = add_months(d, months * steps)
    if nxt is None:  # 29 February, 31st of a short month: no single right answer
        return None
    d = nxt
    return Answer(
        field="next_renewal",
        value=d.isoformat(),
        confidence=min(end.confidence, period.confidence),
        last_updated=end.last_updated,
        sources=(end.sources + period.sources)[:3],
        explanation=(
            f"Computed: the term ended {end.value} and renews automatically every {months} "
            f"month(s); next renewal after {today.isoformat()}."
        ),
    )


def _cancel_by(facts: dict[str, Answer], renewal: Answer | None, today: date) -> Answer | None:
    """The last day to give non-renewal notice before the coming renewal (the computed next
    renewal, else the stated end date when it is still ahead)."""
    notice, period = facts.get("renewal_notice"), facts.get("renewal_period_months")
    if renewal is None:
        renewal = facts.get("renewal_date")
    if not notice or not period or not renewal or notice.conflict or renewal.conflict:
        return None
    m = re.fullmatch(r"P(\d+)([DM])", str(notice.value))
    try:
        d = date.fromisoformat(str(renewal.value))
    except ValueError:
        return None
    if not m or d <= today:
        return None
    n = int(m.group(1))
    by = d - timedelta(days=n) if m.group(2) == "D" else add_months(d, -n)
    if by is None:
        return None
    return Answer(
        field="cancel_by",
        value=by.isoformat(),
        confidence=min(notice.confidence, renewal.confidence),
        last_updated=renewal.last_updated,
        sources=(renewal.sources + notice.sources)[:3],
        explanation=(
            f"Computed: notice of {notice.value} before the renewal on {renewal.value}."
            + (" Already passed: the contract renews unless the parties agree otherwise."
               if by < today else "")
        ),
    )  # fmt: skip


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
        # name-key index (the ER blocking keys) so a lookup scores a few entities, not all
        self._name_index: dict[str, set[str]] = {}
        for eid, members in clusters.items():
            for rid in members:
                for key in _name_keys(self._features[rid]):
                    self._name_index.setdefault(key, set()).add(eid)

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
        keys = _name_keys(probe)
        if keys:  # score only entities sharing a name key with the query (ER blocking keys)
            candidates = sorted(set().union(*(self._name_index.get(k, set()) for k in keys)))
        else:  # nothing to index on (e.g. a very short query): score everything
            candidates = list(self.clusters)
        scored = self._score_entities(probe, caller, candidates)
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

    def _score_entities(self, probe, caller: Caller, entity_ids) -> list[CustomerMatch]:
        scored = []
        for eid in entity_ids:
            visible = self._visible(eid, caller)
            if not visible:
                continue
            best = max(name_similarity(probe, self._features[r.record_id]) for r in visible)
            if best >= self.config.match_threshold:
                scored.append(
                    CustomerMatch(entity_id=eid, name=_name(visible), match_score=round(best, 3))
                )
        return scored

    # ------------------------------------------------------------- tools
    def get_customer(
        self, name: str, caller_id: str, fields: list[str] | None = None
    ) -> CustomerProfile:
        impl = partial(self._get_customer, fields=fields)
        return self._serve("get_customer", impl, name, caller_id)

    def find_contract_terms(
        self, customer: str, caller_id: str, fields: list[str] | None = None
    ) -> ContractTerms:
        impl = partial(self._find_contract_terms, fields=fields)
        return self._serve("find_contract_terms", impl, customer, caller_id)

    def who_owns(self, customer: str, caller_id: str) -> OwnerAnswer:
        return self._serve("who_owns", self._who_owns, customer, caller_id)

    def list_conflicts(self, customer: str, caller_id: str) -> ConflictList:
        return self._serve("list_conflicts", self._list_conflicts, customer, caller_id)

    def _serve(self, tool: str, impl, query: str, caller_id: str):
        """Run a tool, withhold injected source text, then write the audit line."""
        response = impl(query, caller_id)
        response.withheld = _screen(response)
        response.records = {rid: self.records[rid].locator for rid in sorted(_cited_ids(response))}
        if self.audit is not None:
            known = caller_id in self.directory.callers
            self.audit.record(tool, caller_id, known, query, response, response.withheld)
        return response

    def _get_customer(
        self, name: str, caller_id: str, fields: list[str] | None = None
    ) -> CustomerProfile:
        caller = self.directory.resolve(caller_id)
        match, candidates, msg = self._match(name, caller)
        if match is None:
            return CustomerProfile(found=False, message=msg, candidates=candidates)
        visible = self._visible(match.entity_id, caller)
        wanted = set(fields) if fields else None  # None: everything
        facts = self._facts(visible)
        answers = {}
        if wanted is None or "name" in wanted:
            answers["name"] = self._name_answer(visible)
        for f in (*IDENTITY_FIELDS, *PROFILE_FIELDS):
            if f in facts and (wanted is None or f in wanted):
                answers[f] = facts[f]
        show_aliases = wanted is None or "aliases" in wanted
        aliases = sorted({n for r in visible for n in r.all_names() if n}) if show_aliases else []
        return CustomerProfile(
            found=True,
            customer=match,
            candidates=candidates,
            partial_view=self._partial(match.entity_id, visible),
            aliases=aliases,
            fields=answers,
        )

    def _find_contract_terms(
        self, customer: str, caller_id: str, fields: list[str] | None = None
    ) -> ContractTerms:
        caller = self.directory.resolve(caller_id)
        match, candidates, msg = self._match(customer, caller)
        if match is None:
            return ContractTerms(found=False, message=msg, candidates=candidates)
        visible = self._visible(match.entity_id, caller)
        facts = self._facts(visible)
        terms = {f: facts[f] for f in CONTRACT_FIELDS if f in facts and (not fields or f in fields)}
        nxt = _next_renewal(facts, self.config.facts.reference_date())
        if nxt and (not fields or "next_renewal" in fields):
            terms["next_renewal"] = nxt
        cancel = _cancel_by(facts, nxt, self.config.facts.reference_date())
        if cancel and (not fields or "cancel_by" in fields):
            terms["cancel_by"] = cancel
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

    def _ref(self, e: Evidence, quote: bool = False) -> SourceRef:
        locator = self.records[e.record_id].locator
        ref = e.source_ref
        if ref and ref.startswith(locator):  # the locator is in `records`; keep the fragment
            ref = ref[len(locator) :] or None
        return SourceRef(
            record_id=e.record_id,
            source=e.source,
            status=e.status,
            observed_at=e.observed_at,
            weight=e.weight,
            source_ref=ref,
            quote=e.quote if quote else None,
        )

    def _answer(self, fact: ResolvedFact) -> Answer:
        n = self.config.max_sources
        return Answer(
            field=fact.field,
            value=fact.value,
            confidence=fact.confidence,
            last_updated=fact.last_updated,
            sources=[self._ref(e, quote=i == 0) for i, e in enumerate(fact.sources[:n])],
            more_sources=max(len(fact.sources) - n, 0),
            alternatives=[
                Alternative(
                    value=a.value,
                    score=a.score,
                    last_updated=a.last_updated,
                    sources=[self._ref(e) for e in _diverse(a.sources)],
                    more_sources=max(len(a.sources) - len(_diverse(a.sources)), 0),
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
            sources=[_record_ref(r) for r in agree[: self.config.max_sources]],
            more_sources=max(len(agree) - self.config.max_sources, 0),
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
        observed_at=r.updated_at,
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


def _cited_ids(obj: object) -> set[str]:
    if isinstance(obj, SourceRef):
        return {obj.record_id}
    if isinstance(obj, BaseModel):
        return set().union(*(_cited_ids(v) for _, v in obj)) if list(obj) else set()
    if isinstance(obj, list | tuple):
        return set().union(*(_cited_ids(v) for v in obj)) if obj else set()
    if isinstance(obj, dict):
        return set().union(*(_cited_ids(v) for v in obj.values())) if obj else set()
    return set()


def _diverse(sources: list[Evidence]) -> list[Evidence]:
    """The strongest source plus the first one with another status (e.g. a superseded contract
    behind a stale CRM value), so an alternative still shows why it lost."""
    if not sources:
        return []
    other = next((e for e in sources[1:] if e.status != sources[0].status), None)
    return [sources[0], other] if other else [sources[0]]


def _name_keys(f) -> set[str]:
    """Lookup keys of a record's names: the ER blocking keys (consonant-skeleton prefixes,
    acronyms) plus every whole name word, which catches words whose skeleton is too short to key
    on (`Hana` -> `n`)."""
    keys = {k for k in blocking_keys(f) if k.startswith(("sk:", "skj:", "ac:"))}
    keys |= {f"w:{w}" for name in f.names for w in name.split()}
    return keys
