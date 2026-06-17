"""Plain, JSON-serializable dataclasses shared across the layers.

Keeping these free of any Streamlit / network / SDK imports makes every other
module trivially unit-testable and keeps the data contract explicit.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional


@dataclass
class CardIdentity:
    """Structured facts about a single card, as identified from an image."""

    sport: str = ""
    year: str = ""
    brand: str = ""           # e.g. Topps, Panini, Bowman
    set_name: str = ""        # e.g. Chrome, Prizm, Heritage
    player: str = ""          # subject / athlete
    team: str = ""
    card_number: str = ""
    parallel: str = ""        # e.g. Refractor, Silver, Gold /50
    insert: str = ""          # insert/subset name if applicable
    attributes: list[str] = field(default_factory=list)  # Rookie, Auto, Patch...
    is_rookie: bool = False
    is_autograph: bool = False
    is_numbered: bool = False
    serial: str = ""          # e.g. "12/50"
    is_graded: bool = False
    grader: str = ""          # PSA, BGS, SGC, CGC
    grade: str = ""           # e.g. "10", "9.5"
    condition: str = "Raw"    # Raw, or grader+grade summary
    confidence: float = 0.0   # 0..1 model self-reported confidence
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CardIdentity":
        return cls(**{k: v for k, v in (d or {}).items() if k in _field_names(cls)})


@dataclass
class GeneratedListing:
    """The user-facing listing copy produced for a card."""

    ebay_title: str = ""              # <= 80 chars, eBay's hard limit
    description: str = ""
    suggested_condition: str = "Raw"
    search_query: str = ""            # the query used to pull comps

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GeneratedListing":
        return cls(**{k: v for k, v in (d or {}).items() if k in _field_names(cls)})


@dataclass
class Comp:
    """A single comparable sale or active listing."""

    title: str
    price: float
    currency: str = "USD"
    listing_type: str = "sold"        # "sold" | "active"
    source: str = ""                  # "130point", "ebay", "demo"
    sale_date: Optional[str] = None   # ISO 8601 string (sold comps)
    url: str = ""
    image_url: str = ""
    sale_kind: str = ""               # Auction, Buy It Now, Best Offer...
    bids: Optional[int] = None
    shipping: Optional[float] = None
    condition: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Comp":
        kw = {k: v for k, v in (d or {}).items() if k in _field_names(cls)}
        kw.setdefault("title", "")          # tolerate partial dicts (required fields)
        kw.setdefault("price", 0.0)
        return cls(**kw)


@dataclass
class PsaCert:
    """Verified facts for a PSA-graded slab, from the PSA public cert API."""

    cert_number: str = ""
    spec_id: Optional[int] = None
    year: str = ""
    brand: str = ""               # e.g. "YU-GI-OH! RISE OF DESTINY: SPECIAL EDITION"
    category: str = ""            # e.g. "TCG Cards"
    card_number: str = ""         # e.g. "ENSE2"
    subject: str = ""             # e.g. "DARK MAGICIAN GIRL"
    variety: str = ""             # e.g. "SPECIAL EDITION"
    grade: str = ""               # e.g. "VG 3", "GEM MT 10"
    total_population: Optional[int] = None       # copies graded at this exact grade
    population_higher: Optional[int] = None       # copies graded higher
    print_run: str = ""           # serial-number denominator, e.g. "250" — read off
                                  # the card face (PSA's API does not return it)
    is_dna: bool = False          # autograph authentication slab
    valid: bool = True            # False when the cert lookup returned nothing usable

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PsaCert":
        return cls(**{k: v for k, v in (d or {}).items() if k in _field_names(cls)})

    @property
    def grader(self) -> str:
        return "PSA"

    def search_query(self) -> str:
        """Concise phrase to retrieve comps for this exact graded card."""
        parts = [self.year, self.brand, self.subject, self._distinct_variety,
                 self._print_run_token, "PSA", _grade_number(self.grade)]
        seen: set[str] = set()
        out: list[str] = []
        for p in parts:
            p = (p or "").strip()
            if not p:
                continue
            key = p.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        return " ".join(out)

    @property
    def condition(self) -> str:
        """e.g. 'PSA VG 3' — for the listing's condition field."""
        g = (self.grade or "").strip()
        return f"PSA {g}" if g else "PSA Graded"

    @property
    def _print_run_token(self) -> str:
        """The print run as a search-friendly ``/250`` token (blank if unset).

        PSA's API never returns the serial number, so this is populated from the
        card face. Buyers search the denominator (``/250``), so we surface it in
        the title and description when known.
        """
        import re
        raw = (self.print_run or "").strip()
        # A full serial ("074/250") carries the denominator after the slash;
        # a bare value ("250") is the denominator itself.
        denom = raw.rsplit("/", 1)[-1] if "/" in raw else raw
        pr = re.sub(r"\D", "", denom)
        return f"/{pr}" if pr else ""

    @property
    def _distinct_variety(self) -> str:
        """The variety, but blank when the brand already contains it.

        PSA often repeats the variety inside the brand (brand
        ``POKEMON BLACK STAR PROMO`` + variety ``BLACK STAR PROMO``), which
        would otherwise double the phrase in titles/queries.
        """
        v = (self.variety or "").strip()
        if not v or v.lower() in (self.brand or "").lower():
            return ""
        return v

    def listing_title(self) -> str:
        """A title-cased, ≤80-char eBay title built from the verified slab.

        eBay caps titles at 80 chars and some brand strings (e.g. PSA's verbose
        ``YU-GI-OH! RISE OF DESTINY: SPECIAL EDITION``) are long enough to blow
        the budget on their own. So instead of truncating — which can chop off
        the grade, the single most important token for a graded card — we keep
        the highest-signal tokens first and only add the rest if they fit.
        """
        num = f"#{self.card_number}" if self.card_number else ""
        variety = _titlecase(self._distinct_variety)
        run = self._print_run_token
        display = [self.year, _titlecase(self.subject), num,
                   _titlecase(self.brand), variety, run, self.condition]
        # Most-important first: grade, subject, year are always kept if possible.
        # The print run is a strong value/search signal, so it ranks above the
        # long brand string and the card number.
        priority = [self.condition, _titlecase(self.subject), self.year, run,
                    _titlecase(self.brand), num, variety]
        keep: set[str] = set()
        used = 0
        for tok in priority:
            tok = (tok or "").strip()
            if not tok or tok in keep:
                continue
            cost = len(tok) + (1 if used else 0)
            if used + cost <= 80:
                keep.add(tok)
                used += cost
        title = " ".join(t for t in display if (t or "").strip() and t in keep)
        return title[:80].rstrip()

    def listing_description(self) -> str:
        """A copy-ready description body built from the verified slab."""
        num = f" #{self.card_number}" if self.card_number else ""
        lines = [
            f"{self.year} {_titlecase(self.brand)}".strip(),
            f"{_titlecase(self.subject)}{num}".strip(),
        ]
        variety_line = _titlecase(self._distinct_variety)
        run = self._print_run_token
        if variety_line and run:
            lines.append(f"{variety_line} {run}")
        elif variety_line:
            lines.append(variety_line)
        elif run:
            lines.append(f"Serial-numbered {run}")
        lines.append(f"{self.condition} — cert #{self.cert_number}")
        pop = []
        if self.total_population is not None:
            pop.append(f"{self.total_population:,} at this grade")
        if self.population_higher is not None:
            pop.append(f"{self.population_higher:,} graded higher")
        if pop:
            lines.append("PSA population: " + ", ".join(pop))
        lines.append("")
        # No URLs here — eBay flags external links in listings as a policy
        # violation. Reference the cert by number only.
        lines.append(
            f"Authenticated and graded by PSA — cert #{self.cert_number}, "
            f"verifiable on PSA's website by cert number."
        )
        return "\n".join(lines)


