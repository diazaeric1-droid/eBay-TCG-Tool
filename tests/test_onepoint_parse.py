"""Parse the captured 130point response with no network access."""
from pathlib import Path

from tcg.sources import OnePointSource

FIXTURE = Path(__file__).parent / "fixtures" / "onepoint_sample.html"


def test_parses_real_sold_comps():
    comps = OnePointSource.parse(FIXTURE.read_text())
    assert len(comps) >= 1
    for c in comps:
        assert c.listing_type == "sold"
        assert c.source == "130point"
        assert c.price > 0
        assert c.title
        assert c.currency


def test_extracts_price_date_and_link():
    comps = OnePointSource.parse(FIXTURE.read_text())
    first = comps[0]
    assert isinstance(first.price, float)
    assert first.url.startswith("http")
    # The fixture rows carry GMT timestamps -> ISO 8601 UTC strings.
    assert first.sale_date and first.sale_date.endswith("+00:00")


def test_empty_html_is_safe():
    assert OnePointSource.parse("") == []
    assert OnePointSource.parse("<html><body>nope</body></html>") == []
