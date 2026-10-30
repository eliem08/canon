"""Per-deployment ingestion conventions (nothing client-specific is hard-coded in connectors)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IngestConfig:
    default_country: str | None = "1"  # calling code for national numbers (US/Canada by default)
    currency: str | None = "USD"  # facts carry no currency: other currencies are quarantined
    dayfirst: bool | None = None  # numeric date order; None = infer per file, else day-first
    century: int | None = None  # read two-digit years (20/03/18) in this century; None = refuse
    # the deployment's own legal names: in a contract between "us" and a customer, the party that
    # is not one of these is the customer. Empty = the customer is only read from a "Client:" line.
    own_names: tuple[str, ...] = ()
