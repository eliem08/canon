"""Per-client deployment file: `<data>/canon.json`.

Everything that differs between two clients' exports (CRM column names, which file is the CRM,
who may read each source, currency and phone conventions) is set here, so a new deployment is a
config file, not a code change. Every key is optional; a missing file means the defaults.

    {
      "ingest":    {"default_country": "212", "currency": "MAD", "dayfirst": null},
      "crm":       {"file": "crm/companies.csv", "acl": ["sales", "exec"],
                    "columns": {"name": "Company name", "owner": "Company owner"}},
      "slack":     {"acl": ["sales"], "archived_acl": ["sales"], "channel_prefixes": ["client"]},
      "contracts": {"acl": ["legal", "exec"]}
    }

Unknown keys are an error: a typo in a column mapping must not silently fall back to a default.
`canon check` writes a suggested file to start from.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

from canon.ingest.config import IngestConfig
from canon.ingest.contracts import DEFAULT_CONTRACT_ACL
from canon.ingest.crm import DEFAULT_CRM_ACL, CRMFieldMap
from canon.ingest.slack import SlackConfig

DEPLOYMENT_FILE = "canon.json"
CRM_FILES = ("crm/accounts.json", "crm/accounts.csv", "crm/accounts.xlsx")


@dataclass(frozen=True)
class Deployment:
    ingest: IngestConfig = field(default_factory=IngestConfig)
    crm_file: str | None = None  # relative to the data dir; None = crm/accounts.{json,csv,xlsx}
    crm_fields: CRMFieldMap = field(default_factory=CRMFieldMap)
    crm_acl: tuple[str, ...] = DEFAULT_CRM_ACL
    slack: SlackConfig = field(default_factory=SlackConfig)
    contract_acl: tuple[str, ...] = tuple(DEFAULT_CONTRACT_ACL)

    def crm_paths(self, root: Path) -> list[Path]:
        if self.crm_file:
            path = Path(root) / self.crm_file
            if not path.is_file():
                raise ValueError(f"{DEPLOYMENT_FILE}: crm.file {self.crm_file!r} does not exist")
            return [path]
        return [Path(root) / name for name in CRM_FILES if (Path(root) / name).exists()]


def _check_keys(section: str, given: dict, allowed: set[str]) -> None:
    unknown = sorted(set(given) - allowed)
    if unknown:
        raise ValueError(f"{DEPLOYMENT_FILE}: unknown key(s) in {section}: {', '.join(unknown)}")


def _acl(section: str, value) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ValueError(f"{DEPLOYMENT_FILE}: {section}.acl must be a list of group names")
    return tuple(value)


def parse_deployment(data: dict) -> Deployment:
    _check_keys("the top level", data, {"ingest", "crm", "slack", "contracts"})
    dep = Deployment()
    ingest = data.get("ingest", {})
    _check_keys("ingest", ingest, {f.name for f in fields(IngestConfig)})
    dep = replace(dep, ingest=replace(dep.ingest, **ingest))

    crm = data.get("crm", {})
    _check_keys("crm", crm, {"file", "acl", "columns"})
    columns = crm.get("columns", {})
    _check_keys("crm.columns", columns, {f.name for f in fields(CRMFieldMap)})
    if not all(isinstance(v, str) and v for v in columns.values()):
        raise ValueError(f"{DEPLOYMENT_FILE}: crm.columns values must be column names")
    dep = replace(dep, crm_file=crm.get("file"), crm_fields=CRMFieldMap(**columns))
    if "acl" in crm:
        dep = replace(dep, crm_acl=_acl("crm", crm["acl"]))

    slack = data.get("slack", {})
    _check_keys("slack", slack, {"acl", "archived_acl", "channel_prefixes"})
    overrides = {k: _acl(f"slack.{k}", v) for k, v in slack.items() if k != "channel_prefixes"}
    if "channel_prefixes" in slack:
        overrides["channel_prefixes"] = tuple(slack["channel_prefixes"])
    dep = replace(dep, slack=replace(dep.slack, **overrides))

    contracts = data.get("contracts", {})
    _check_keys("contracts", contracts, {"acl"})
    if "acl" in contracts:
        dep = replace(dep, contract_acl=_acl("contracts", contracts["acl"]))
    return dep


def load_deployment(root: Path) -> Deployment:
    path = Path(root) / DEPLOYMENT_FILE
    if not path.exists():
        return Deployment()
    return parse_deployment(json.loads(path.read_text(encoding="utf-8")))
