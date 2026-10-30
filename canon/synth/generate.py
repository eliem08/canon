"""Seeded generator for Canon's synthetic messy dataset.

Layout written under the output directory:

    crm/accounts.json                 Salesforce-like account export
    slack/users.json                  Slack workspace export (users, channels,
    slack/channels.json               one folder per channel, one file per day)
    slack/<channel>/<YYYY-MM-DD>.json
    contracts/<number>_v<k>.txt       text extracted from contract PDFs
    ground_truth/ground_truth.json    HIDDEN: record -> entity map + current facts

Only `ground_truth/` knows the answers; the ingest layer never reads it.
"""

from __future__ import annotations

import json
import random
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import ClassVar

from canon.synth.seeds import REPS, SEEDS, SIGNATORIES, CustomerSeed

REFERENCE_DATE = date(2026, 10, 1)
# Fictional callers of the MCP server and the ACL groups they belong to.
# Sources carry ACLs: CRM -> sales, exec; Slack -> sales; contracts -> legal, exec.
IDENTITIES = {
    "callers": {
        **{name.lower().replace(" ", "."): {"name": name, "groups": ["sales"]} for _, name in REPS},
        "hind.legal": {"name": "Hind Amrani (legal counsel)", "groups": ["legal"]},
        "ceo": {"name": "Chief Executive Officer", "groups": ["exec"]},
        "revops.admin": {"name": "RevOps admin", "groups": ["sales", "legal", "exec"]},
        "intern": {"name": "Summer intern", "groups": []},
    }
}
DEFAULT_SEED = 20261001
VENDOR = "Tadamon Solutions SARL"

LEGAL_VARIANTS = {
    "SARL": ["SARL", "S.A.R.L.", "Sarl", "SARL AU", "S.A.R.L", "Société à Responsabilité Limitée"],
    "SA": ["SA", "S.A.", "S.A", "Société Anonyme"],
    "SAS": ["SAS", "S.A.S."],
    "Ltd": ["Ltd", "Ltd.", "Limited", "LTD"],
}
ARABIC_LEGAL = {"SARL": "ش.م.م", "SA": "ش.م", "SAS": "ش.م.ب", "Ltd": "المحدودة"}
FREE_MAIL = ["gmail.com", "hotmail.fr", "yahoo.fr", "outlook.com"]
CHANNEL_PREFIXES = ["client", "acc", "deal", "ext"]
FR_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
    "septembre", "octobre", "novembre", "décembre",
]  # fmt: skip


@dataclass
class Truth:
    """Current, correct facts for one customer (the answer key)."""

    entity_id: str
    seed: CustomerSeed
    tax_id: str
    phone: str  # E.164 switchboard
    mobile: str  # contact person's mobile, E.164
    contact_first: str
    address: str
    old_address: str | None
    owner: str
    previous_owner: str
    contract_number: str
    v1_value: int
    v2_value: int
    v1_signed: date
    v1_start: date
    v1_renewal: date
    v2_signed: date
    v2_renewal: date
    signatory: str
    owner_change_in_slack_only: bool
    crm_value_stale: bool


