"""The people and companies of the seeded world. Names are invented; every address is on a
reserved `.example` domain. Identifiers (phones, IBANs, tax ids) are valid in shape and check
digit so the personal-data guards see what real data looks like."""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass, field

INTERNAL_DOMAIN = "anduin.example"
COMPANY = "Anduin"


@dataclass(frozen=True)
class Person:
    key: str
    name: str
    email: str
    org: str
    title: str
    side: str  # internal | customer | third_party
    role: str
    phone: str = ""
    lang: str = "en"
    tz: str = "-0700"  # offset of where they work
    aliases: tuple[str, ...] = ()

    @property
    def first(self) -> str:
        return self.name.split()[0]


@dataclass(frozen=True)
class Org:
    key: str
    name: str
    domain: str
    kind: str  # vendor | customer | counsel | administrator | other
    disclaimer: str = ""


@dataclass
class World:
    people: dict[str, Person] = field(default_factory=dict)
    orgs: dict[str, Org] = field(default_factory=dict)

    def p(self, key: str) -> Person:
        return self.people[key]


def iban(rng: random.Random, country: str = "GB", bank: str = "NWBK") -> str:
    """A valid IBAN (mod-97 check digits) with an invented account."""
    body = f"{bank}{rng.randint(10**13, 10**14 - 1)}"
    rearranged = body + country + "00"
    digits = "".join(str(int(c, 36)) for c in rearranged)
    check = 98 - int(digits) % 97
    return f"{country}{check:02d}{body}"


def spaced(iban_: str) -> str:
    return " ".join(iban_[i : i + 4] for i in range(0, len(iban_), 4))


def us_phone(rng: random.Random) -> str:
    return (
        f"+1 ({rng.choice([212, 415, 617, 312, 310])}) 555-01{rng.randint(0, 99):02d}"
    )


def vn_phone(rng: random.Random) -> str:
    return f"+84 9{rng.randint(0, 9)} {rng.randint(100, 999)} {rng.randint(1000, 9999)}"


def ein(rng: random.Random) -> str:
    return f"{rng.randint(10, 98)}-{rng.randint(1000000, 9999999)}"


DISCLAIMER_LAW = (
    "This message and any attachments are privileged and confidential and intended only for "
    "the addressee. If you have received it in error, please notify the sender and delete it."
)


