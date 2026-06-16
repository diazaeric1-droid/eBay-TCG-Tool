"""Card identification via Claude vision (paid) or Ollama (free, local).

Engine selection
---------------
1. **Claude** — used when ``ANTHROPIC_API_KEY`` is set.  Best quality; requires
   an Anthropic account.
2. **Ollama** — used when ``OLLAMA_BASE_URL`` is set (e.g.
   ``http://localhost:11434``).  Completely free; needs a local Ollama install
   with a vision-capable model pulled (``ollama pull llava``).

If neither is configured, ``identify_card`` raises ``AIUnavailable`` and the
UI falls back to manual entry (130point comps are still real).
"""
from __future__ import annotations

import json as _json
import re
from typing import Tuple

import requests as _req

from .config import Settings
from .images import to_jpeg_b64
from .models import CardIdentity, GeneratedListing

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore


class AIUnavailable(RuntimeError):
    """Neither an API key nor a local Ollama backend is configured."""


class AIError(RuntimeError):
    """The AI call failed (network, auth, rate limit, refusal, malformed output)."""


# --------------------------------------------------------------------------- #
# Claude prompt / tool definition (unchanged from original)
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = (
    "You are an expert sports- and trading-card cataloguer who lists cards on eBay. "
    "From the image, identify the card as precisely as you can and produce a sell-ready "
    "listing. Read the actual text on the card; never invent details you cannot see. "
    "If the card is in a grading slab (PSA/BGS/SGC/CGC), capture the grader, the numeric "
    "grade, and the cert number if legible. The eBay title MUST be 80 characters or fewer "
    "and should front-load the highest-signal keywords a buyer would search: "
    "year, brand/set, player, parallel/insert, card number, and notable attributes "
    "(RC, Auto, /numbering, grade). The search_query should be the concise phrase that "
    "best retrieves comparable sales (no condition words, no '#', no punctuation noise). "
    "Set confidence to your honest 0-1 certainty about the identification."
)

CARD_TOOL = {
    "name": "report_card",
    "description": "Report the identified card and the generated eBay listing.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sport": {"type": "string", "description": "e.g. Baseball, Basketball, Pokemon"},
            "year": {"type": "string"},
            "brand": {"type": "string", "description": "e.g. Topps, Panini, Bowman"},
            "set_name": {"type": "string", "description": "e.g. Chrome, Prizm, Heritage"},
            "player": {"type": "string", "description": "player / subject / character"},
            "team": {"type": "string"},
            "card_number": {"type": "string"},
            "parallel": {"type": "string", "description": "e.g. Refractor, Silver, Gold /50"},
            "insert": {"type": "string", "description": "insert/subset name, if any"},
            "attributes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "tags like Rookie, Auto, Patch, Numbered",
            },
            "is_rookie": {"type": "boolean"},
            "is_autograph": {"type": "boolean"},
            "is_numbered": {"type": "boolean"},
            "serial": {"type": "string", "description": "e.g. 12/50 if serial-numbered"},
            "is_graded": {"type": "boolean"},
            "grader": {"type": "string", "description": "PSA, BGS, SGC, CGC or empty"},
            "grade": {"type": "string", "description": "numeric grade or empty"},
            "condition": {"type": "string", "description": "Raw, or 'PSA 10' style summary"},
            "confidence": {"type": "number", "description": "0..1 identification certainty"},
            "notes": {"type": "string", "description": "anything uncertain or notable"},
            "ebay_title": {"type": "string", "description": "<= 80 characters"},
            "description": {"type": "string", "description": "copy/paste-ready listing body"},
            "search_query": {"type": "string", "description": "phrase to retrieve comps"},
        },
        "required": [
            "year", "brand", "player", "ebay_title", "description",
            "search_query", "confidence",
        ],
    },
}

# --------------------------------------------------------------------------- #
# Ollama prompt (plain JSON — no tool-use protocol)
# --------------------------------------------------------------------------- #
OLLAMA_PROMPT = """\
You are an expert sports and trading card cataloguer who lists on eBay.
Study the card image carefully and read all text visible on it.
Never invent details you cannot see.

Respond with ONLY a JSON object — no markdown fences, no explanation, just raw JSON.

Required JSON fields:
  year         — card year, e.g. "2018"
  brand        — manufacturer, e.g. "Topps", "Panini", "Bowman"
  set_name     — set name, e.g. "Chrome", "Prizm", "Heritage"
  player       — player or character name
  team         — team name
  card_number  — card number, e.g. "150"
  sport        — e.g. "Baseball", "Basketball", "Pokemon"
  parallel     — parallel/variant name (e.g. "Refractor", "Gold /50") or ""
  is_rookie    — true if rookie card, else false
  is_autograph — true if signed, else false
  is_numbered  — true if serial-numbered, else false
  serial       — serial stamp, e.g. "12/50", or ""
  is_graded    — true if in a PSA/BGS/SGC/CGC slab, else false
  grader       — "PSA", "BGS", "SGC", "CGC", or ""
  grade        — numeric grade, e.g. "10", "9.5", or ""
  condition    — "Raw" or graded summary, e.g. "PSA 10"
  ebay_title   — MUST be ≤80 characters; front-load: year brand set player parallel card# attributes (RC/Auto/etc)
  description  — full copy-paste-ready eBay listing body
  search_query — concise phrase to find sold comps (no punctuation, no condition words)
  confidence   — number 0.0–1.0 reflecting identification certainty
  notes        — anything uncertain or notable, or ""

Example ebay_title (64 chars): "2018 Topps Chrome Shohei Ohtani Rookie RC #150 Angels Refractor"
"""


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def identify_card(
    image: "Image.Image", settings: Settings
) -> Tuple[CardIdentity, GeneratedListing]:
    """Return (identity, listing).

    Engine priority:
      1. Claude — if ``ANTHROPIC_API_KEY`` is set (highest quality)
      2. Ollama — if ``OLLAMA_BASE_URL`` is set (free, local, no key)

    Raises ``AIUnavailable`` if neither is configured.
    Raises ``AIError`` if a configured engine fails.
    """
    if settings.anthropic_api_key:
        return _identify_claude(image, settings)
    if settings.ollama_enabled:
        return _identify_ollama(image, settings)
    raise AIUnavailable(
        "No AI backend configured. "
        "Install Ollama (https://ollama.com) and set OLLAMA_BASE_URL=http://localhost:11434, "
        "or set ANTHROPIC_API_KEY for Claude."
    )


