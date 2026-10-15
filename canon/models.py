"""Source-agnostic data model shared by every Canon stage."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal["crm", "slack", "contract", "email"]
RecordStatus = Literal["active", "archived", "superseded"]


class Fact(BaseModel):
    """A single dated assertion a source makes about an entity."""

    field: str
    value: str | float | int
    observed_at: date | None = None
    record_id: str


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

    def all_names(self) -> list[str]:
        names = [self.name] if self.name else []
        return names + [n for n in self.alt_names if n and n != self.name]


class FieldValue(BaseModel):
    """A golden-record field: the surviving value plus why and from where."""

    value: str | float | int | None
    record_ids: list[str] = Field(default_factory=list)
    rule: str


class GoldenRecord(BaseModel):
    entity_id: str
    fields: dict[str, FieldValue]
    members: list[str] = Field(description="Lineage: every source record merged into this entity")
    acl: list[str] = Field(default_factory=list)
