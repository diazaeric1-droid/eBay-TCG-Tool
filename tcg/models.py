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
