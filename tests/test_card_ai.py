"""AI layer: graceful disable + structured-output parsing (mocked Claude/Ollama)."""
import io
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from tcg.card_ai import AIUnavailable, AIError, _extract_json, identify_card
from tcg.config import Settings


def _img():
    return Image.new("RGB", (80, 120), (10, 80, 200))


def test_disabled_without_api_key_or_ollama():
    s = Settings(anthropic_api_key=None, ollama_base_url=None)
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


# --------------------------------------------------------------------------- #
# Ollama backend
# --------------------------------------------------------------------------- #
_OLLAMA_DATA = {
    "year": "2020", "brand": "Panini", "set_name": "Prizm",
    "player": "LeBron James", "team": "Lakers",
    "card_number": "1", "sport": "Basketball",
    "is_rookie": False, "is_autograph": False, "is_numbered": False,
    "is_graded": False, "grader": "", "grade": "", "condition": "Raw",
    "parallel": "Silver", "serial": "", "notes": "",
    "ebay_title": "2020 Panini Prizm LeBron James Silver #1 Lakers",
    "description": "Sharp Prizm Silver of LeBron James.",
    "search_query": "2020 Panini Prizm LeBron James Silver",
    "confidence": 0.85,
}


def _fake_ollama_post(url, json=None, timeout=None, **kwargs):
    """Return a fake Ollama /api/chat response."""
    import json as _json
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"message": {"content": _json.dumps(_OLLAMA_DATA)}}
    resp.raise_for_status = lambda: None
    return resp


def test_ollama_identifies_card():
    s = Settings(anthropic_api_key=None, ollama_base_url="http://localhost:11434", ollama_model="llava")
    with patch("tcg.card_ai._req.post", side_effect=_fake_ollama_post):
        identity, listing = identify_card(_img(), s)
    assert identity.player == "LeBron James"
    assert identity.confidence == 0.85
    assert listing.search_query.startswith("2020 Panini Prizm")


def test_ollama_used_when_no_anthropic_key():
    """Ollama is the fallback when ANTHROPIC_API_KEY is absent."""
    s = Settings(anthropic_api_key=None, ollama_base_url="http://localhost:11434")
    with patch("tcg.card_ai._req.post", side_effect=_fake_ollama_post):
        identity, _ = identify_card(_img(), s)
    assert identity.player == "LeBron James"


def test_claude_preferred_over_ollama(monkeypatch):
    """When both are configured, Claude is used (not Ollama)."""
    _fake_anthropic(monkeypatch, {**_OLLAMA_DATA, "player": "FromClaude", "confidence": 0.99})
    s = Settings(anthropic_api_key="sk-test", ollama_base_url="http://localhost:11434")
    with patch("tcg.card_ai._req.post") as mock_post:
        identity, _ = identify_card(_img(), s)
    mock_post.assert_not_called()   # Ollama never touched
    assert identity.player == "FromClaude"


def test_ollama_model_not_found_gives_helpful_error():
    resp = MagicMock()
    resp.status_code = 404
    resp.json.return_value = {"error": "model 'llava' not found, try pulling it first"}
    resp.content = b'{"error": "..."}'
    s = Settings(anthropic_api_key=None, ollama_base_url="http://localhost:11434", ollama_model="llava")
    with patch("tcg.card_ai._req.post", return_value=resp):
        with pytest.raises(AIError, match="ollama pull llava"):
            identify_card(_img(), s)


def test_ollama_connection_refused_gives_helpful_error():
    import requests
    s = Settings(anthropic_api_key=None, ollama_base_url="http://localhost:11434")
    with patch("tcg.card_ai._req.post", side_effect=requests.exceptions.ConnectionError("refused")):
        with pytest.raises(AIError, match="ollama serve"):
            identify_card(_img(), s)


def test_extract_json_from_clean():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_from_prose():
    assert _extract_json('Here is the data:\n{"a": 1}\nDone.') == {"a": 1}


def test_extract_json_returns_none_on_garbage():
    assert _extract_json("not json at all") is None
