"""MCP Readiness Audit: the client-facing report built from one ingest + resolve run.

Everything here is computed from the client's own data. No ground truth is needed: the report
lists what Canon *found* (duplicates, disagreements, stale CRM values, unreadable values,
borderline merges, permission gaps), each with the records behind it, and ranks the fixes.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import date

from pydantic import BaseModel, Field

from canon.models import GoldenRecord, ParseIssue, SourceRecord
from canon.resolve.normalize import fold
from canon.resolve.pipeline import Resolution

AUDITED_FIELDS = ("owner", "contract_value", "renewal_date", "address")
FIELD_LABELS = {
    "owner": "account owner",
    "contract_value": "contract value",
    "renewal_date": "renewal date",
    "address": "address",
}


class Finding(BaseModel):
    """One line of the prioritized fix list."""

    key: str
    title: str
    count: int
    weight: float  # how much one instance costs an agent (heuristic, see docs/AUDIT.md)
    who_fixes: str
    examples: list[str] = Field(default_factory=list)

    @property
    def impact(self) -> float:
        return self.count * self.weight


class StaleValue(BaseModel):
    entity_id: str
    customer: str | None
    field: str
    current: str
    current_source: str
    stale: str
    stale_record: str
    confidence: float


class CallerView(BaseModel):
    caller: str
    groups: list[str]
    records_visible: int
    customers_visible: int
    customers_partial: int


class Audit(BaseModel):
    as_of: date | None
    records_by_source: dict[str, int]
    records_by_status: dict[str, int]
    entities: int
    multi_record_entities: int
    cross_source_entities: int
    same_source_duplicates: dict[str, int]  # source -> customers with 2+ records there
    largest_clusters: list[tuple[str, str | None, list[str]]]  # (entity, name, record ids)
    conflicts_by_field: dict[str, int]
    low_confidence_by_field: dict[str, int]
    stale_crm: list[StaleValue]
    slack_only_owner_changes: list[StaleValue]
    quarantine_by_reason: dict[str, int]
    warnings_by_reason: dict[str, int]
    quarantine_examples: list[ParseIssue]
    review_items: int
    review_examples: list[dict]
    callers: list[CallerView]
    records_by_acl: dict[str, int]
    injections: int
    findings: list[Finding]


def show_value(value) -> str:
    """1426000.0 -> '1,426,000'; other values as they are."""
    if isinstance(value, float | int) and not isinstance(value, bool):
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    return str(value)


def _same(a, b) -> bool:
    if isinstance(a, int | float) and isinstance(b, int | float):
        return math.isclose(float(a), float(b), rel_tol=0.005)
    return fold(str(a)).strip() == fold(str(b)).strip()


def _name(g: GoldenRecord) -> str | None:
    fv = g.fields.get("name")
    return str(fv.value) if fv and fv.value else None


def _stale_values(golden: list[GoldenRecord], by_id: dict[str, SourceRecord]):
    """CRM values that disagree with the value Canon kept (from a more authoritative source, or
    a more recent record, including another CRM account), and owner changes only Slack knows."""
    stale, slack_only = [], []
    for g in golden:
        for field in AUDITED_FIELDS:
            fact = g.facts.get(field)
            if fact is None or fact.value is None or not fact.sources:
                continue
            best = fact.sources[0]
            crm_values = [
                (f.value, r.record_id)
                for rid in g.members
                if (r := by_id[rid]).source == "crm" and r.status == "active"
                for f in r.facts
                if f.field == field
            ]
            for value, rid in crm_values:
                if rid != best.record_id and not _same(value, fact.value):
                    item = StaleValue(
                        entity_id=g.entity_id,
                        customer=_name(g),
                        field=field,
                        current=show_value(fact.value),
                        current_source=best.record_id,
                        stale=show_value(value),
                        stale_record=rid,
                        confidence=fact.confidence,
                    )
                    if field == "owner" and all(e.source == "slack" for e in fact.sources):
                        slack_only.append(item)
                    else:
                        stale.append(item)
                    break
    return stale, slack_only


def build_audit(
    records: list[SourceRecord],
    res: Resolution,
    directory=None,
    unreadable: list[ParseIssue] | None = None,
    as_of: date | None = None,
    low_confidence: float = 0.3,
) -> Audit:
    by_id = {r.record_id: r for r in records}
    golden = res.golden
    unreadable = unreadable or []

    # duplicates
    same_source: Counter = Counter()
    for g in golden:
        sources = Counter(by_id[m].source for m in g.members if by_id[m].status != "superseded")
        for source, n in sources.items():
            if n > 1:
                same_source[source] += 1
    largest = sorted(golden, key=lambda g: (-len(g.members), g.entity_id))[:10]

    # conflicts, confidence, staleness
    conflicts: Counter = Counter()
    low: Counter = Counter()
    for g in golden:
        for field, fact in g.facts.items():
            conflicts[field] += fact.conflict
            low[field] += fact.confidence < low_confidence
    stale, slack_only = _stale_values(golden, by_id)

    # quarantine
    issues = [i for r in records for i in r.issues] + list(unreadable)
    held = [i for i in issues if i.severity == "quarantined"]
    warned = [i for i in issues if i.severity == "warning"]
    injections = sum(i.reason.startswith("possible_prompt_injection") for i in issues)

    # permissions
    views = []
    if directory is not None:
        for cid, caller in sorted(directory.callers.items()):
            visible = {r.record_id for r in records if caller.groups & set(r.acl)}
            seen = [g for g in golden if visible & set(g.members)]
            partial = [g for g in seen if not set(g.members) <= visible]
            views.append(
                CallerView(
                    caller=cid,
                    groups=sorted(caller.groups),
                    records_visible=len(visible),
                    customers_visible=len(seen),
                    customers_partial=len(partial),
                )
            )
    by_acl = Counter(", ".join(sorted(r.acl)) or "(nobody)" for r in records)

    findings = _findings(stale, slack_only, same_source, held, unreadable, res, low, injections)
    return Audit(
        as_of=as_of,
        records_by_source=dict(Counter(r.source for r in records)),
        records_by_status=dict(Counter(r.status for r in records)),
        entities=len(golden),
        multi_record_entities=sum(len(g.members) > 1 for g in golden),
        cross_source_entities=sum(len({by_id[m].source for m in g.members}) > 1 for g in golden),
        same_source_duplicates=dict(same_source),
        largest_clusters=[(g.entity_id, _name(g), g.members) for g in largest],
        conflicts_by_field=dict(conflicts),
        low_confidence_by_field=dict(low),
        stale_crm=stale,
        slack_only_owner_changes=slack_only,
        quarantine_by_reason=dict(Counter(i.reason.split(":")[0] for i in held)),
        warnings_by_reason=dict(Counter(i.reason.split(":")[0] for i in warned)),
        quarantine_examples=held[:25],
        review_items=len(res.review),
        review_examples=[i.model_dump() for i in res.review[:10]],
        callers=views,
        records_by_acl=dict(by_acl),
        injections=injections,
        findings=findings,
    )


def _findings(stale, slack_only, same_source, held, unreadable, res, low, injections):
    by_field = Counter(s.field for s in stale)
    found = []
    for field, n in by_field.items():
        examples = [
            f"{s.customer}: CRM says `{s.stale}`, current is `{s.current}` ({s.current_source})"
            for s in stale
            if s.field == field
        ][:3]
        found.append(
            Finding(
                key=f"stale_crm_{field}",
                title=(
                    f"CRM {FIELD_LABELS[field]} disagrees with a more reliable or more recent "
                    "source"
                ),
                count=n,
                weight=3.0 if field in ("contract_value", "renewal_date", "owner") else 1.5,
                who_fixes="Sales ops / CRM admin",
                examples=examples,
            )
        )
    if slack_only:
        found.append(
            Finding(
                key="owner_change_slack_only",
                title="Account owner changed in Slack but not in the CRM",
                count=len(slack_only),
                weight=3.0,
                who_fixes="Account owners / sales ops",
                examples=[
                    f"{s.customer}: CRM `{s.stale}`, Slack says `{s.current}`" for s in slack_only
                ][:3],
            )
        )
    if same_source.get("crm"):
        found.append(
            Finding(
                key="crm_duplicates",
                title="Customers with more than one active CRM account",
                count=same_source["crm"],
                weight=2.0,
                who_fixes="CRM admin (merge accounts)",
            )
        )
    if held:
        reasons = Counter(i.reason.split(":")[0] for i in held).most_common(3)
        found.append(
            Finding(
                key="quarantined_values",
                title="Values that cannot be read safely (ambiguous, malformed or impossible)",
                count=len(held),
                weight=2.0,
                who_fixes="Data owners of each source (fix the field at the source)",
                examples=[f"{r}: {n}" for r, n in reasons],
            )
        )
    if unreadable:
        found.append(
            Finding(
                key="unreadable_documents",
                title="Documents with no readable text (corrupt, encrypted, or scans without OCR)",
                count=len(unreadable),
                weight=2.0,
                who_fixes="Legal / document owners (re-export or rescan)",
                examples=[f"{i.record_id}: {i.reason}" for i in unreadable][:3],
            )
        )
    if res.review:
        found.append(
            Finding(
                key="review_merges",
                title="Borderline duplicate decisions a person should confirm",
                count=len(res.review),
                weight=1.0,
                who_fixes="Account owners (answer in overrides.json)",
                examples=[
                    f"{i.left_name} ~ {i.right_name} ({i.probability:.2f})" for i in res.review
                ][:3],
            )
        )
    weak = sum(low.values())
    if weak:
        found.append(
            Finding(
                key="low_confidence",
                title="Facts Canon could only answer with low confidence (sources disagree)",
                count=weak,
                weight=1.0,
                who_fixes="Sales ops (confirm the current value once)",
            )
        )
    if injections:
        found.append(
            Finding(
                key="prompt_injection",
                title="Source text that reads like instructions to an AI model",
                count=injections,
                weight=3.0,
                who_fixes="Security (review the source; Canon withholds the text)",
            )
        )
    return sorted(found, key=lambda f: (-f.impact, f.key))


def render_audit(a: Audit) -> str:
    total = sum(a.records_by_source.values())
    lines = [
        "# MCP Readiness Audit: findings",
        "",
        f"*Facts as of {a.as_of or 'today'}. Every number below comes from the exported data; the "
        "record ids let you check each one.*",
        "",
        "## 1. Prioritized fix list",
        "",
        "| # | Finding | Count | Impact | Who fixes it |",
        "|---|---|---|---|---|",
    ]
    for i, f in enumerate(a.findings[:10], 1):
        lines.append(f"| {i} | {f.title} | {f.count} | {f.impact:.0f} | {f.who_fixes} |")
    lines += ["", "Examples:", ""]
    for f in a.findings[:10]:
        for ex in f.examples:
            lines.append(f"- *{f.key}*: {ex}")
    lines += [
        "",
        "Impact = count × weight (3 for facts agents are asked about most: contract value, renewal "
        "date, owner; 2 for duplicates and unreadable values; 1 for review items). It is a ranking "
        "aid, not a measured cost.",
        "",
        "## 2. What was ingested",
        "",
        f"{total} source records: "
        + ", ".join(f"{n} {s}" for s, n in sorted(a.records_by_source.items()))
        + " ("
        + ", ".join(f"{n} {s}" for s, n in sorted(a.records_by_status.items()))
        + ").",
        "",
        "## 3. Duplicates",
        "",
        f"- {total} records describe **{a.entities} customers**; {a.multi_record_entities} "
        f"customers appear more than once and {a.cross_source_entities} appear in more than one "
        "system.",
    ]
    for source, n in sorted(a.same_source_duplicates.items()):
        lines.append(f"- {n} customers have more than one live record **inside {source}**.")
    lines += ["", "Largest groups:", "", "| Customer | Records |", "|---|---|"]
    for eid, name, members in a.largest_clusters:
        lines.append(f"| {name or eid} | {len(members)}: {', '.join(members[:6])} |")
    lines += [
        "",
        "## 4. Conflicting and stale facts",
        "",
        "| Field | Customers with conflicting values | Low-confidence answers |",
        "|---|---|---|",
    ]
    for field in sorted(set(a.conflicts_by_field) | set(a.low_confidence_by_field)):
        lines.append(
            f"| {field} | {a.conflicts_by_field.get(field, 0)} | "
            f"{a.low_confidence_by_field.get(field, 0)} |"
        )
    lines += [
        "",
        f"**Stale CRM values** ({len(a.stale_crm)}): the CRM disagrees with the value Canon kept "
        "from a more authoritative or more recent source.",
        "",
        "| Customer | Field | CRM says | Current value | From | Confidence |",
        "|---|---|---|---|---|---|",
    ]
    for s in a.stale_crm[:25]:
        lines.append(
            f"| {s.customer} | {s.field} | {s.stale} | {s.current} | {s.current_source} | "
            f"{s.confidence:.2f} |"
        )
    lines += [
        "",
        f"**Owner changes only Slack knows about** ({len(a.slack_only_owner_changes)}):",
        "",
    ]
    for s in a.slack_only_owner_changes[:25]:
        lines.append(f"- {s.customer}: CRM `{s.stale}` → `{s.current}` ({s.current_source})")
    lines += [
        "",
        "## 5. Values Canon refused to read (quarantine)",
        "",
        "| Reason | Count |",
        "|---|---|",
        *[f"| {r} | {n} |" for r, n in sorted(a.quarantine_by_reason.items(), key=lambda x: -x[1])],
        "",
        "Read under an assumption (kept, flagged): "
        + (", ".join(f"{r} {n}" for r, n in sorted(a.warnings_by_reason.items())) or "none")
        + ".",
        "",
    ]
    if a.quarantine_examples:
        lines += ["| Record | Field | Raw text | Reason |", "|---|---|---|---|"]
        for i in a.quarantine_examples:
            raw = i.raw.replace("|", "/").replace("\n", " ")[:80]
            lines.append(f"| {i.record_id} | {i.field} | `{raw}` | {i.reason} |")
    lines += [
        "",
        "## 6. Merges to confirm",
        "",
        f"{a.review_items} pair decisions are borderline (full list in `review_queue.json`; "
        "answers go in `overrides.json` and are applied on every run).",
        "",
        "| Record | Record | Probability | Decision |",
        "|---|---|---|---|",
    ]
    for r in a.review_examples:
        lines.append(
            f"| {r['left_name']} ({r['left']}) | {r['right_name']} ({r['right']}) | "
            f"{r['probability']:.2f} | {r['decision']} |"
        )
    lines += [
        "",
        "## 7. Permissions",
        "",
        "Who can read which records (as configured; see the caveat below):",
        "",
        "| Readable by | Records |",
        "|---|---|",
        *[f"| {acl} | {n} |" for acl, n in sorted(a.records_by_acl.items())],
    ]
    if a.callers:
        lines += [
            "",
            "| Caller | Groups | Records visible | Customers visible "
            "| Customers seen only in part |",
            "|---|---|---|---|---|",
        ]
        for v in a.callers:
            lines.append(
                f"| {v.caller} | {', '.join(v.groups) or '—'} | {v.records_visible} | "
                f"{v.customers_visible} | {v.customers_partial} |"
            )
    lines += [
        "",
        "A caller who sees a customer only in part gets answers from the sources they may read, "
        "flagged `partial_view`. An agent built on the raw export would read every source for "
        "everyone.",
        "",
        f"Possible prompt injections in source text: **{a.injections}** "
        "(listed in `quarantine.json`).",
        "",
        "## Caveats",
        "",
        "- Permissions are what the export and the role mapping say, not a live read of each "
        "system's sharing settings.",
        '- "Stale" means a more authoritative or more recent source disagrees, using the scoring '
        "rules in `docs/FACT_SCORING.md`. The value Canon keeps can itself be wrong; "
        "low-confidence items are the ones to confirm first.",
        "- Duplicate counts depend on entity resolution; borderline decisions are listed in "
        "section 6.",
    ]
    return "\n".join(lines) + "\n"
