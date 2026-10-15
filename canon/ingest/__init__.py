"""Source connectors. Each turns a raw export into `SourceRecord`s."""

from __future__ import annotations

from pathlib import Path

from canon.ingest.contracts import load_contracts
from canon.ingest.crm import load_crm
from canon.ingest.slack import load_slack
from canon.models import SourceRecord


def load_all(root: Path) -> list[SourceRecord]:
    """Load every known source present under `root` (never reads `ground_truth/`)."""
    root = Path(root)
    records: list[SourceRecord] = []
    if (root / "crm" / "accounts.json").exists():
        records += load_crm(root / "crm" / "accounts.json")
    if (root / "slack" / "channels.json").exists():
        records += load_slack(root / "slack")
    if (root / "contracts").is_dir():
        records += load_contracts(root / "contracts")
    return records


__all__ = ["load_all", "load_contracts", "load_crm", "load_slack"]
