"""Source connectors. Each turns a raw export into `SourceRecord`s."""

from __future__ import annotations

from pathlib import Path

from canon.ingest.config import IngestConfig
from canon.ingest.contracts import load_contracts
from canon.ingest.crm import load_crm
from canon.ingest.slack import load_slack
from canon.models import SourceRecord


def load_all(root: Path, config: IngestConfig | None = None) -> list[SourceRecord]:
    """Load every known source present under `root` (never reads `ground_truth/`)."""
    root = Path(root)
    records: list[SourceRecord] = []
    if (root / "crm" / "accounts.json").exists():
        records += load_crm(root / "crm" / "accounts.json", config=config)
    if (root / "slack" / "channels.json").exists():
        records += load_slack(root / "slack", ingest=config)
    if (root / "contracts").is_dir():
        records += load_contracts(root / "contracts", config=config)
    return records


__all__ = ["IngestConfig", "load_all", "load_contracts", "load_crm", "load_slack"]
