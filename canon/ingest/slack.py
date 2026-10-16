"""Slack workspace export connector.

One `SourceRecord` per account channel. The channel name (minus a configurable
prefix such as `client-` or `old-`) and its purpose give the entity's informal
name; message text yields contact e-mails/phones and dated facts (owner,
contract value, renewal date) via multilingual (FR/EN/Darija) cue patterns.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from canon.ingest.common import business_domain, date_from_ts, find_emails, find_phones
from canon.ingest.config import IngestConfig
from canon.ingest.parsing import IssueLog, parse_amount, parse_date
from canon.models import Fact, SourceRecord


@dataclass(frozen=True)
class SlackConfig:
    channel_prefixes: tuple[str, ...] = ("client", "acc", "deal", "ext", "old", "cust", "account")
    purpose_prefixes: tuple[str, ...] = ("suivi compte", "account channel for", "compte")
    owner_cues: tuple[str, ...] = ("owner", "reprend le compte", "responsable du compte")
    value_cues: tuple[str, ...] = ("montant", "deal", "contrat", "contract", "par an", "/an")
    renewal_cues: tuple[str, ...] = ("renouvellement", "renewal")
    acl: tuple[str, ...] = ("sales",)
    archived_acl: tuple[str, ...] = ("sales",)


USER_MENTION_RE = re.compile(r"<@(U\w+)>")


def load_slack(
    root: Path, config: SlackConfig | None = None, ingest: IngestConfig | None = None
) -> list[SourceRecord]:
    config = config or SlackConfig()
    root = Path(root)
    users = {
        u["id"]: u.get("real_name") or u.get("name")
        for u in json.loads((root / "users.json").read_text(encoding="utf-8"))
    }
    channels = json.loads((root / "channels.json").read_text(encoding="utf-8"))
    records = []
    for channel in channels:
        messages = []
        for day_file in sorted((root / channel["name"]).glob("*.json")):
            messages.extend(json.loads(day_file.read_text(encoding="utf-8")))
        messages.sort(key=lambda m: float(m["ts"]))
        records.append(channel_to_record(channel, messages, users, config, str(root), ingest))
    return records


def humanize_channel(name: str, prefixes: tuple[str, ...]) -> str:
    parts = name.split("-")
    if len(parts) > 1 and parts[0] in prefixes:
        parts = parts[1:]
    return " ".join(parts)


def _strip_prefix(text: str, prefixes: tuple[str, ...]) -> str:
    low = text.lower()
    for p in prefixes:
        if low.startswith(p):
            return text[len(p) :].strip(" :-")
    return text


def channel_to_record(
    channel: dict,
    messages: list[dict],
    users: dict[str, str],
    config: SlackConfig,
    locator: str,
    ingest: IngestConfig | None = None,
) -> SourceRecord:
    ingest = ingest or IngestConfig()
    dayfirst = ingest.dayfirst is not False
    rid = f"slack:{channel['id']}"
    log = IssueLog(rid)
    archived = bool(channel.get("is_archived"))
    purpose = (channel.get("purpose") or {}).get("value") or ""
    alt = [_strip_prefix(purpose, config.purpose_prefixes)] if purpose else []
    emails, phones, facts = [], [], []
    for msg in messages:
        text = msg.get("text", "")
        when = date_from_ts(msg["ts"])
        low = text.lower()
        emails += find_emails(text)
        phones += find_phones(text, ingest.default_country)
        mention = USER_MENTION_RE.search(text)
        if mention and any(c in low for c in config.owner_cues):
            owner = users.get(mention.group(1))
            if owner:
                facts.append(Fact(field="owner", value=owner, observed_at=when, record_id=rid))
        elif any(c in low for c in config.renewal_cues):
            renewal = log.take("renewal_date", parse_date(text, dayfirst=dayfirst))
            if renewal:
                facts.append(
                    Fact(
                        field="renewal_date",
                        value=renewal.isoformat(),
                        observed_at=when,
                        record_id=rid,
                    )
                )
        elif any(c in low for c in config.value_cues):
            amount = log.take(
                "contract_value",
                parse_amount(text, expected_currency=ingest.currency, require_marker=True),
            )
            if amount:
                facts.append(
                    Fact(
                        field="contract_value", value=amount.value, observed_at=when, record_id=rid
                    )
                )
    domains = [d for d in (business_domain(e) for e in emails) if d]
    last = date_from_ts(messages[-1]["ts"]) if messages else None
    return SourceRecord(
        record_id=rid,
        source="slack",
        locator=f"{locator}/{channel['name']}",
        name=humanize_channel(channel["name"], config.channel_prefixes),
        alt_names=alt,
        domain=domains[0] if domains else None,
        phone=phones[0] if phones else None,
        email=emails[0] if emails else None,
        status="archived" if archived else "active",
        updated_at=last,
        facts=facts,
        acl=list(config.archived_acl if archived else config.acl),
        issues=log.items,
    )
