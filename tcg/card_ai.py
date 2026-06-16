"""Claude vision: identify a card from a photo and draft the listing copy.

The original app only *simulated* this. Here we send the image to Claude
(Opus 4.8 by default) and force a single structured tool call so the result is a
validated object — no brittle JSON-from-prose parsing, which also makes this
robust across SDK versions.

If no ``ANTHROPIC_API_KEY`` is configured, ``identify_card`` raises
``AIUnavailable`` and the UI falls back to manual entry (comps are still real).
"""
from __future__ import annotations

from typing import Tuple

from .config import Settings
from .images import to_jpeg_b64
from .models import CardIdentity, GeneratedListing

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore


class AIUnavailable(RuntimeError):
    """No API key configured — AI identification is disabled."""


class AIError(RuntimeError):
    """The AI call failed (network, auth, rate limit, refusal, malformed output)."""


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


def identify_card(
    image: "Image.Image", settings: Settings
) -> Tuple[CardIdentity, GeneratedListing]:
    """Return (identity, listing). Raises AIUnavailable / AIError on failure."""
    if not settings.ai_enabled:
        raise AIUnavailable("ANTHROPIC_API_KEY is not set.")

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
    except Exception as exc:  # noqa: BLE001 - surface anything else cleanly
        raise AIError(f"Unexpected error calling Claude: {exc}") from exc

    data = _first_tool_input(resp)
    if data is None:
        raise AIError("Model did not return a structured card report.")
    return _split(data)


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
    # The model declares confidence as a number, but tool inputs are not type-coerced
    # by the SDK — normalize so the UI can always format it as a percentage.
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
