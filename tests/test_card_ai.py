"""AI layer: graceful disable + structured-output parsing (mocked Claude)."""
import io
import sys
import types

import pytest
from PIL import Image

from tcg.card_ai import AIUnavailable, identify_card
from tcg.config import Settings


def _img():
    return Image.new("RGB", (80, 120), (10, 80, 200))


def test_disabled_without_api_key():
    s = Settings(anthropic_api_key=None)
    with pytest.raises(AIUnavailable):
        identify_card(_img(), s)


class _ToolUse:
    type = "tool_use"
    name = "report_card"

    def __init__(self, data):
        self.input = data


class _Resp:
    def __init__(self, data):
        self.content = [_ToolUse(data)]


def _fake_anthropic(monkeypatch, data):
    """Install a fake `anthropic` module returning a forced tool call."""
    mod = types.ModuleType("anthropic")

    class APIError(Exception):
        pass

    class APIStatusError(APIError):
        def __init__(self, status_code=500, message="err"):
            self.status_code = status_code
            self.message = message

    class Anthropic:
        def __init__(self, *a, **k):
            self.messages = types.SimpleNamespace(create=lambda **kw: _Resp(data))

    mod.Anthropic = Anthropic
    mod.APIError = APIError
    mod.APIStatusError = APIStatusError
    monkeypatch.setitem(sys.modules, "anthropic", mod)


def test_parses_structured_card(monkeypatch):
    _fake_anthropic(monkeypatch, {
        "year": "2018", "brand": "Topps", "set_name": "Chrome",
        "player": "Shohei Ohtani", "card_number": "150", "is_rookie": True,
        "ebay_title": "2018 Topps Chrome Shohei Ohtani Rookie RC #150 Angels",
        "description": "Sharp rookie card.", "search_query": "2018 Topps Chrome Shohei Ohtani Rookie",
        "confidence": 0.92, "condition": "Raw",
    })
    s = Settings(anthropic_api_key="sk-test")
    identity, listing = identify_card(_img(), s)
    assert identity.player == "Shohei Ohtani"
    assert identity.is_rookie is True
    assert identity.confidence == 0.92
    assert listing.search_query.startswith("2018 Topps Chrome")
    assert len(listing.ebay_title) <= 80


def test_string_confidence_is_coerced(monkeypatch):
    # The SDK does not type-coerce tool inputs; a string must not crash the UI.
    _fake_anthropic(monkeypatch, {
        "year": "2020", "brand": "Topps", "player": "Y",
        "ebay_title": "t", "description": "d", "search_query": "q",
        "confidence": "0.8",          # string, not number
    })
    s = Settings(anthropic_api_key="sk-test")
    identity, _ = identify_card(_img(), s)
    assert isinstance(identity.confidence, float)
    assert identity.confidence == 0.8


def test_garbage_confidence_defaults_to_zero(monkeypatch):
    _fake_anthropic(monkeypatch, {
        "year": "2020", "brand": "Topps", "player": "Y",
        "ebay_title": "t", "description": "d", "search_query": "q",
        "confidence": "very sure",    # unparseable
    })
    s = Settings(anthropic_api_key="sk-test")
    identity, _ = identify_card(_img(), s)
    assert identity.confidence == 0.0


def test_title_truncated_to_80(monkeypatch):
    _fake_anthropic(monkeypatch, {
        "year": "2018", "brand": "Topps", "player": "X",
        "ebay_title": "Z" * 200, "description": "d",
        "search_query": "q", "confidence": 0.5,
    })
    s = Settings(anthropic_api_key="sk-test")
    _, listing = identify_card(_img(), s)
    assert len(listing.ebay_title) == 80
