"""Configuration & feature detection.

Settings come from (in order of precedence):
  1. Environment variables
  2. Streamlit secrets (``.streamlit/secrets.toml``), if running under Streamlit

Nothing here imports Streamlit at module load time, so the config layer stays
unit-testable. Streamlit secrets are read lazily and defensively.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Load a local ``.env`` (if present) so env-var settings work off-Streamlit.
# No-op when python-dotenv isn't installed or no .env exists — on Streamlit
# Cloud, secrets come from st.secrets instead.
try:  # pragma: no cover - trivial best-effort glue
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv()
except Exception:
    pass


def _secret(key: str) -> Optional[str]:
    """Best-effort read from Streamlit secrets; never raises off-Streamlit."""
    try:
        import streamlit as st  # local import: keep config importable without st
        # Accessing st.secrets off a Streamlit runtime raises; guard it.
        if key in st.secrets:  # type: ignore[operator]
            return str(st.secrets[key])
    except Exception:
        return None
    return None


def _get(key: str, default: Optional[str] = None) -> Optional[str]:
    val = os.environ.get(key)
    if val is not None and val != "":
        return val
    val = _secret(key)
    if val is not None and val != "":
        return val
    return default


def _get_int(key: str, default: int) -> int:
    raw = _get(key)
    try:
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    # --- AI (Claude vision) ---
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-opus-4-8"

    # --- AI (Ollama local vision — no key required) ---
    ollama_base_url: Optional[str] = None
    ollama_model: str = "qwen2.5vl:7b"

    # --- eBay Browse API (optional, for ACTIVE comps) ---
    ebay_client_id: Optional[str] = None
    ebay_client_secret: Optional[str] = None
    ebay_env: str = "production"          # production | sandbox
    ebay_marketplace: str = "EBAY_US"

    # --- PSA public API (optional: verify graded slabs by cert #) ---
    psa_api_token: Optional[str] = None

    # --- storage ---
    data_dir: Path = Path("data")

    # --- networking / safety knobs ---
    http_timeout: int = 20
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    max_upload_mb: int = 25
    max_image_pixels: int = 60_000_000     # ~60MP decompression-bomb ceiling
    ai_image_max_dim: int = 1600           # downscale long edge before sending to Claude/Ollama
    comp_limit: int = 40                   # max comps to pull per source

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key or self.ollama_base_url)

    @property
    def ollama_enabled(self) -> bool:
        return bool(getattr(self, "ollama_base_url", None))

    @property
    def ebay_enabled(self) -> bool:
        return bool(self.ebay_client_id and self.ebay_client_secret)

    @property
    def psa_enabled(self) -> bool:
        return bool(getattr(self, "psa_api_token", None))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "history.db"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"


def load_settings() -> Settings:
    data_dir = Path(_get("TCG_DATA_DIR", "data") or "data")
    return Settings(
        anthropic_api_key=_get("ANTHROPIC_API_KEY"),
        anthropic_model=_get("ANTHROPIC_MODEL", "claude-opus-4-8") or "claude-opus-4-8",
        ollama_base_url=_get("OLLAMA_BASE_URL"),
        ollama_model=_get("OLLAMA_MODEL", "qwen2.5vl:7b") or "qwen2.5vl:7b",
        ebay_client_id=_get("EBAY_CLIENT_ID"),
        ebay_client_secret=_get("EBAY_CLIENT_SECRET"),
        ebay_env=(_get("EBAY_ENV", "production") or "production").lower(),
        ebay_marketplace=_get("EBAY_MARKETPLACE", "EBAY_US") or "EBAY_US",
        psa_api_token=_get("PSA_API_TOKEN"),
        data_dir=data_dir,
        http_timeout=_get_int("TCG_HTTP_TIMEOUT", 20),
        max_upload_mb=_get_int("TCG_MAX_UPLOAD_MB", 25),
        max_image_pixels=_get_int("TCG_MAX_IMAGE_PIXELS", 60_000_000),
        ai_image_max_dim=_get_int("TCG_AI_IMAGE_MAX_DIM", 1600),
        comp_limit=_get_int("TCG_COMP_LIMIT", 40),
    )
