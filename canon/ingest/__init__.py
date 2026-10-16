"""Source connectors. Each turns a raw export into `SourceRecord`s."""

from __future__ import annotations

from pathlib import Path

from canon.guard import injection_rule
from canon.ingest.config import IngestConfig
from canon.ingest.contracts import load_contracts
from canon.ingest.crm import load_crm
from canon.ingest.slack import load_slack
from canon.models import ParseIssue, SourceRecord


def load_all(
    root: Path, config: IngestConfig | None = None, unreadable: list[ParseIssue] | None = None
) -> list[SourceRecord]:
    """Load every known source present under `root` (never reads `ground_truth/`).

    Documents with no readable text are appended to `unreadable` (if given)."""
    root = Path(root)
    records: list[SourceRecord] = []
    for name in ("accounts.json", "accounts.csv", "accounts.xlsx"):
        if (root / "crm" / name).exists():
            records += load_crm(root / "crm" / name, config=config)
    if (root / "slack" / "channels.json").exists():
        records += load_slack(root / "slack", ingest=config)
    if (root / "contracts").is_dir():
        records += load_contracts(root / "contracts", config=config, unreadable=unreadable)
    for r in records:
        flag_injections(r)
    return records


def flag_injections(record: SourceRecord) -> None:
    """Warn (in the quarantine report) about source text that reads like instructions to a model.
    The value is still ingested; the MCP server withholds the text when it would return it."""
    texts = [("name", n) for n in record.all_names()] + [("address", record.address)]
    texts += [(f.field, f.quote or f.value) for f in record.facts]
    for field, text in texts:
        rule = injection_rule(text)
        if rule:
            record.issues.append(
                ParseIssue(
                    record_id=record.record_id,
                    field=field,
                    raw=str(text)[:300],
                    reason=f"possible_prompt_injection:{rule}",
                    severity="warning",
                )
            )


__all__ = ["IngestConfig", "load_all", "load_contracts", "load_crm", "load_slack"]
