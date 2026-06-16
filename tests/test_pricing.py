"""Valuation math — the part that carries financial risk."""
from datetime import datetime, timedelta, timezone

from tcg.models import Comp
from tcg.pricing import _percentile, valuate
from tcg.sources import EbaySource, _safe_url


def _sold(price, currency="USD", date=None):
    return Comp(title="x", price=price, currency=currency, listing_type="sold",
                source="130point", sale_date=date)


def test_percentile_interpolation():
    vals = [10, 20, 30, 40, 100]
    assert _percentile(vals, 25) == 20
    assert _percentile(vals, 50) == 30
    assert _percentile(vals, 75) == 40


def test_basic_valuation():
    comps = [_sold(p) for p in (10, 20, 30, 40, 100)]
    v = valuate(comps)
    assert v.n == 5
    assert v.estimate == 30           # median
    assert v.median == 30
    assert v.low == 20 and v.high == 40   # IQR
    assert v.range_kind == "IQR (p25–p75)"
    assert v.minimum == 10 and v.maximum == 100
    assert v.confidence in {"low", "medium", "high"}


def test_range_kind_honest_for_small_n():
    # 2-3 comps: range is min..max and must be labeled as such, never "IQR".
    v2 = valuate([_sold(10), _sold(40)])
    assert v2.range_kind == "min–max"
    assert v2.low == 10 and v2.high == 40
    v1 = valuate([_sold(25)])
    assert v1.range_kind == "single sale"
    assert v1.low == v1.high == 25


def test_empty_is_handled():
    v = valuate([])
    assert v.n == 0
    assert v.estimate is None
    assert v.confidence == "none"


def test_foreign_currency_excluded():
    comps = [_sold(10), _sold(20), _sold(30), _sold(9999, currency="EUR")]
    v = valuate(comps)
    assert v.currency == "USD"
    assert v.n == 3                    # EUR comp dropped
    assert any("other currencies" in n for n in v.notes)


def test_recency_filter():
    now = datetime.now(timezone.utc)
    recent = [_sold(50, date=(now - timedelta(days=5)).isoformat()) for _ in range(3)]
    old = [_sold(500, date=(now - timedelta(days=400)).isoformat()) for _ in range(3)]
    v = valuate(recent + old, recency_days=90)
    assert v.n == 3
    assert v.estimate == 50            # only recent comps survive


def test_high_confidence_when_many_tight_comps():
    comps = [_sold(p) for p in (98, 99, 100, 101, 102) * 3]  # n=15, tight
    v = valuate(comps)
    assert v.n == 15
    assert v.confidence == "high"


def test_ebay_browse_parser():
    payload = {
        "itemSummaries": [
            {
                "title": "2018 Topps Chrome Ohtani RC",
                "price": {"value": "129.99", "currency": "USD"},
                "itemWebUrl": "https://ebay.com/itm/1",
                "image": {"imageUrl": "https://img/1.jpg"},
                "buyingOptions": ["FIXED_PRICE"],
                "condition": "Ungraded",
                "shippingOptions": [{"shippingCost": {"value": "0.00"}}],
            },
            {"title": "no price", "price": {}},  # dropped
        ]
    }
    comps = EbaySource.parse_browse(payload)
    assert len(comps) == 1
    assert comps[0].price == 129.99
    assert comps[0].listing_type == "active"
    assert comps[0].shipping == 0.0


def test_safe_url_blocks_non_http():
    assert _safe_url("https://ebay.com/itm/1") == "https://ebay.com/itm/1"
    assert _safe_url("http://ebay.com/itm/1") == "http://ebay.com/itm/1"
    assert _safe_url("javascript:alert(1)") == ""
    assert _safe_url("data:text/html,<script>") == ""
    assert _safe_url(None) == ""
