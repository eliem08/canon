"""Source-agnostic data model shared by every Canon stage."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal["crm", "slack", "contract", "email", "confirmed"]  # confirmed: by a person
RecordStatus = Literal["active", "archived", "superseded"]


class Fact(BaseModel):
    """A single dated assertion a source makes about an entity."""

    field: str
    value: str | float | int
    observed_at: date | None = None
    valid_until: date | None = Field(
        default=None, description="End of the period the source asserts it for (e.g. contract term)"
    )
    record_id: str
    source_ref: str | None = Field(
        default=None, description="Where inside the record: message ts, file page/line, CRM row"
    )
    quote: str | None = Field(default=None, description="The source text the value was read from")


class ParseIssue(BaseModel):
    """A value a connector refused to interpret (quarantined) or read under an assumption.

    Quarantined values produce no `Fact`; the raw text is kept so a human can resolve it."""

    record_id: str
    field: str
    raw: str
    reason: str  # machine-readable code, e.g. "ambiguous_separator", "impossible_date"
    severity: Literal["quarantined", "warning"] = "quarantined"


class SourceRecord(BaseModel):
    """One mention of an entity in one source, normalized to a common shape.

    Identity attributes (name, domain, phone, ...) drive entity resolution;
    `facts` carry the business values (owner, contract value, ...) that later
    milestones score and serve.
    """

    record_id: str
    source: SourceType
    locator: str = Field(description="Where the record came from (file path, channel, ...)")
    name: str | None = None
    alt_names: list[str] = Field(default_factory=list)
    parties: list[str] = Field(
        default_factory=list, description="Every party a contract names, the record's own included"
    )
    domain: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    city: str | None = None
    tax_id: str | None = None
    status: RecordStatus = "active"
    updated_at: date | None = None
    facts: list[Fact] = Field(default_factory=list)
    acl: list[str] = Field(default_factory=list)
    issues: list[ParseIssue] = Field(default_factory=list)

    def all_names(self) -> list[str]:
        names = [self.name] if self.name else []
        return names + [n for n in self.alt_names if n and n != self.name]


class FieldValue(BaseModel):
    """A golden-record field: the surviving value plus why and from where."""

    value: str | float | int | None
    record_ids: list[str] = Field(default_factory=list)
    rule: str


class Evidence(BaseModel):
    """One source observation of a fact value, with the weights that scored it."""

    record_id: str
    source: SourceType
    status: RecordStatus
    value: str | float | int
    observed_at: date | None
    authority: float
    freshness: float
    weight: float  # authority x freshness, in [0, 1]
    acl: list[str] = Field(default_factory=list)
    source_ref: str | None = None
    quote: str | None = None


class ScoredValue(BaseModel):
    value: str | float | int
    score: float  # noisy-OR of supporting evidence weights
    last_updated: date | None
    sources: list[Evidence]


class ResolvedFact(BaseModel):
    """The winning value of one field plus every losing value kept as an alternative."""

    field: str
    value: str | float | int | None
    confidence: float
    last_updated: date | None
    sources: list[Evidence] = Field(default_factory=list)
    alternatives: list[ScoredValue] = Field(default_factory=list)
    conflict: bool = False
    explanation: str = ""


class GoldenRecord(BaseModel):
    entity_id: str
    fields: dict[str, FieldValue]
    members: list[str] = Field(description="Lineage: every source record merged into this entity")
    acl: list[str] = Field(default_factory=list)
    facts: dict[str, ResolvedFact] = Field(default_factory=dict)
