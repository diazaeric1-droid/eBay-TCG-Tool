"""Turn raw comps into a defensible valuation.

The original app hard-coded ``Estimated_Value = "$85.00"``. Here the estimate is
derived from real sold comps with outlier-robust statistics, an interquartile
range, and a confidence rating driven by sample size and price dispersion.
"""
from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from .models import Comp, PriceReport, Valuation
from .sources import DemoSource, EbaySource, OnePointSource, SourceError


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolation percentile (pct in 0..100)."""
    if not sorted_vals:
        raise ValueError("empty")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _trimmed_mean(sorted_vals: list[float], trim: float = 0.1) -> float:
    n = len(sorted_vals)
    k = int(n * trim)
    core = sorted_vals[k : n - k] if n - 2 * k >= 1 else sorted_vals
    return statistics.fmean(core)


def _recency_filter(comps: list[Comp], days: Optional[int]) -> list[Comp]:
    if not days:
        return comps
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    kept = []
    for c in comps:
        if not c.sale_date:
            kept.append(c)  # keep undated rather than silently drop
            continue
        try:
            ts = datetime.fromisoformat(c.sale_date).timestamp()
        except ValueError:
            kept.append(c)
            continue
        if ts >= cutoff:
            kept.append(c)
    return kept


def valuate(
    sold_comps: list[Comp],
    currency: str = "USD",
    recency_days: Optional[int] = None,
) -> Valuation:
    """Compute a valuation from sold comps in a single currency."""
    notes: list[str] = []

    usable = [c for c in sold_comps if c.listing_type == "sold" and c.price and c.price > 0]
    # Restrict to the dominant currency to avoid mixing unconverted FX.
    if usable:
        currencies = Counter(c.currency for c in usable)
        currency = currencies.most_common(1)[0][0]
        dropped = [c for c in usable if c.currency != currency]
        if dropped:
            notes.append(
                f"Excluded {len(dropped)} comp(s) in other currencies (no FX conversion)."
            )
        usable = [c for c in usable if c.currency == currency]

    if recency_days:
        before = len(usable)
        usable = _recency_filter(usable, recency_days)
        if len(usable) < before:
            notes.append(
                f"Filtered to last {recency_days} days ({before} -> {len(usable)} comps)."
            )

    prices = sorted(c.price for c in usable)
    n = len(prices)
    if n == 0:
        return Valuation(currency=currency, n=0, confidence="none",
                         basis="No usable sold comps.", notes=notes)

    median = statistics.median(prices)
    tmean = _trimmed_mean(prices)
    p25 = _percentile(prices, 25)
    p75 = _percentile(prices, 75)
    stdev = statistics.pstdev(prices) if n > 1 else 0.0

    # Headline estimate: median (robust to the auction-sniped highs/lows).
    estimate = round(median, 2)
    # Range: interquartile when there are enough comps to be meaningful; otherwise
    # fall back to min..max (and label it honestly — never call min..max "IQR").
    if n == 1:
        low, high, range_kind = estimate, estimate, "single sale"
    elif n >= 4:
        low, high, range_kind = round(p25, 2), round(p75, 2), "IQR (p25–p75)"
    else:
        low, high, range_kind = round(prices[0], 2), round(prices[-1], 2), "min–max"

    cv = (stdev / median) if median else 0.0  # coefficient of variation
    confidence = _confidence(n, cv)

    return Valuation(
        estimate=estimate,
        low=low,
        high=high,
        currency=currency,
        n=n,
        median=round(median, 2),
        trimmed_mean=round(tmean, 2),
        p25=round(p25, 2),
        p75=round(p75, 2),
        minimum=round(prices[0], 2),
        maximum=round(prices[-1], 2),
        stdev=round(stdev, 2),
        confidence=confidence,
        range_kind=range_kind,
        basis=f"{n} sold comp(s) from 130point; estimate = median, range = {range_kind}.",
        notes=notes,
    )


def _confidence(n: int, cv: float) -> str:
    if n == 0:
        return "none"
    if n >= 12 and cv < 0.35:
        return "high"
    if n >= 5 and cv < 0.6:
        return "medium"
    return "low"


class PricingEngine:
    """Gathers comps from the configured sources and computes a report."""

    def __init__(
        self,
        onepoint: Optional[OnePointSource] = None,
        ebay: Optional[EbaySource] = None,
        comp_limit: int = 40,
    ):
        self.onepoint = onepoint or OnePointSource()
        self.ebay = ebay
        self.comp_limit = comp_limit

    def build_report(
        self,
        query: str,
        recency_days: Optional[int] = None,
        allow_demo_fallback: bool = False,
    ) -> PriceReport:
        report = PriceReport(query=query)

        # --- sold comps (130point, real) ---
        try:
            report.sold_comps = self.onepoint.search_sold(query, limit=self.comp_limit)
            if report.sold_comps:
                report.sources_used.append("130point (sold)")
            else:
                report.warnings.append("130point returned no sold comps for this query.")
        except SourceError as exc:
            report.warnings.append(str(exc))
            if allow_demo_fallback:
                report.sold_comps = DemoSource.sold(query)
                report.sources_used.append("DEMO (simulated sold)")

        # --- active comps (eBay Browse, optional) ---
        if self.ebay and self.ebay.enabled:
            try:
                report.active_comps = self.ebay.search_active(query, limit=20)
                if report.active_comps:
                    report.sources_used.append("eBay Browse (active)")
            except SourceError as exc:
                report.warnings.append(str(exc))
        else:
            report.warnings.append(
                "eBay Browse API not configured — active comps unavailable "
                "(set EBAY_CLIENT_ID / EBAY_CLIENT_SECRET)."
            )

        report.valuation = valuate(report.sold_comps, recency_days=recency_days)
        return report
