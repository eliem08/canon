"""Chat connectors beyond Slack: WhatsApp chat exports and Microsoft Teams channel exports.

Both are converted to the Slack connector's channel/message shape and go through the same fact
extraction, message-level citations and scoring (`slack.channel_to_record`); records keep source
"slack" (team chat) and carry the platform in their ids: `whatsapp:<id>`, `teams:<id>`.

Permissions, privacy first:
- a WhatsApp chat is readable by its participants only (`whatsapp-user:<phone or name>`), unless
  the deployment file gives it groups (`"whatsapp": {"acl": [...]}`);
- a private or shared Teams channel is readable by its members (`teams-user:<id>`); a standard
  channel by the configured groups, like a public Slack channel.
Callers carry these principals through `chat_ids` in the identities file.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from canon.ingest.config import IngestConfig
from canon.ingest.extract import TextModel
from canon.ingest.parsing import infer_dayfirst, parse_phone
from canon.ingest.slack import SlackConfig, channel_to_record
from canon.models import ParseIssue, SourceRecord


@dataclass(frozen=True)
class WhatsAppConfig:
    chat: SlackConfig = field(default_factory=SlackConfig)
    acl: tuple[str, ...] | None = None  # None = participants only
    chat_title_prefixes: tuple[str, ...] = (
        "whatsapp chat with",
        "whatsapp chat -",
        "discussion whatsapp avec",
        "conversation whatsapp avec",
        "whatsapp chat",
    )


def _slug(text: str) -> str:
    folded = text.lower().replace("_", " ")
    return re.sub(r"-+", "-", re.sub(r"[^\w]+", "-", folded, flags=re.UNICODE)).strip("-")


def _chat_id(platform: str, key: str) -> str:
    return hashlib.sha1(f"{platform}:{key}".encode()).hexdigest()[:10].upper()


# ---------------------------------------------------------------- WhatsApp

# iOS:     [17/03/2026, 14:05:12] Omar Fassi: message
# Android: 17/03/2026, 14:05 - Omar Fassi: message      (US phones: 3/17/26, 2:05 PM - ...)
_WA_LINE = re.compile(
    r"^[‎‏]?\[?(?P<d>\d{1,2})[/.](?P<m>\d{1,2})[/.](?P<y>\d{2}|\d{4}),?\s+"
    r"(?P<H>\d{1,2}):(?P<M>\d{2})(?::(?P<S>\d{2}))?\s*(?P<ampm>[AaPp]\.?\s?[Mm]\.?)?\]?\s*"
    r"(?:[-–]\s*)?(?P<rest>.*)$"
)
_WA_SENDER = re.compile(r"^(?P<who>[^:]{1,80}?):\s(?P<text>.*)$", re.S)
_WA_MEDIA = re.compile(
    r"^[‎]?(?:<attached: [^>]+>|<media omitted>|(?:image|video|audio|sticker|document|GIF) "
    r"omitted|<médias omis>|image absente)$",
    re.I,
)


def _wa_principal(sender: str, ingest: IngestConfig) -> str:
    phone = parse_phone(sender, ingest.default_country)
    return phone.value if phone.ok else " ".join(sender.lower().split())


def parse_whatsapp(text: str, ingest: IngestConfig | None = None) -> tuple[list[dict], list[str]]:
    """Messages as {"ts", "user", "text"} and the issues found (unreadable timestamps).

    Day/month order comes from the deployment (`ingest.dayfirst`), else is inferred from the
    file's own dates. Two-digit years are WhatsApp's export format and are read as 20yy."""
    ingest = ingest or IngestConfig()
    lines = text.replace("\r\n", "\n").split("\n")
    heads = [(i, m) for i, line in enumerate(lines) if (m := _WA_LINE.match(line))]
    dayfirst = ingest.dayfirst
    if dayfirst is None:
        years = [m["y"] if len(m["y"]) == 4 else f"20{m['y']}" for _, m in heads]
        inferred, _ = infer_dayfirst(
            [f"{m['d']}/{m['m']}/{y}" for (_, m), y in zip(heads, years, strict=True)]
        )
        dayfirst = inferred is not False
    messages, issues = [], []
    starts = [i for i, _ in heads] + [len(lines)]
    for (i, m), end in zip(heads, starts[1:], strict=True):
        body = "\n".join([m["rest"], *lines[i + 1 : end]]).strip()
        sender = _WA_SENDER.match(body)
        if not sender:
            continue  # system line: "Messages are end-to-end encrypted", "X added Y"
        a, b = int(m["d"]), int(m["m"])
        day, month = (a, b) if dayfirst else (b, a)
        year = int(m["y"]) + (2000 if len(m["y"]) == 2 else 0)
        hour = int(m["H"])
        if m["ampm"]:  # 12 AM = 0h, 12 PM = 12h
            hour = hour % 12 + (12 if m["ampm"].lower().startswith("p") else 0)
        try:
            when = datetime(year, month, day, hour, int(m["M"]), int(m["S"] or 0), tzinfo=UTC)
        except ValueError:
            issues.append(lines[i][:120])
            continue
        content = sender["text"].replace("‎", "").strip()
        if not content or _WA_MEDIA.match(content):
            continue
        messages.append(
            {"ts": f"{when.timestamp():.0f}", "user": sender["who"].strip(), "text": content}
        )
    return messages, issues


def _whatsapp_title(path: Path, prefixes: tuple[str, ...]) -> str:
    stem = path.parent.name if path.name.lower() == "_chat.txt" else path.stem
    low = stem.lower()
    for p in prefixes:
        if low.startswith(p):
            return stem[len(p) :].strip(" -_")
    return stem


def load_whatsapp(
    root: Path,
    config: WhatsAppConfig | None = None,
    ingest: IngestConfig | None = None,
    llm: TextModel | None = None,
) -> list[SourceRecord]:
    """Every `*.txt` chat export under `root` (a `<chat>/_chat.txt` folder works too)."""
    config = config or WhatsAppConfig()
    ingest = ingest or IngestConfig()
    root = Path(root)
    records = []
    for path in sorted(p for p in root.rglob("*.txt") if p.is_file() and not p.is_symlink()):
        rel = path.relative_to(root).as_posix()
        title = _whatsapp_title(path, config.chat_title_prefixes)
        messages, bad = parse_whatsapp(path.read_text(encoding="utf-8-sig"), ingest)
        members = sorted({_wa_principal(m["user"], ingest) for m in messages})
        channel = {
            "id": _chat_id("whatsapp", rel),
            "name": _slug(title) or "chat",
            "is_private": config.acl is None,
            "members": members,
        }
        chat_config = replace(config.chat, acl=config.acl or config.chat.acl)
        users = {m["user"]: m["user"] for m in messages}
        rec = channel_to_record(
            channel, messages, users, chat_config, f"whatsapp/{rel}", ingest, llm, "whatsapp"
        )
        rec.locator = f"whatsapp/{rel}"
        for f in rec.facts:
            f.source_ref = f.source_ref.replace(f"/{channel['name']}#", "#")
        rec.issues += [
            ParseIssue(
                record_id=rec.record_id, field="message", raw=b, reason="unreadable_timestamp"
            )
            for b in bad
        ]
        records.append(rec)
    return records


# ---------------------------------------------------------------- Microsoft Teams

_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</?(?:p|div|br|li)[^>]*>", re.I)


def teams_text(body: dict) -> str:
    content = (body or {}).get("content") or ""
    if (body or {}).get("contentType", "html").lower() == "html":
        content = _TAG.sub("", _BLOCK.sub("\n", content))  # <at id="0">Omar</at> -> Omar
        content = html.unescape(content).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", content)).strip()


def _graph_messages(folder: Path) -> list[dict]:
    out = []
    for page in sorted(folder.glob("*.json")):
        data = json.loads(page.read_text(encoding="utf-8"))
        out += data.get("value", []) if isinstance(data, dict) else data
    return out


def load_teams(
    root: Path,
    config: SlackConfig | None = None,
    ingest: IngestConfig | None = None,
    llm: TextModel | None = None,
) -> list[SourceRecord]:
    """A Teams export in Microsoft Graph shape: `teams/channels.json` lists channels
    (id, displayName, membershipType, members, isArchived) and `teams/<channel id>/*.json` holds
    pages of `chatMessage` objects (`{"value": [...]}` or a plain list)."""
    config = config or SlackConfig()
    root = Path(root)
    channels = json.loads((root / "channels.json").read_text(encoding="utf-8"))
    records = []
    for ch in channels:
        cid = str(ch.get("id", ""))
        folder = root / cid
        if not cid or folder.resolve().parent != root.resolve():
            raise ValueError(f"unsafe Teams channel id in export: {cid!r}")
        raw = _graph_messages(folder) if folder.is_dir() else []
        users, messages = {}, []
        for msg in raw:
            if msg.get("messageType", "message") != "message" or msg.get("deletedDateTime"):
                continue
            who = ((msg.get("from") or {}).get("user") or {}).get("displayName") or ""
            text = teams_text(msg.get("body") or {})
            created = msg.get("createdDateTime")
            if not text or not created:
                continue
            when = datetime.fromisoformat(created.replace("Z", "+00:00"))
            users[who] = who
            messages.append({"ts": f"{when.timestamp():.0f}", "user": who, "text": text})
        messages.sort(key=lambda m: float(m["ts"]))
        members = [
            m.get("userId") or m.get("id") for m in ch.get("members", []) if isinstance(m, dict)
        ] + [m for m in ch.get("members", []) if isinstance(m, str)]
        channel = {
            "id": _chat_id("teams", cid),
            "name": _slug(ch.get("displayName") or cid),
            "is_private": ch.get("membershipType", "standard") in ("private", "shared"),
            "is_archived": bool(ch.get("isArchived")),
            "members": [m for m in members if m],
            "purpose": {"value": ch.get("description") or ""},
        }
        records.append(
            channel_to_record(channel, messages, users, config, "teams", ingest, llm, "teams")
        )
    return records
