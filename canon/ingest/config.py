"""Per-deployment ingestion conventions (nothing client-specific is hard-coded in connectors)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IngestConfig:
    default_country: str | None = "212"  # calling code for national phone numbers ("0522...")
    currency: str | None = "MAD"  # facts carry no currency: other currencies are quarantined
    dayfirst: bool | None = None  # numeric date order; None = infer per file, else day-first
    # the deployment's own legal names: in a contract between "us" and a customer, the party that
    # is not one of these is the customer. Empty = the customer is only read from a "Client:" line.
    own_names: tuple[str, ...] = ()
