"""Source connectors. Each turns a raw export into `SourceRecord`s."""

from __future__ import annotations

from pathlib import Path

from canon.guard import injection_rule
from canon.ingest.chat import load_teams, load_whatsapp
from canon.ingest.config import IngestConfig
from canon.ingest.contracts import load_contracts
from canon.ingest.crm import load_crm
from canon.ingest.deployment import Deployment, load_deployment
from canon.ingest.slack import load_slack
from canon.models import ParseIssue, SourceRecord


def load_all(
    root: Path,
    config: IngestConfig | None = None,
    unreadable: list[ParseIssue] | None = None,
    deployment: Deployment | None = None,
) -> list[SourceRecord]:
    """Load every known source present under `root` (never reads `ground_truth/`).

    Column names, ACLs and conventions come from `deployment` (default: `<root>/canon.json`);
    an explicit `config` overrides its ingest settings. Documents with no readable text are
    appended to `unreadable` (if given)."""
    root = Path(root)
    dep = deployment or load_deployment(root)
    config = config or dep.ingest
    records: list[SourceRecord] = []
    for path in dep.crm_paths(root):
        records += load_crm(path, fields=dep.crm_fields, acl=dep.crm_acl, config=config)
    if (root / "slack" / "channels.json").exists():
        records += load_slack(root / "slack", config=dep.slack, ingest=config)
    if (root / "teams" / "channels.json").exists():
        records += load_teams(root / "teams", config=dep.teams, ingest=config)
    if (root / "whatsapp").is_dir():
        records += load_whatsapp(root / "whatsapp", config=dep.whatsapp, ingest=config)
    if (root / "contracts").is_dir():
        records += load_contracts(
            root / "contracts", acl=dep.contract_acl, config=config, unreadable=unreadable
        )
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


__all__ = [
    "Deployment",
    "IngestConfig",
    "load_all",
    "load_contracts",
    "load_crm",
    "load_deployment",
    "load_slack",
]