class Generator:
    """The Moroccan profile (French, Darija, Arabic names, MAD). Locale details are class attributes
    and small hooks so another profile can subclass it (see `canon/synth/west.py`)."""

    SEEDS = SEEDS
    REPS = REPS
    SIGNATORIES = SIGNATORIES
    VENDOR = VENDOR
    IDENTITIES = IDENTITIES
    CURRENCY = "MAD"
    EMAIL_LOCALS = ("contact", "info", "{first}", "achats")
    FREE_MAIL = tuple(FREE_MAIL)
    NUMERIC_DATE = "%d/%m/%Y"  # how people in this locale write dates by hand
    TAX_COLUMN = "ICE"
    CONTACT_NAMES = ("Hamid", "Samira", "Driss", "Loubna", "Yassine", "Ghita", "Reda", "Asmae")
    OLD_STREETS = ("Allal Ben Abdellah", "Ibn Batouta", "Al Moutanabbi", "Oued Sebou")
    # chat wording ({u}: user mention, {m}: customer mention, {v}: amount, {d}: date)
    MENTIONS = ("{nick}", "{nick_lower}", "chrika dyal {nick_lower}", "{name}")
    TEMPLATES_OWNER = (
        "Salam, mn daba <@{u}> howa l'owner dyal {m}",
        "FYI <@{u}> reprend le compte {m} à partir d'aujourd'hui",
        "Account owner: <@{u}> ({m})",
    )
    TEMPLATES_VALUE = (
        "Deal signé m3a {m}: {v} par an",
        "contrat {m} tla3 l {v} 🎉",
        "Nouveau montant annuel pour {m}: {v}",
    )
    TEMPLATES_RENEWAL = (
        "renouvellement dyal {m} f {d}",
        "Renewal {m} prévu le {d}",
        "rappel: date de renouvellement {m} = {d}",
    )
    CHATTER = (
        "chkon 3ndo l'update 3la {m}?",
        "rappel: meeting m3a {m} ghda 10h",
        "{m} se plaignent du retard de livraison, 3afak tchouf m3ahom",
        "wach kayn chi news 3la {m}?",
        "Envoyé la facture à {m}",
        "{m} bghaw demo dyal la nouvelle version",
    )
    CONTACT_EMAIL_POST = "contact chez {m}: {e}"
    CONTACT_PHONE_POST = "3ayto l {n} f {p}"
    CHANNEL_PURPOSE = "Suivi compte {m}"
    CHANNEL_TOPICS = ("", "Kolchi 3la had chrika hna", "Account channel")

    def __init__(self, seed: int = DEFAULT_SEED) -> None:
        self.rng = random.Random(seed)
        self.seed = seed
        self.records: dict[str, str] = {}  # record_id -> entity_id
        self.notes: dict[str, list[str]] = {}  # record_id -> what makes it messy
        self._used_ids: set[str] = set()

    # ------------------------------------------------------------------ helpers
    def _unique(self, make) -> str:
        while True:
            value = make()
            if value not in self._used_ids:
                self._used_ids.add(value)
                return value

    def _date_between(self, start: date, end: date) -> date:
        return start + timedelta(days=self.rng.randint(0, (end - start).days))

    def _typo(self, text: str) -> str:
        words = text.split(" ")
        candidates = [i for i, w in enumerate(words) if len(w) >= 5 and w.isalpha()]
        if not candidates:
            return text
        i = self.rng.choice(candidates)
        w = words[i]
        pos = self.rng.randint(1, len(w) - 2)
        op = self.rng.choice(["swap", "drop", "double", "sub"])
        if op == "swap":
            w = w[:pos] + w[pos + 1] + w[pos] + w[pos + 2 :]
        elif op == "drop":
            w = w[:pos] + w[pos + 1 :]
        elif op == "double":
            w = w[:pos] + w[pos] + w[pos:]
        else:
            w = w[:pos] + self.rng.choice("aeiourstln") + w[pos + 1 :]
        words[i] = w
        return " ".join(words)

    @staticmethod
    def _strip_accents(text: str) -> str:
        import unicodedata

        return "".join(
            c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
        )

    def _legal(self, form: str) -> str:
        return self.rng.choice(LEGAL_VARIANTS[form])

    def _phone_variant(self, e164: str) -> str:
        national = "0" + e164[4:]  # +212522... -> 0522...
        d = national
        style = self.rng.choice(["e164", "spaced", "dashed", "intl00", "paren", "plain"])
        if style == "e164":
            return e164
        if style == "spaced":
            return " ".join([d[:2], d[2:4], d[4:6], d[6:8], d[8:]])
        if style == "dashed":
            return "-".join([d[:4], d[4:6], d[6:8], d[8:]])
        if style == "intl00":
            return "00" + e164[1:]
        if style == "paren":
            return f"+212 (0){d[1:2]} {d[2:4]} {d[4:6]} {d[6:8]} {d[8:]}"
        return d

    def _money(self, value: int) -> str:
        style = self.rng.choice(["space", "dot", "comma", "k", "raw"])
        if style == "space":
            return f"{value:,}".replace(",", " ") + " MAD"
        if style == "dot":
            return f"{value:,}".replace(",", ".") + " DH"
        if style == "comma":
            return f"{value:,} MAD"
        if style == "k":
            return f"{value / 1000:g}k MAD"
        return str(value)

    # ------------------------------------------------------------------ locale hooks
    def _new_tax_id(self) -> str:  # ICE: 15 digits
        return "00" + "".join(self.rng.choices("0123456789", k=13))

    def _new_phone(self, mobile: bool) -> str:  # E.164
        return ("+2126" if mobile else "+2125") + "".join(self.rng.choices("0123456789", k=8))

    def _old_address(self) -> str:
        return f"{self.rng.randint(2, 140)} Rue {self.rng.choice(self.OLD_STREETS)}"

    # ------------------------------------------------------------------ truth
    def build_truths(self) -> list[Truth]:
        rng = self.rng
        truths = []
        for idx, seed in enumerate(self.SEEDS, start=1):
            owner, previous = rng.sample([name for _, name in self.REPS], 2)
            v1_signed = self._date_between(date(2023, 1, 10), date(2024, 6, 30))
            v1_start = v1_signed + timedelta(days=rng.randint(5, 30))
            v1_start = v1_start.replace(day=1)
            v1_renewal = v1_start.replace(year=v1_start.year + 2)
            v2_signed = self._date_between(date(2025, 3, 1), date(2026, 6, 30))
            v2_renewal = v2_signed.replace(day=1).replace(year=v2_signed.year + rng.choice([1, 2]))
            if v2_renewal <= REFERENCE_DATE:
                v2_renewal = v2_renewal.replace(year=v2_renewal.year + 1)
            v1_value = rng.randrange(60_000, 1_500_000, 5_000)
            v2_value = int(round(v1_value * rng.uniform(1.05, 1.35), -3))
            moved = rng.random() < 0.2
            old_address = None
            if moved:
                old_address = self._old_address()
            truths.append(
                Truth(
                    entity_id=f"E{idx:02d}",
                    seed=seed,
                    tax_id=self._unique(self._new_tax_id),
                    phone=self._unique(lambda: self._new_phone(mobile=False)),
                    mobile=self._unique(lambda: self._new_phone(mobile=True)),
                    contact_first=rng.choice(list(self.CONTACT_NAMES)),
                    address=seed.street,
                    old_address=old_address,
                    owner=owner,
                    previous_owner=previous,
                    contract_number=f"CN-{v1_signed.year}-{idx * 7 + 100:03d}",
                    v1_value=v1_value,
                    v2_value=v2_value,
                    v1_signed=v1_signed,
                    v1_start=v1_start,
                    v1_renewal=v1_renewal,
                    v2_signed=v2_signed,
                    v2_renewal=v2_renewal,
                    signatory=rng.choice(self.SIGNATORIES),
                    owner_change_in_slack_only=False,  # decided once channels are known
                    crm_value_stale=rng.random() < 0.3,
                )
            )
        return truths

    # ------------------------------------------------------------------ CRM
    def crm_name(self, t: Truth, variant: str) -> str:
        s = t.seed
        if variant == "clean":
            return f"{s.name} {self._legal(s.legal_form)}"
        if variant == "typo":
            return f"{self._typo(s.name)} {self._legal(s.legal_form)}"
        if variant == "upper":
            return f"{self._strip_accents(s.name).upper()} {s.legal_form.upper()}"
        if variant == "arabic" and s.arabic:
            return f"{s.arabic} {ARABIC_LEGAL[s.legal_form]}"
        if variant == "darija":
            return f"Chrikat {s.aliases[0] if s.aliases else s.name}"
        if variant == "ste":
            return f"Sté {s.name}"
        if variant == "alias" and s.aliases:
            return self.rng.choice(s.aliases)
        return f"{self._strip_accents(s.name)} {self._legal(s.legal_form)}"

    def crm_records(self, t: Truth, n: int, slack_change_after: date | None) -> list[dict]:
        rng = self.rng
        s = t.seed
        out = []
        for k in range(n):
            primary = k == 0
            acc_id = self._unique(
                lambda: (
                    "0015g0000" + "".join(rng.choices("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789", k=6))
                )
            )
            notes = []
            if primary:
                variant = rng.choice(["clean", "clean", "upper", "ste"])
                modified = self._date_between(date(2026, 3, 1), date(2026, 9, 20))
                if slack_change_after is not None:
                    modified = slack_change_after - timedelta(days=rng.randint(20, 120))
                owner = t.previous_owner if slack_change_after is not None else t.owner
                if slack_change_after is not None:
                    notes.append("stale:owner")
                value = t.v1_value if t.crm_value_stale else t.v2_value
                renewal = t.v1_renewal if t.crm_value_stale else t.v2_renewal
                if t.crm_value_stale:
                    notes += ["stale:contract_value", "stale:renewal_date"]
                address = t.address
            else:
                variant = rng.choice(["typo", "arabic", "darija", "alias", "typo", "noaccent"])
                if variant == "arabic" and not s.arabic:
                    variant = "typo"
                modified = self._date_between(date(2024, 1, 15), date(2025, 6, 30))
                owner = t.previous_owner
                value = t.v1_value
                renewal = t.v1_renewal
                notes += ["stale:owner", "stale:contract_value", "stale:renewal_date"]
                address = t.old_address or t.address
                if t.old_address:
                    notes.append("stale:address")
            notes.append(f"name:{variant}")
            website = None
            if rng.random() < (0.9 if primary else 0.55):
                website = rng.choice(
                    [s.domain, f"www.{s.domain}", f"https://{s.domain}/", f"http://www.{s.domain}"]
                )
            phone = None
            if rng.random() < (0.9 if primary else 0.6):
                phone = self._phone_variant(t.phone if rng.random() < 0.75 else t.mobile)
            email = None
            if rng.random() < 0.7:
                local = rng.choice(
                    [x.format(first=t.contact_first.lower()) for x in self.EMAIL_LOCALS]
                )
                domain = s.domain
                if not primary and rng.random() < 0.4:
                    domain = rng.choice(self.FREE_MAIL)
                    local = f"{t.contact_first.lower()}.{s.key.replace('-', '')}"
                    notes.append("free_mail")
                email = f"{local}@{domain}"
            renewal_str = (
                renewal.isoformat() if rng.random() < 0.6 else renewal.strftime(self.NUMERIC_DATE)
            )
            record = {
                "Id": acc_id,
                "Account Name": self.crm_name(t, variant),
                "Website": website,
                "Phone": phone,
                "Primary Contact Email": email,
                "Billing Street": address if rng.random() < 0.85 else None,
                "Billing City": rng.choice([s.city, s.city.upper(), self._strip_accents(s.city)]),
                self.TAX_COLUMN: t.tax_id if rng.random() < (0.5 if primary else 0.25) else None,
                "Industry": s.industry,
                "Owner": owner,
                "Annual Contract Value": value if rng.random() < 0.5 else self._money(value),
                "Currency": self.CURRENCY,
                "Renewal Date": renewal_str,
                "LastModifiedDate": datetime.combine(
                    modified, datetime.min.time().replace(hour=rng.randint(8, 18))
                ).isoformat()
                + "Z",
            }
            rid = f"crm:{acc_id}"
            self.records[rid] = t.entity_id
            self.notes[rid] = notes
            out.append(record)
        return out

    # ------------------------------------------------------------------ Slack
    def slack_channel(
        self, t: Truth, archived: bool, users: dict[str, str]
    ) -> tuple[dict, dict[str, list[dict]], date | None]:
        """Return (channel meta, {day: messages}, date of owner change if any)."""
        rng = self.rng
        s = t.seed
        uid = {name: u for u, name in users.items()}
        nick = rng.choice(list(s.aliases) or [s.name])
        slug_source = rng.choice([s.name, nick, nick])
        slug = self._strip_accents(slug_source).lower().replace("'", "").replace(" ", "-")
        if rng.random() < 0.3:
            slug = slug.replace("-", "")
        prefix = "old" if archived else rng.choice(CHANNEL_PREFIXES)
        name = f"{prefix}-{slug}"
        cid = self._unique(
            lambda: "C0" + "".join(rng.choices("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789", k=8))
        )
        notes = [f"channel:{name}"]
        days: dict[str, list[dict]] = {}

        def post(when: date, user: str, text: str) -> None:
            ts = datetime.combine(when, datetime.min.time(), tzinfo=UTC) + timedelta(
                hours=rng.randint(8, 19), minutes=rng.randint(0, 59)
            )
            days.setdefault(when.isoformat(), []).append(
                {"type": "message", "user": user, "text": text, "ts": f"{ts.timestamp():.6f}"}
            )

        mention = rng.choice(
            [m.format(nick=nick, nick_lower=nick.lower(), name=s.name) for m in self.MENTIONS]
        )
        owner_change = None
        if archived:
            start = t.v1_signed - timedelta(days=30)
            end = t.v2_signed - timedelta(days=60)
            owner = t.previous_owner
            value, renewal = t.v1_value, t.v1_renewal
            notes += ["archived", "stale:owner", "stale:contract_value", "stale:renewal_date"]
        else:
            start = t.v2_signed - timedelta(days=20)
            end = REFERENCE_DATE - timedelta(days=5)
            owner = t.owner
            value, renewal = t.v2_value, t.v2_renewal
        author = uid[owner]
        templates_owner = list(self.TEMPLATES_OWNER)
        templates_value = list(self.TEMPLATES_VALUE)
        templates_renewal = list(self.TEMPLATES_RENEWAL)
        chatter = list(self.CHATTER)
        posts = [
            ("value", rng.choice(templates_value).format(m=mention, v=self._money(value))),
            (
                "renewal",
                rng.choice(templates_renewal).format(
                    m=mention, d=renewal.strftime(self.NUMERIC_DATE)
                ),
            ),
        ]
        if rng.random() < 0.75:
            email = f"{rng.choice(['contact', t.contact_first.lower()])}@{s.domain}"
            posts.append(("contact", self.CONTACT_EMAIL_POST.format(m=mention, e=email)))
        if rng.random() < 0.5:
            phone = self._phone_variant(t.mobile)
            posts.append(("contact", self.CONTACT_PHONE_POST.format(n=t.contact_first, p=phone)))
        posts += [
            ("chatter", rng.choice(chatter).format(m=mention)) for _ in range(rng.randint(1, 3))
        ]
        rng.shuffle(posts)
        owner_post = ("owner", rng.choice(templates_owner).format(u=author, m=mention))
        # In active channels the owner statement is the latest (freshest) signal.
        if archived:
            posts.insert(rng.randint(0, len(posts)), owner_post)
        else:
            posts.append(owner_post)
        timeline = sorted(self._date_between(start, end) for _ in posts)
        for when, (kind, text) in zip(timeline, posts, strict=True):
            user = author if kind in {"owner", "value"} else rng.choice(list(users))
            post(when, user, text)
            if kind == "owner" and not archived:
                owner_change = when
        meta = {
            "id": cid,
            "name": name,
            "created": int(datetime.combine(start, datetime.min.time(), tzinfo=UTC).timestamp()),
            "is_archived": archived,
            "purpose": {"value": self.CHANNEL_PURPOSE.format(m=mention)},
            "topic": {"value": rng.choice(list(self.CHANNEL_TOPICS))},
            "members": sorted({author, rng.choice(list(users))}),
        }
        rid = f"slack:{cid}"
        self.records[rid] = t.entity_id
        self.notes[rid] = notes
        return meta, days, owner_change

    # ------------------------------------------------------------------ contracts
    def contract_text(self, t: Truth, version: int) -> str:
        s = t.seed
        rng = self.rng
        signed = t.v1_signed if version == 1 else t.v2_signed
        value = t.v1_value if version == 1 else t.v2_value
        start = t.v1_start if version == 1 else t.v2_signed.replace(day=1)
        renewal = t.v1_renewal if version == 1 else t.v2_renewal
        address = (t.old_address or t.address) if version == 1 else t.address
        party = rng.choice(
            [
                f"{s.name} {self._legal(s.legal_form)}",
                f"Ste {s.name} {s.legal_form}",
                f"{s.name}, {self._legal(s.legal_form)}",
            ]
        )
        fmt = "%d/%m/%Y"
        if s.lang == "en":
            supersede = (
                f"\nClause 12 - Entire agreement. This agreement supersedes and replaces version 1 "
                f"of agreement {t.contract_number} signed on {t.v1_signed.strftime(fmt)}.\n"
                if version == 2
                else ""
            )
            return (
                "SERVICES AGREEMENT\n"
                f"Agreement No: {t.contract_number}\n"
                f"Version: {version}\n"
                f"Signature date: {signed.strftime(fmt)}\n\n"
                "BETWEEN\n"
                f"{self.VENDOR}, hereinafter the Provider,\n"
                "AND\n"
                f"Customer: {party}\n"
                f"Tax ID (ICE): {t.tax_id}\n"
                f"Registered office: {address}, {s.city}\n"
                f"Represented by: {t.signatory}\n"
                f"Contact: {rng.choice(['contact', 'legal'])}@{s.domain}"
                f" - Tel: {self._phone_variant(t.phone)}\n\n"
                "Clause 1 - Scope. The Provider supplies data platform services.\n"
                f"Clause 4 - Fees. The annual fee is {value:,} MAD excluding VAT.\n"
                f"Clause 5 - Term. Effective date: {start.strftime(fmt)}. "
                f"Renewal date: {renewal.strftime(fmt)}.\n"
                f"{supersede}"
                f"\nSigned for the Customer: {t.signatory}\n"
            )
        arabic_line = f"الطرف الثاني: {s.arabic} {ARABIC_LEGAL[s.legal_form]}\n" if s.arabic else ""
        supersede = (
            f"\nArticle 12 - Le présent contrat annule et remplace la version 1 du contrat "
            f"N° {t.contract_number} signée le {t.v1_signed.strftime(fmt)}.\n"
            if version == 2
            else ""
        )
        montant = f"{value:,}".replace(",", " ")
        return (
            "CONTRAT DE PRESTATION DE SERVICES\n"
            f"Contrat N° : {t.contract_number}\n"
            f"Version : {version}\n"
            f"Date de signature : {signed.strftime(fmt)}\n\n"
            "ENTRE LES SOUSSIGNÉS :\n"
            f"{self.VENDOR}, ci-après « le Prestataire »,\n"
            "ET\n"
            f"Le Client : {party}\n"
            f"{arabic_line}"
            f"ICE : {t.tax_id}\n"
            f"Siège social : {address}, {s.city}\n"
            f"Représenté par : {t.signatory}\n"
            f"Contact : {rng.choice(['contact', 'juridique'])}@{s.domain}"
            f" - Tél : {self._phone_variant(t.phone)}\n\n"
            "Article 1 - Objet. Le Prestataire fournit des services de plateforme de données.\n"
            f"Article 4 - Prix. Le montant annuel est fixé à {montant} MAD HT.\n"
            f"Article 5 - Durée. Date d'effet : {start.strftime(fmt)}. "
            f"Date de renouvellement : {renewal.strftime(fmt)}.\n"
            f"{supersede}"
            f"\nFait à {s.city}, le {signed.day} {FR_MONTHS[signed.month - 1]} {signed.year}\n"
            f"Pour le Client : {t.signatory}\n"
        )

    # ------------------------------------------------------------------ main
    def generate(self, out_dir: Path) -> dict:
        rng = self.rng
        truths = self.build_truths()
        users = dict(self.REPS)
        crm: list[dict] = []
        channels: list[dict] = []
        channel_days: dict[str, dict[str, list[dict]]] = {}
        contracts: dict[str, str] = {}
        entities = {}

        for t in truths:
            # appearances: 2 contract versions + 1-3 CRM + 0-2 Slack, total 3..6
            while True:
                n_crm = rng.choice([1, 1, 2, 2, 3])
                n_slack = rng.choice([0, 1, 1, 2])
                if 3 <= 2 + n_crm + n_slack <= 6:
                    break
            has_active = n_slack >= 1
            has_archived = n_slack == 2 or (n_slack == 1 and rng.random() < 0.25)
            if n_slack == 1 and has_archived:
                has_active = False
            owner_change = None
            if has_archived:
                meta, days, _ = self.slack_channel(t, archived=True, users=users)
                channels.append(meta)
                channel_days[meta["name"]] = days
            if has_active:
                meta, days, owner_change = self.slack_channel(t, archived=False, users=users)
                channels.append(meta)
                channel_days[meta["name"]] = days
            slack_only = has_active and owner_change is not None and rng.random() < 0.35
            t.owner_change_in_slack_only = slack_only
            crm.extend(self.crm_records(t, n_crm, owner_change if slack_only else None))
            for version in (1, 2):
                stem = f"{t.contract_number}_v{version}"
                contracts[stem] = self.contract_text(t, version)
                rid = f"contract:{stem}"
                self.records[rid] = t.entity_id
                self.notes[rid] = ["superseded"] if version == 1 else []
                if version == 1 and t.old_address:
                    self.notes[rid].append("stale:address")
            s = t.seed
            entities[t.entity_id] = {
                "key": s.key,
                "name": s.name,
                "legal_name": f"{s.name} {s.legal_form}",
                "legal_form": s.legal_form,
                "arabic_name": s.arabic,
                "domain": s.domain,
                "phone": t.phone,
                "address": t.address,
                "city": s.city,
                "tax_id": t.tax_id,
                "industry": s.industry,
                "owner": t.owner,
                "contract_number": t.contract_number,
                "contract_value": t.v2_value,
                "currency": self.CURRENCY,
                "contract_start": t.v2_signed.replace(day=1).isoformat(),
                "renewal_date": t.v2_renewal.isoformat(),
                "signatory": t.signatory,
                "owner_change_in_slack_only": t.owner_change_in_slack_only,
                "crm_value_stale": t.crm_value_stale,
            }

        rng.shuffle(crm)
        if out_dir.exists():
            for sub in ("crm", "slack", "contracts", "ground_truth"):
                shutil.rmtree(out_dir / sub, ignore_errors=True)
        _write_json(out_dir / "crm" / "accounts.json", crm)
        _write_json(
            out_dir / "slack" / "users.json",
            [{"id": u, "name": n.split()[0].lower(), "real_name": n} for u, n in self.REPS],
        )
        _write_json(out_dir / "slack" / "channels.json", sorted(channels, key=lambda c: c["name"]))
        for name, days in channel_days.items():
            for day, msgs in days.items():
                _write_json(out_dir / "slack" / name / f"{day}.json", msgs)
        for stem, text in contracts.items():
            path = out_dir / "contracts" / f"{stem}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        truth = {
            "seed": self.seed,
            "reference_date": REFERENCE_DATE.isoformat(),
            "entities": entities,
            "records": dict(sorted(self.records.items())),
            "record_notes": dict(sorted(self.notes.items())),
        }
        _write_json(out_dir / "ground_truth" / "ground_truth.json", truth)
        _write_json(out_dir / "identities.json", self.IDENTITIES)
        self.write_extra(out_dir)
        from canon.evals.questions import build_questions  # eval set derives from the truth

        _write_json(
            out_dir / "ground_truth" / "eval_questions.json",
            [q.model_dump() for q in build_questions(truth)],
        )
        return truth

    # the deployment settings a real client with this data would write (docs/DEPLOY.md)
    DEPLOYMENT: ClassVar[dict] = {"ingest": {"default_country": "212", "currency": "MAD"}}

    def write_extra(self, out_dir: Path) -> None:
        _write_json(out_dir / "canon.json", self.DEPLOYMENT)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def generate(out_dir: Path, seed: int = DEFAULT_SEED) -> dict:
    return Generator(seed).generate(Path(out_dir))