def _grade_number(grade: str) -> str:
    """'VG 3' -> '3', 'GEM MT 10' -> '10', '9.5' -> '9.5'."""
    import re
    m = re.search(r"(\d+(?:\.\d+)?)", grade or "")
    return m.group(1) if m else ""


def _titlecase(s: str) -> str:
    """Title-case PSA's ALL-CAPS fields without mangling tokens like 'PSA'/'RC'.

    ``str.title()`` capitalizes the letter after an apostrophe ("SURGE'S" ->
    "Surge'S"); card text apostrophes are possessives, so we lower that back
    down ("Surge's").
    """
    import re
    s = (s or "").strip()
    if not s:
        return ""
    keep = {"RC", "PSA", "BGS", "SGC", "CGC", "SP", "SSP", "GU", "USA", "II", "III"}
    out = []
    for w in s.split():
        if w.upper() in keep:
            out.append(w)
            continue
        w = w.title()
        # str.title() over-capitalizes after apostrophes ("Surge'S") and
        # ordinals ("1St"); card text wants "Surge's" and "1st".
        w = re.sub(r"'([A-Za-z])", lambda m: "'" + m.group(1).lower(), w)
        w = re.sub(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), w)
        out.append(w)
    return " ".join(out)


@dataclass
class Valuation:
    """A defensible estimate derived from a set of sold comps."""

    estimate: Optional[float] = None
    low: Optional[float] = None
    high: Optional[float] = None
    currency: str = "USD"
    n: int = 0
    median: Optional[float] = None
    trimmed_mean: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    stdev: Optional[float] = None
    confidence: str = "none"          # none | low | medium | high
    range_kind: str = ""              # what low..high represents (IQR / min-max / single)
    basis: str = ""                   # human description of what fed the estimate
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Valuation":
        return cls(**{k: v for k, v in (d or {}).items() if k in _field_names(cls)})


@dataclass
class PriceReport:
    """Everything the pricing engine produced for one query."""

    query: str = ""
    valuation: Valuation = field(default_factory=Valuation)
    sold_comps: list[Comp] = field(default_factory=list)
    active_comps: list[Comp] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "valuation": self.valuation.to_dict(),
            "sold_comps": [c.to_dict() for c in self.sold_comps],
            "active_comps": [c.to_dict() for c in self.active_comps],
            "sources_used": list(self.sources_used),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PriceReport":
        d = d or {}
        return cls(
            query=d.get("query", ""),
            valuation=Valuation.from_dict(d.get("valuation", {})),
            sold_comps=[Comp.from_dict(c) for c in d.get("sold_comps", [])],
            active_comps=[Comp.from_dict(c) for c in d.get("active_comps", [])],
            sources_used=list(d.get("sources_used", [])),
            warnings=list(d.get("warnings", [])),
        )


def _field_names(cls) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
