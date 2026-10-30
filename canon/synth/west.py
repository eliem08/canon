"""The Western synthetic profile: a US B2B software vendor's customer data.

Same structure and the same kinds of mess as the Moroccan profile (`canon/synth/generate.py`):
duplicate CRM accounts, stale CRM values superseded by a signed contract, owner changes announced
only in Slack, look-alike customers ("Summit Logistics" / "Summit Travel"). Everything is in
English, in USD, with US phone numbers, EINs and month-first dates; contracts state dates in words
and some carry an auto-renewal clause with a notice period.

    uv run canon generate --profile west --out data/synthetic_west

All companies, people, domains, phone numbers and tax ids are invented.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import ClassVar

from canon.synth.generate import DEFAULT_SEED, Generator, Truth
from canon.synth.seeds import CustomerSeed


def _seed(key, name, form, domain, city, street, industry, *aliases) -> CustomerSeed:
    return CustomerSeed(key, name, form, domain, city, street, industry, None, aliases, "en")


WEST_SEEDS: tuple[CustomerSeed, ...] = (
    _seed("summit-log", "Summit Logistics", "Inc", "summitlogistics.com", "Denver",
          "1450 Larimer St", "Logistics", "Summit Log", "SummitLog"),
    _seed("summit-travel", "Summit Travel", "LLC", "summittravel.com", "Denver",
          "800 Lincoln St", "Travel", "Summit Trips"),
    _seed("northwind", "Northwind Analytics", "Inc", "northwindanalytics.io", "Seattle",
          "1201 3rd Ave", "Software", "Northwind", "NWA"),
    _seed("northwind-pack", "Northwind Packaging", "LLC", "northwindpack.com", "Tacoma",
          "2302 Pacific Ave", "Manufacturing", "NW Packaging"),
    _seed("bluefin", "Bluefin Health", "Inc", "bluefinhealth.com", "Boston",
          "100 Summer St", "Healthcare", "Bluefin"),
    _seed("harbor-foods", "Harbor Foods", "Corp", "harborfoods.com", "Baltimore",
          "300 E Pratt St", "Food", "Harbor"),
    _seed("redwood", "Redwood Capital Partners", "LLC", "redwoodcp.com", "San Francisco",
          "555 California St", "Finance", "Redwood Capital", "RCP"),
    _seed("ironclad-mfg", "Ironclad Manufacturing", "Inc", "ironcladmfg.com", "Cleveland",
          "1300 E 9th St", "Manufacturing", "Ironclad"),
    _seed("lumen-retail", "Lumen Retail Group", "Inc", "lumenretail.com", "Chicago",
          "233 S Wacker Dr", "Retail", "Lumen Retail", "Lumen"),
    _seed("cedar-ins", "Cedar Insurance Brokers", "LLC", "cedarins.com", "Hartford",
          "185 Asylum St", "Insurance", "Cedar Insurance"),
    _seed("atlas-freight", "Atlas Freight", "Inc", "atlasfreight.com", "Dallas",
          "2200 Ross Ave", "Logistics", "Atlas"),
    _seed("pioneer-energy", "Pioneer Energy Services", "Corp", "pioneerenergy.com", "Houston",
          "811 Main St", "Energy", "Pioneer Energy"),
    _seed("granite-legal", "Granite Legal Solutions", "LLC", "granitelegal.com", "New York",
          "450 Lexington Ave", "Legal", "Granite Legal"),
    _seed("meridian-edu", "Meridian Learning", "Inc", "meridianlearning.com", "Austin",
          "600 Congress Ave", "Education", "Meridian"),
    _seed("oakline", "Oakline Hotels", "LLC", "oaklinehotels.com", "Nashville",
          "150 4th Ave N", "Hospitality", "Oakline"),
    _seed("vertex-bio", "Vertex Biologics", "Inc", "vertexbiologics.com", "San Diego",
          "4250 Executive Sq", "Biotech", "Vertex Bio"),
    _seed("keystone", "Keystone Construction", "Inc", "keystonebuild.com", "Philadelphia",
          "1650 Market St", "Construction", "Keystone"),
    _seed("brightpath", "BrightPath Telecom", "Inc", "brightpathtel.com", "Atlanta",
          "1180 Peachtree St NE", "Telecom", "BrightPath", "Bright Path"),
    _seed("evergreen", "Evergreen Supply Co", "LLC", "evergreensupply.com", "Portland",
          "1000 SW Broadway", "Distribution", "Evergreen Supply"),
    _seed("copperline", "Copperline Media", "Inc", "copperlinemedia.com", "Los Angeles",
          "2049 Century Park E", "Media", "Copperline"),
    _seed("tidewater", "Tidewater Marine", "Corp", "tidewatermarine.com", "Norfolk",
          "150 W Main St", "Marine", "Tidewater"),
    _seed("silverleaf", "Silverleaf Dental Group", "LLC", "silverleafdental.com", "Phoenix",
          "2 N Central Ave", "Healthcare", "Silverleaf"),
    _seed("quarry", "Quarry Data Systems", "Inc", "quarrydata.com", "Raleigh",
          "421 Fayetteville St", "Software", "Quarry Data", "QDS"),
    _seed("lakeshore", "Lakeshore Logistics", "LLC", "lakeshorelogistics.com", "Milwaukee",
          "1450 Larimer St", "Logistics", "Lakeshore"),  # same street as Summit Logistics
    _seed("brightwater", "Brightwater Analytics", "Inc", "brightwateranalytics.com", "Minneapolis",
          "80 S 8th St", "Software", "Brightwater"),
)  # fmt: skip

WEST_REPS: tuple[tuple[str, str], ...] = (
    ("U01", "Jordan Miller"),
    ("U02", "Sarah Chen"),
    ("U03", "Marcus Johnson"),
    ("U04", "Emily Rodriguez"),
    ("U05", "David Kim"),
    ("U06", "Priya Patel"),
    ("U07", "Tom Anderson"),
    ("U08", "Rachel Green"),
)
WEST_SIGNATORIES: tuple[str, ...] = (
    "Michael Thompson", "Jennifer Walsh", "Robert Hughes", "Lisa Morgan", "Daniel Brooks",
    "Karen Mitchell", "Steven Wright", "Amanda Foster", "Brian Collins", "Nicole Harper",
    "Kevin Sullivan", "Laura Bennett",
)  # fmt: skip
WEST_IDENTITIES = {
    "callers": {
        **{
            name.lower().replace(" ", "."): {"name": name, "groups": ["sales"]}
            for _, name in WEST_REPS
        },
        "dana.legal": {"name": "Dana Whitfield (legal counsel)", "groups": ["legal"]},
        "ceo": {"name": "Chief Executive Officer", "groups": ["exec"]},
        "revops.admin": {"name": "RevOps admin", "groups": ["sales", "legal", "exec"]},
        "intern": {"name": "Summer intern", "groups": []},
    }
}
LEGAL_VARIANTS = {
    "Inc": ["Inc", "Inc.", "Incorporated", "INC"],
    "LLC": ["LLC", "L.L.C.", "llc"],
    "Corp": ["Corp", "Corp.", "Corporation"],
    "Ltd": ["Ltd", "Ltd.", "Limited"],
}
AREA_CODES = ("212", "312", "415", "617", "206", "512", "303", "404", "713", "215")


class WestGenerator(Generator):
    SEEDS = WEST_SEEDS
    REPS = WEST_REPS
    SIGNATORIES = WEST_SIGNATORIES
    VENDOR = "Fieldstone Software, Inc."
    IDENTITIES = WEST_IDENTITIES
    CURRENCY = "USD"
    TAX_COLUMN = "Tax ID"
    NUMERIC_DATE = "%m/%d/%Y"
    EMAIL_LOCALS = ("contact", "info", "{first}", "billing")
    FREE_MAIL = ("gmail.com", "outlook.com", "yahoo.com", "icloud.com")
    CONTACT_NAMES = ("Chris", "Megan", "Ryan", "Ashley", "Josh", "Lauren", "Tyler", "Hannah")
    OLD_STREETS = ("Oak St", "Maple Ave", "Main St", "Elm St", "Washington Blvd")
    MENTIONS = ("{nick}", "{nick_lower}", "the {nick} team", "{name}")
    TEMPLATES_OWNER = (
        "Heads up: <@{u}> is taking over the {m} account starting today",
        "FYI <@{u}> now owns {m}",
        "Account owner: <@{u}> ({m})",
    )
    TEMPLATES_VALUE = (
        "Closed the renewal with {m}: {v} per year",
        "{m} signed! New ACV {v} 🎉",
        "New annual contract value for {m}: {v}",
    )
    TEMPLATES_RENEWAL = (
        "{m} renewal is on {d}",
        "Reminder: {m} renews {d}",
        "renewal date for {m} = {d}",
    )
    CHATTER = (
        "anyone have an update on {m}?",
        "QBR with {m} tomorrow at 10",
        "{m} is complaining about the onboarding delays, can someone check in?",
        "any news from {m}?",
        "Sent the invoice to {m}",
        "{m} asked for a demo of the new release",
    )
    CONTACT_EMAIL_POST = "main contact at {m}: {e}"
    CONTACT_PHONE_POST = "call {n} at {p}"
    CHANNEL_PURPOSE = "Account channel for {m}"
    CHANNEL_TOPICS = ("", "Everything about this customer", "Account channel")
    DEPLOYMENT: ClassVar[dict] = {
        "ingest": {"default_country": "1", "currency": "USD", "dayfirst": False},
        "crm": {"columns": {"tax_id": "Tax ID"}},
    }

    # ------------------------------------------------------------------ locale hooks
    def _new_tax_id(self) -> str:  # EIN
        d = "".join(self.rng.choices("0123456789", k=9))
        return f"{self.rng.randint(10, 98)}-{d[:7]}"

    def _new_phone(self, mobile: bool) -> str:
        exchange = f"{self.rng.randint(2, 9)}{self.rng.randint(0, 9)}{self.rng.randint(0, 9)}"
        line = "".join(self.rng.choices("0123456789", k=4))
        return f"+1{self.rng.choice(AREA_CODES)}{exchange}{line}"

    def _old_address(self) -> str:
        return f"{self.rng.randint(10, 2400)} {self.rng.choice(self.OLD_STREETS)}"

    def _legal(self, form: str) -> str:
        return self.rng.choice(LEGAL_VARIANTS[form])

    def _phone_variant(self, e164: str) -> str:
        a, x, n = e164[2:5], e164[5:8], e164[8:]
        style = self.rng.choice(["e164", "paren", "dashed", "dotted", "intl", "one"])
        return {
            "e164": e164,
            "paren": f"({a}) {x}-{n}",
            "dashed": f"{a}-{x}-{n}",
            "dotted": f"{a}.{x}.{n}",
            "intl": f"+1 {a} {x} {n}",
            "one": f"1-{a}-{x}-{n}",
        }[style]

    def _money(self, value: int) -> str:
        style = self.rng.choice(["dollar", "usd", "k", "code", "raw"])
        if style == "dollar":
            return f"${value:,}"
        if style == "usd":
            return f"{value:,} USD"
        if style == "k":
            return f"${value / 1000:g}k"
        if style == "code":
            return f"USD {value}"
        return str(value)

    def crm_name(self, t: Truth, variant: str) -> str:
        s = t.seed
        alias = self.rng.choice(s.aliases) if s.aliases else s.name
        if variant == "clean":
            return f"{s.name} {self._legal(s.legal_form)}"
        if variant == "typo":
            return f"{self._typo(s.name)} {self._legal(s.legal_form)}"
        if variant == "upper":
            return f"{s.name.upper()} {s.legal_form.upper()}"
        if variant == "arabic":  # this profile's third-script variant: a "dba" name
            return f"{s.name} {self._legal(s.legal_form)} dba {alias}"
        if variant == "darija":  # an informal office label
            return f"{alias} - HQ"
        if variant == "ste":
            return f"{s.name}, {self._legal(s.legal_form)}"
        if variant == "alias":
            return alias
        return f"{s.name} {self._legal(s.legal_form)}"

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
            [f"{s.name} {self._legal(s.legal_form)}", f"{s.name}, {self._legal(s.legal_form)}"]
        )

        def words(d: date) -> str:  # "March 3, 2025": no day/month ambiguity
            return f"{d:%B} {d.day}, {d.year}"

        supersede = (
            f"\nSection 12 - Entire agreement. This agreement supersedes and replaces version 1 "
            f"of agreement {t.contract_number} signed on {words(t.v1_signed)}.\n"
            if version == 2
            else ""
        )
        auto = ""
        if version == 2 and rng.random() < 0.5:
            notice = rng.choice(["thirty (30)", "sixty (60)", "ninety (90)"])
            auto = (
                "Section 6 - Renewal. Thereafter this Agreement shall automatically renew for "
                "successive one (1) year periods unless either party gives at least "
                f"{notice} days' prior written notice of non-renewal.\n"
            )
        return (
            "MASTER SUBSCRIPTION AGREEMENT\n"
            f"Agreement No: {t.contract_number}\n"
            f"Version: {version}\n"
            f"Signature date: {words(signed)}\n\n"
            "BETWEEN\n"
            f"{self.VENDOR}, hereinafter the Provider,\n"
            "AND\n"
            f"Customer: {party}\n"
            f"Tax ID (EIN): {t.tax_id}\n"
            f"Registered office: {address}, {s.city}\n"
            f"Represented by: {t.signatory}\n"
            f"Contact: {rng.choice(['contact', 'legal'])}@{s.domain}"
            f" - Tel: {self._phone_variant(t.phone)}\n\n"
            "Section 1 - Scope. The Provider supplies data platform services.\n"
            f"Section 4 - Fees. The annual fee is USD {value:,} excluding taxes.\n"
            f"Section 5 - Term. Effective date: {words(start)}. "
            f"Renewal date: {words(renewal)}.\n"
            f"{auto}"
            f"{supersede}"
            f"\nSigned for the Customer: {t.signatory}\n"
        )


def generate_west(out_dir: Path, seed: int = DEFAULT_SEED) -> dict:
    return WestGenerator(seed).generate(Path(out_dir))  # also writes canon.json
