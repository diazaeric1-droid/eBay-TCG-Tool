"""Live market-data sources.

This module is what makes the tool *real*. The original app fabricated every
number; here we pull actual comparable sales.

Sources
-------
OnePointSource
    Sold comps from 130point.com's public sales-search backend
    (``https://back.130point.com/sales/``). 130point aggregates completed eBay
    (and other marketplace) sales — exactly the "past sold listings" the tool is
    supposed to use. No API key required.

EbaySource
    Active listings via eBay's official **Browse API**. Requires application
    credentials (client id/secret). This is the legitimate, ToS-compliant way to
    get current "similar active comps"; we deliberately do *not* scrape eBay's
    HTML search pages.

DemoSource
    Clearly-labelled synthetic comps, used only as an explicit, visible fallback
    when a live source is unreachable. Never presented as real data.

All network parsing functions are pure/static so they can be unit-tested against
saved HTML/JSON fixtures with no network access.
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .models import Comp

# Map a friendly marketplace toggle to 130point's internal "type" code.
# type=2 is the eBay sales feed (the community default).
ONEPOINT_URL = "https://back.130point.com/sales/"
ONEPOINT_EBAY_TYPE = 2
ONEPOINT_MAX_BYTES = 8_000_000  # guard against an unexpectedly huge response body


class SourceError(RuntimeError):
    """A data source was reachable-in-principle but failed this request."""


# --------------------------------------------------------------------------- #
# 130point — sold comps
# --------------------------------------------------------------------------- #
class OnePointSource:
    def __init__(self, timeout: int = 20, user_agent: Optional[str] = None):
        self.timeout = timeout
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )

    def search_sold(self, query: str, limit: int = 40) -> list[Comp]:
        query = (query or "").strip()
        if not query:
            return []
        headers = {
            "User-Agent": self.user_agent,
            "Origin": "https://130point.com",
            "Referer": "https://130point.com/sales/",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "*/*",
        }
        data = {
            "query": query,
            "type": str(ONEPOINT_EBAY_TYPE),
            "subcat": "-1",
            "sortBy": "",
        }
        try:
            resp = requests.post(
                ONEPOINT_URL, data=data, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise SourceError(f"130point request failed: {exc}") from exc

        if len(resp.content) > ONEPOINT_MAX_BYTES:
            raise SourceError("130point response was unexpectedly large; aborting.")

        comps = self.parse(resp.text)
        return comps[:limit]

    # -- pure parser (unit-tested against a fixture) ------------------------- #
    @staticmethod
    def parse(html: str) -> list[Comp]:
        soup = BeautifulSoup(html or "", "lxml")
        comps: list[Comp] = []
        for row in soup.find_all("tr", id="dRow"):
            price = _to_float(row.get("data-price"))
            if price is None or price <= 0:
                continue
            currency = (row.get("data-currency") or "USD").strip() or "USD"

            title, url = _onepoint_title(row)
            comps.append(
                Comp(
                    title=title,
                    price=price,
                    currency=currency,
                    listing_type="sold",
                    source="130point",
                    sale_date=_onepoint_date(row),
                    url=url,
                    image_url=_onepoint_image(row),
                    sale_kind=_clean(_text(row.find("span", id="auctionLabel"))),
                    bids=_onepoint_bids(row),
                    shipping=_onepoint_shipping(row),
                )
            )
        return comps


def _onepoint_title(row) -> tuple[str, str]:
    span = row.find("span", id="titleText")
    if span is None:
        return "(untitled sale)", ""
    a = span.find("a")
    if a is not None:
        return _clean(a.get_text()), _safe_url(a.get("href"))
    return _clean(span.get_text()), ""


def _onepoint_image(row) -> str:
    img = row.find("img")
    return (img.get("src") if img else "") or ""


def _onepoint_bids(row) -> Optional[int]:
    txt = _text(row.find("span", id="bidText"))
    m = re.search(r"Bids:\s*(\d+)", txt)
    return int(m.group(1)) if m else None


def _onepoint_shipping(row) -> Optional[float]:
    txt = _text(row.find("span", id="shipString"))
    m = re.search(r"([\d,]+\.\d{2})", txt)
    return _to_float(m.group(1)) if m else None


def _onepoint_date(row) -> Optional[str]:
    txt = _text(row.find("span", id="dateText"))
    if not txt:
        return None
    raw = re.sub(r"^\s*Date:\s*", "", txt).strip()
    # 130point format: "Fri 24 Apr 2026 01:57:00 GMT" (RFC-ish, no comma)
    for parser in (_parse_rfc, _parse_strptime):
        dt = parser(raw)
        if dt is not None:
            return dt.astimezone(timezone.utc).isoformat()
    return None


def _parse_rfc(raw: str) -> Optional[datetime]:
    try:
        # parsedate_to_datetime wants a comma after the weekday; add one.
        fixed = re.sub(r"^([A-Za-z]{3})\s+", r"\1, ", raw)
        return parsedate_to_datetime(fixed)
    except (TypeError, ValueError, IndexError):
        return None


def _parse_strptime(raw: str) -> Optional[datetime]:
    for fmt in ("%a %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=dt.tzinfo or timezone.utc)
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# eBay Browse API — active comps
# --------------------------------------------------------------------------- #
class EbaySource:
    """Active listings via eBay's official Browse API (client-credentials OAuth)."""

    def __init__(
        self,
        client_id: Optional[str],
        client_secret: Optional[str],
        env: str = "production",
        marketplace: str = "EBAY_US",
        timeout: int = 20,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.env = env
        self.marketplace = marketplace
        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def _base(self) -> str:
        return (
            "https://api.sandbox.ebay.com"
            if self.env == "sandbox"
            else "https://api.ebay.com"
        )

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        try:
            resp = requests.post(
                f"{self._base}/identity/v1/oauth2/token",
                auth=(self.client_id, self.client_secret),
                data={
                    "grant_type": "client_credentials",
                    "scope": "https://api.ebay.com/oauth/api_scope",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
            self._token = payload["access_token"]
            self._token_expiry = time.time() + int(payload.get("expires_in", 7200))
        except (requests.RequestException, KeyError, ValueError) as exc:
            raise SourceError(f"eBay OAuth failed: {exc}") from exc
        return self._token

    def search_active(self, query: str, limit: int = 20) -> list[Comp]:
        if not self.enabled:
            return []
        query = (query or "").strip()
        if not query:
            return []
        token = self._get_token()
        try:
            resp = requests.get(
                f"{self._base}/buy/browse/v1/item_summary/search",
                params={"q": query, "limit": str(min(limit, 50))},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-EBAY-C-MARKETPLACE-ID": self.marketplace,
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            raise SourceError(f"eBay Browse search failed: {exc}") from exc
        return self.parse_browse(payload)[:limit]

    @staticmethod
    def parse_browse(payload: dict) -> list[Comp]:
        comps: list[Comp] = []
        for item in (payload or {}).get("itemSummaries", []) or []:
            price = (item.get("price") or {})
            value = _to_float(price.get("value"))
            if value is None:
                continue
            ship = None
            opts = item.get("shippingOptions") or []
            if opts:
                ship = _to_float((opts[0].get("shippingCost") or {}).get("value"))
            comps.append(
                Comp(
                    title=_clean(item.get("title", "")),
                    price=value,
                    currency=price.get("currency", "USD") or "USD",
                    listing_type="active",
                    source="ebay",
                    url=_safe_url(item.get("itemWebUrl", "")),
                    image_url=(item.get("image") or {}).get("imageUrl", "") or "",
                    sale_kind=", ".join(item.get("buyingOptions", []) or []),
                    shipping=ship,
                    condition=item.get("condition", "") or "",
                )
            )
        return comps


# --------------------------------------------------------------------------- #
# Demo (clearly-labelled synthetic fallback)
# --------------------------------------------------------------------------- #
class DemoSource:
    """Deterministic, obviously-fake comps for offline UI demos.

    Output is always tagged ``source="demo"`` and titled "[SIMULATED] ..." so it
    can never be mistaken for real market data.
    """

    @staticmethod
    def _seed(query: str) -> int:
        return int(hashlib.sha256((query or "card").encode()).hexdigest()[:8], 16)

    @classmethod
    def sold(cls, query: str, n: int = 12) -> list[Comp]:
        seed = cls._seed(query)
        base = 20 + (seed % 180)  # a stable pseudo "market" price per query
        comps: list[Comp] = []
        now = datetime.now(timezone.utc)
        for i in range(n):
            jitter = ((seed >> (i % 16)) % 31) - 15  # +/-15
            price = max(1.0, round(base + jitter + i * 0.5, 2))
            comps.append(
                Comp(
                    title=f"[SIMULATED] {query} — sold comp #{i + 1}",
                    price=price,
                    currency="USD",
                    listing_type="sold",
                    source="demo",
                    sale_date=(now - timedelta(days=(n - i) * 7)).isoformat(),
                    sale_kind="Auction" if i % 2 else "Buy It Now",
                )
            )
        return comps

    @classmethod
    def active(cls, query: str, n: int = 4) -> list[Comp]:
        seed = cls._seed(query)
        base = 25 + (seed % 190)
        return [
            Comp(
                title=f"[SIMULATED] {query} — active listing #{i + 1}",
                price=max(1.0, round(base + i * 7.5, 2)),
                currency="USD",
                listing_type="active",
                source="demo",
                sale_kind="FIXED_PRICE",
            )
            for i in range(n)
        ]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _text(node) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _to_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _safe_url(url) -> str:
    """Only allow http(s) links through — a scraped/remote href is untrusted."""
    from urllib.parse import urlparse

    u = (url or "").strip()
    try:
        return u if urlparse(u).scheme in ("http", "https") else ""
    except ValueError:
        return ""