def build_world(rng: random.Random) -> World:
    w = World()

    def org(key: str, name: str, domain: str, kind: str, disclaimer: str = "") -> None:
        w.orgs[key] = Org(key, name, domain, kind, disclaimer)

    def person(
        key: str,
        name: str,
        org_key: str,
        title: str,
        side: str,
        role: str,
        *,
        lang: str = "en",
        tz: str = "-0500",
        aliases: tuple[str, ...] = (),
        email: str | None = None,
    ) -> None:
        o = w.orgs[org_key]
        local = email or ".".join(part.lower() for part in _ascii(name).split())
        phone = vn_phone(rng) if lang != "en" or "+0700" == tz else us_phone(rng)
        w.people[key] = Person(
            key,
            name,
            f"{local}@{o.domain}",
            o.name,
            title,
            side,
            role,
            phone,
            lang,
            tz,
            aliases,
        )

    org("anduin", COMPANY, INTERNAL_DOMAIN, "vendor")
    internal = [
        ("sarah", "Sarah Kim", "Customer Success Manager", "csm", "-0700"),
        ("minh", "Minh Tran", "Senior Engineer, Digitization", "digitization", "+0700"),
        ("linh", "Linh Pham", "QA Lead", "qa", "+0700"),
        ("jake", "Jake Morales", "Forward Deployed Engineer", "fde", "-0700"),
        ("hana", "Hana Nguyen", "Support Engineer", "support", "+0700"),
        ("tom", "Tom Becker", "Account Executive", "sales", "-0500"),
        ("priya_m", "Priya Menon", "Solutions Architect", "solutions", "-0500"),
        ("alex", "Alex Duong", "Engineering Manager", "eng_manager", "+0700"),
        ("carla", "Carla Ruiz", "Compliance & Security Lead", "compliance", "-0700"),
        ("dan", "Dan Okafor", "Billing & Finance Operations", "finance", "-0500"),
        ("mai", "Mai Le", "Implementation Manager", "implementation", "+0700"),
        ("rebecca", "Rebecca Stone", "VP, Customer Success", "vp_cs", "-0700"),
    ]
    for key, name, title, role, tz in internal:
        lang = "vi" if tz == "+0700" else "en"
        person(key, name, "anduin", title, "internal", role, lang=lang, tz=tz)

    # Customers and their counterparts.
    org("meridian", "Meridian Growth Partners", "meridiangrowth.example", "customer")
    org(
        "whitmore",
        "Whitmore & Hale LLP",
        "whitmorehale.example",
        "counsel",
        DISCLAIMER_LAW,
    )
    org("northstar", "Northstar Fund Services", "northstarfs.example", "administrator")
    org("crestline", "Crestline Real Estate Fund", "crestlinere.example", "customer")
    org("pryce", "Pryce Dunmore LLP", "prycedunmore.example", "counsel", DISCLAIMER_LAW)
    org("blueridge", "Blue Ridge Family Office", "blueridgefo.example", "customer")
    org("tidewater", "Tidewater Capital", "tidewatercap.example", "customer")
    org("lotus", "Lotus Pacific Ventures", "lotuspacific.example", "customer")
    org("summit", "Summit Peak Partners", "summitpeak.example", "customer")
    org("granite", "Granite Bay Infrastructure", "granitebay.example", "customer")
    org("silverleaf", "Silverleaf Ventures", "silverleafvc.example", "customer")
    org("meridianh", "Meridian Health Systems", "meridianhealth.example", "customer")
    org("kestrel", "Kestrel Pension Trust", "kestrelpension.example", "other")

    c = "customer"
    person("rachel", "Rachel Ng", "meridian", "COO", c, "client", tz="-0800")
    person(
        "victor",
        "Victor Salazar",
        "meridian",
        "Managing Partner",
        c,
        "client",
        tz="-0800",
    )
    person(
        "beth", "Beth Alvarez", "meridian", "Fund Controller", c, "client", tz="-0800"
    )
    person(
        "gregory",
        "Gregory Hale",
        "whitmore",
        "Partner",
        "third_party",
        "counsel",
        tz="-0500",
    )
    person(
        "priya_r",
        "Priya Raman",
        "northstar",
        "Senior Fund Accountant",
        "third_party",
        "administrator",
        tz="-0500",
    )
    person("owen", "Owen Brandt", "crestline", "CFO", c, "client", tz="-0600")
    person(
        "dana",
        "Dana Whitaker",
        "crestline",
        "Director of Investor Relations",
        c,
        "client",
        tz="-0600",
    )
    person(
        "marcus", "Marcus Lee", "crestline", "Fund Controller", c, "client", tz="-0600"
    )
    person(
        "elaine",
        "Elaine Pryce",
        "pryce",
        "Associate",
        "third_party",
        "counsel",
        tz="-0600",
    )
    person(
        "helen",
        "Helen Marsh",
        "blueridge",
        "Chief Investment Officer",
        c,
        "client",
        tz="-0500",
    )
    person(
        "arjun",
        "Arjun Patel",
        "blueridge",
        "Head of Operations",
        c,
        "client",
        tz="-0500",
    )
    person("colin", "Colin Reese", "blueridge", "IT Director", c, "client", tz="-0500")
    person(
        "sofia",
        "Sofia Marchetti",
        "tidewater",
        "General Counsel & CCO",
        c,
        "client",
        tz="-0500",
    )
    person("nate", "Nate Holloway", "tidewater", "COO", c, "client", tz="-0500")
    person(
        "ines",
        "Ines Duarte",
        "tidewater",
        "Head of Investor Relations",
        c,
        "client",
        tz="-0500",
    )
    person(
        "bao",
        "Trần Quốc Bảo",
        "lotus",
        "Managing Partner",
        c,
        "client",
        lang="vi",
        tz="+0700",
        aliases=("Quoc Bao", "Bảo"),
        email="bao.tran",
    )
    person(
        "ha",
        "Lê Thu Hà",
        "lotus",
        "Fund Administration Manager",
        c,
        "client",
        lang="vi",
        tz="+0700",
        aliases=("Thu Ha", "Hà"),
        email="ha.le",
    )
    person(
        "chau",
        "Nguyễn Minh Châu",
        "lotus",
        "Legal Counsel",
        c,
        "client",
        lang="vi",
        tz="+0700",
        aliases=("Minh Chau", "Châu"),
        email="chau.nguyen",
    )
    person("greg", "Greg Lindqvist", "summit", "CFO", c, "client", tz="-0500")
    person(
        "tara", "Tara Quinn", "summit", "Operations Manager", c, "client", tz="-0500"
    )
    person("leah", "Leah Kowalski", "granite", "CFO", c, "client", tz="-0600")
    person(
        "rohan",
        "Rohan Mehta",
        "granite",
        "Fund Operations Lead",
        c,
        "client",
        tz="-0600",
    )
    person(
        "noor",
        "Noor Haddad",
        "silverleaf",
        "Operations Associate",
        c,
        "client",
        tz="-0800",
    )
    person(
        "pete",
        "Pete Gallagher",
        "meridianh",
        "IT Administrator",
        c,
        "client",
        tz="-0500",
    )
    person(
        "kestrel_ir",
        "Walter Osei",
        "kestrel",
        "Investment Operations",
        "third_party",
        "investor",
        tz="-0500",
    )
    return w


def _ascii(name: str) -> str:
    folded = unicodedata.normalize("NFD", name.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in folded if unicodedata.category(c) != "Mn")


LP_FIRST = [
    "Aurora",
    "Beacon",
    "Cobalt",
    "Delphi",
    "Evergreen",
    "Fairview",
    "Granville",
    "Halcyon",
    "Ironwood",
    "Juniper",
    "Keystone",
    "Larkspur",
    "Montclair",
    "Northgate",
    "Oakmont",
    "Pinecrest",
    "Quarry",
    "Redwood",
    "Sterling",
    "Tamarack",
]
LP_KIND = [
    "Pension Fund",
    "Family Trust",
    "Endowment",
    "Foundation",
    "Capital LLC",
    "Holdings Ltd",
    "Retirement Plan",
    "Partners LP",
]


def lp_names(rng: random.Random, n: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    while len(out) < n:
        name = f"{rng.choice(LP_FIRST)} {rng.choice(LP_KIND)}"
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def signature(w: World, p: Person) -> str:
    lines = [p.name, f"{p.title}, {p.org}"]
    if p.phone and p.side != "third_party" or p.role in ("counsel", "administrator"):
        lines.append(p.phone)
    lines.append(p.email)
    return "\n".join(lines)
