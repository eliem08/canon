"""Email connector: `.eml` files and `.mbox` mailboxes under `<data>/email/`.

One `SourceRecord` per customer domain (all the messages exchanged with `harborfoods.com`), the way
the Slack connector makes one record per account channel. The domain links it to the CRM account's
website; facts (contract value, renewal date, owner) come from each message body via
`canon.ingest.extract` and cite the message (`file#<Message-ID>`), dated by its `Date:` header.

Three rules keep it from guessing:
- quoted replies and forwarded history are cut before reading a body, so an old price quoted in
  today's reply is not dated today;
- contact details (phone numbers) are read only from messages the customer sent, so our own
  signatures are never attributed to a customer;
- our own domains must be known (`email.own_domains` in `canon.json`), or be obvious: one domain
  on at least 90% of messages and clearly ahead of the next. Otherwise the mailbox is refused
  with a reason, not guessed.
Free-mail addresses (gmail, outlook...) cannot be tied to a company and are skipped.
"""

from __future__ import annotations

import mailbox
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

from canon.ingest.common import business_domain, find_phones
from canon.ingest.config import IngestConfig
from canon.ingest.extract import ExtractionRules, TextModel, extract_message
from canon.ingest.parsing import IssueLog
from canon.models import Fact, ParseIssue, SourceRecord

OWN_DOMAIN_SHARE = 0.9  # one domain on this share of messages is the mailbox owner's

# where quoted history starts: "On Tue, Mar 3, 2026 at 10:00 Jane <j@x.com> wrote:",
# "Le ... a écrit :", Outlook's "-----Original Message-----" / "From: ... Sent: ...", and
# forwarded-message banners
_QUOTE_START = re.compile(
    r"^(?:On .{0,200}wrote:\s*$|Le .{0,200}a écrit\s*:\s*$|-{2,}\s*Original Message\s*-{2,}"
    r"|-{2,}\s*Forwarded message\s*-{2,}|From:\s.+$)",
    re.I | re.M,
)


@dataclass(frozen=True)
class EmailConfig:
    own_domains: tuple[str, ...] = ()  # our company's domains; empty = infer if obvious
    acl: tuple[str, ...] = ("sales", "exec")
    rules: ExtractionRules = field(default_factory=ExtractionRules)


def fresh_text(body: str) -> str:
    """The part of a message its sender wrote: quoted lines and quoted history removed."""
    m = _QUOTE_START.search(body)
    if m:
        body = body[: m.start()]
    return "\n".join(line for line in body.splitlines() if not line.lstrip().startswith(">"))


def _html_text(markup: str) -> str:
    """Visible text of an HTML body, one line per block (quoted <blockquote> history dropped)."""
    from html.parser import HTMLParser

    class _Text(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.out: list[str] = []
            self.skip = 0  # inside <script>, <style> or a quoted <blockquote>

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "blockquote"):
                self.skip += 1
            elif tag in ("br", "p", "div", "tr", "li"):
                self.out.append("\n")

        def handle_endtag(self, tag):
            if tag in ("script", "style", "blockquote"):
                self.skip = max(0, self.skip - 1)

        def handle_data(self, data):
            if not self.skip:
                self.out.append(data)

    parser = _Text()
    parser.feed(markup)
    return "".join(parser.out)