# --------------------------------------------------------------------------- #
# Claude backend
# --------------------------------------------------------------------------- #
def _identify_claude(
    image: "Image.Image", settings: Settings
) -> Tuple[CardIdentity, GeneratedListing]:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise AIError("The 'anthropic' package is not installed.") from exc

    b64, media_type = to_jpeg_b64(image, max_dim=settings.ai_image_max_dim)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    try:
        resp = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=[CARD_TOOL],
            tool_choice={"type": "tool", "name": "report_card"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Identify this card and generate the eBay listing. "
                                "Call report_card exactly once."
                            ),
                        },
                    ],
                }
            ],
        )
    except anthropic.APIStatusError as exc:
        raise AIError(f"Claude API error ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIError as exc:
        raise AIError(f"Claude API call failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise AIError(f"Unexpected error calling Claude: {exc}") from exc

    data = _first_tool_input(resp)
    if data is None:
        raise AIError("Model did not return a structured card report.")
    return _split(data)


# --------------------------------------------------------------------------- #
# Ollama backend
# --------------------------------------------------------------------------- #
def _identify_ollama(
    image: "Image.Image", settings: Settings
) -> Tuple[CardIdentity, GeneratedListing]:
    b64, _ = to_jpeg_b64(image, max_dim=settings.ai_image_max_dim)
    base = (settings.ollama_base_url or "").rstrip("/")
    # Vision models on CPU can be slow; use a generous timeout.
    timeout = max(120, settings.http_timeout * 6)

    try:
        resp = _req.post(
            f"{base}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": [
                    {
                        "role": "user",
                        "content": OLLAMA_PROMPT,
                        "images": [b64],
                    }
                ],
                "stream": False,
                "format": "json",
            },
            timeout=timeout,
        )
    except _req.exceptions.ConnectionError as exc:
        raise AIError(
            f"Cannot reach Ollama at {base}. "
            "Is Ollama running? Start it with: ollama serve"
        ) from exc
    except _req.RequestException as exc:
        raise AIError(f"Ollama request failed: {exc}") from exc

    if resp.status_code == 404:
        try:
            hint = resp.json().get("error", "")
        except Exception:
            hint = ""
        raise AIError(
            f"Ollama model '{settings.ollama_model}' not found. "
            f"Pull it first: ollama pull {settings.ollama_model}"
            + (f" ({hint})" if hint else "")
        )

    try:
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
    except (KeyError, ValueError, _req.HTTPError) as exc:
        raise AIError(f"Unexpected Ollama response: {exc}") from exc

    data = _extract_json(content)
    if not data:
        raise AIError(
            "Ollama did not return a parseable JSON card report. "
            "Try a better vision model such as llava:13b or llava-phi3."
        )
    return _split(data)


def _extract_json(text: str) -> dict | None:
    """Extract the first JSON object from text (handles prose-wrapped output)."""
    text = (text or "").strip()
    try:
        result = _json.loads(text)
        if isinstance(result, dict):
            return result
    except (ValueError, TypeError):
        pass
    # Fallback: grab first {...} block from prose-wrapped output
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            result = _json.loads(m.group(0))
            if isinstance(result, dict):
                return result
        except (ValueError, TypeError):
            pass
    return None


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _first_tool_input(resp) -> dict | None:
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "report_card":
            return dict(block.input)
    return None


def _split(data: dict) -> Tuple[CardIdentity, GeneratedListing]:
    title = (data.get("ebay_title") or "").strip()
    if len(title) > 80:
        title = title[:80].rstrip()
    identity = CardIdentity.from_dict(data)
    # The SDK / Ollama JSON may not type-coerce numbers; normalise so the UI
    # can always format confidence as a percentage without crashing.
    try:
        identity.confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        identity.confidence = 0.0
    listing = GeneratedListing(
        ebay_title=title,
        description=(data.get("description") or "").strip(),
        suggested_condition=(data.get("condition") or "Raw").strip() or "Raw",
        search_query=(data.get("search_query") or "").strip(),
    )
    return identity, listing