def _body(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html")) if msg.is_multipart() else msg
    if part is None:
        return ""
    try:
        text = part.get_content()
    except (LookupError, UnicodeDecodeError):  # unknown charset
        text = part.get_payload(decode=True).decode("utf-8", "replace")
    return _html_text(text) if part.get_content_subtype() == "html" else text


def _messages(root: Path) -> list[tuple[str, EmailMessage]]:
    """(locator, message) for every .eml file and every message of every .mbox file."""
    out = []
    for path in sorted(Path(root).rglob("*")):
        if path.suffix.lower() == ".eml":
            with path.open("rb") as fh:
                out.append((path.as_posix(), BytesParser(policy=policy.default).parse(fh)))
        elif path.suffix.lower() == ".mbox":
            box = mailbox.mbox(path, factory=None, create=False)
            for raw in box:
                msg = BytesParser(policy=policy.default).parsebytes(raw.as_bytes())
                out.append((path.as_posix(), msg))
    return out


def _addresses(msg: EmailMessage, *headers: str) -> list[tuple[str, str]]:
    values = [str(v) for h in headers for v in (msg.get_all(h) or [])]
    return [(name, addr.lower()) for name, addr in getaddresses(values) if "@" in addr]


def _domain(addr: str) -> str:
    return addr.rsplit("@", 1)[1]


def own_domains(messages: list[tuple[str, EmailMessage]], configured: tuple[str, ...]):
    """The mailbox owner's domains: configured, or the one domain on >= 90% of messages."""
    if configured:
        return {d.lower() for d in configured}
    seen = Counter()
    for _, msg in messages:
        seen.update({_domain(a) for _, a in _addresses(msg, "From", "To", "Cc")})
    if not messages or not seen:
        return None
    top = seen.most_common(2)
    domain, n = top[0]
    runner_up = top[1][1] if len(top) > 1 else 0
    # obvious = on nearly every message and clearly ahead (a one-customer mailbox is ambiguous)
    obvious = n >= OWN_DOMAIN_SHARE * len(messages) and runner_up < OWN_DOMAIN_SHARE * n
    return {domain} if obvious else None


def _label(domain: str) -> str:
    """'harbor-foods.com' -> 'harbor foods' (a weak name; the domain is the real link)."""
    return domain.split(".")[0].replace("-", " ")


def load_email(
    root: Path,
    config: EmailConfig | None = None,
    ingest: IngestConfig | None = None,
    llm: TextModel | None = None,
    unreadable: list[ParseIssue] | None = None,
) -> list[SourceRecord]:
    config = config or EmailConfig()
    ingest = ingest or IngestConfig()
    dayfirst = ingest.dayfirst is not False
    messages = _messages(root)
    ours = own_domains(messages, config.own_domains)
    if ours is None:
        if unreadable is not None and messages:
            unreadable.append(
                ParseIssue(
                    record_id=f"email:{Path(root).name}",
                    field="own_domains",
                    raw=f"{len(messages)} messages",
                    reason="own_domain_unknown",
                )
            )
        return []
    # internal people, for "Jordan is taking over" style owner statements
    users = {
        a: (name or a.split("@")[0])
        for _, msg in messages
        for name, a in _addresses(msg, "From", "To", "Cc")
        if _domain(a) in ours
    }
    by_domain: dict[str, list[tuple[str, EmailMessage]]] = defaultdict(list)
    for loc, msg in messages:
        external = {
            d
            for d in (business_domain(a) for _, a in _addresses(msg, "From", "To", "Cc"))
            if d and d not in ours
        }
        for d in external:
            by_domain[d].append((loc, msg))
    records = []
    for domain, items in sorted(by_domain.items()):
        rid = f"email:{domain}"
        log = IssueLog(rid)
        facts, phones, contacts, names = [], [], [], []
        last: date | None = None
        for loc, msg in items:
            when = _date(msg)
            last = max(filter(None, [last, when]), default=None)
            text = fresh_text(_body(msg))
            sender = _addresses(msg, "From")
            from_customer = bool(sender) and _domain(sender[0][1]) == domain
            if from_customer:
                phones += find_phones(text, ingest.default_country)
                contacts.append(sender[0][1])
                names += [n for n, a in sender if n]
            ref = f"{loc}#{(msg.get('Message-ID') or '').strip('<> ')}"
            # an email is several statements (and a signature): read it line by line, so a phone
            # number in the signature does not make a stated amount ambiguous
            lines = [ln for ln in text.splitlines() if ln.strip()]
            found = [
                e
                for ln in lines
                for e in extract_message(
                    ln, users, log, ingest.currency, dayfirst, config.rules, llm
                )
            ]
            for e in found:
                facts.append(
                    Fact(field=e.field, value=e.value, observed_at=when, record_id=rid,
                         source_ref=ref, quote=e.quote)
                )  # fmt: skip
        records.append(
            SourceRecord(
                record_id=rid,
                source="email",
                locator=f"{Path(root).as_posix()}/{domain}",
                name=_label(domain),
                domain=domain,
                email=contacts[0] if contacts else None,
                phone=phones[0] if phones else None,
                updated_at=last,
                facts=facts,
                acl=list(config.acl),
                issues=log.items,
            )
        )
    return records


def _date(msg: EmailMessage) -> date | None:
    try:
        return parsedate_to_datetime(str(msg["Date"])).date() if msg["Date"] else None
    except (TypeError, ValueError):
        return None
