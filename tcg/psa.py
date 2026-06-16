"""PSA public-API client — verify graded slabs by certification number.

The PSA cert API returns the *identity* of a slab (year, set, card, grade) plus
*population* data (how many exist at this grade and how many grade higher). It
does **not** return prices — pricing still comes from the sold-comp sources
(130point / PriceCharting). Population is, however, a strong value signal: a card
with thousands graded higher sits at the low end of its grade curve.

Requires ``PSA_API_TOKEN`` (a PSA public-API bearer token). Without it,
``verify_cert`` raises ``PsaUnavailable`` and the app simply skips PSA lookups.

Note on Cloudflare: PSA fronts the API with Cloudflare, which 1010-blocks
non-browser User-Agents. We therefore send a normal browser UA (the same one the
rest of the app uses) alongside the bearer token.
"""
from __future__ import annotations

import re
from typing import Optional

import requests as _req

from .config import Settings
from .models import PsaCert

PSA_CERT_URL = "https://api.psacard.com/publicapi/cert/GetByCertNumber/{cert}"


class PsaUnavailable(RuntimeError):
    """No PSA API token configured."""


class PsaError(RuntimeError):
    """The PSA API call failed (network, auth, bad cert, malformed output)."""


def normalize_cert(raw: str) -> str:
    """Strip everything but digits from a user-entered cert number."""
    return re.sub(r"\D", "", raw or "")


class PsaSource:
    def __init__(self, settings: Settings):
        self.token = getattr(settings, "psa_api_token", None)
        self.timeout = max(15, getattr(settings, "http_timeout", 20))
        self.user_agent = getattr(settings, "user_agent", None) or (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def verify_cert(self, cert: str) -> PsaCert:
        """Look up a PSA cert number and return its verified identity + population.

        Raises ``PsaUnavailable`` if no token is set, ``PsaError`` on failure or
        an unknown cert.
        """
        if not self.token:
            raise PsaUnavailable(
                "No PSA API token configured. Set PSA_API_TOKEN to enable "
                "graded-slab verification."
            )
        cert_n = normalize_cert(cert)
        if not cert_n:
            raise PsaError("Enter a numeric PSA certification number.")

        headers = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": self.user_agent,   # required: Cloudflare 1010-blocks non-browser UAs
            "Accept": "application/json",
        }
        try:
            resp = _req.get(
                PSA_CERT_URL.format(cert=cert_n), headers=headers, timeout=self.timeout
            )
        except _req.RequestException as exc:
            raise PsaError(f"PSA request failed: {exc}") from exc

        if resp.status_code == 401:
            raise PsaError("PSA API rejected the token (401). Check PSA_API_TOKEN.")
        if resp.status_code == 429:
            raise PsaError("PSA API rate limit hit (429). Try again shortly.")
        try:
            resp.raise_for_status()
            payload = resp.json()
        except (ValueError, _req.HTTPError) as exc:
            raise PsaError(f"Unexpected PSA response ({resp.status_code}): {exc}") from exc

        return _parse_cert(payload, cert_n)


def _parse_cert(payload: dict, cert_n: str) -> PsaCert:
    data = (payload or {}).get("PSACert") or {}
    if not data or not (data.get("Subject") or data.get("Brand")):
        raise PsaError(f"PSA has no record for cert #{cert_n}.")

    def _int(v) -> Optional[int]:
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return PsaCert(
        cert_number=str(data.get("CertNumber") or cert_n),
        spec_id=_int(data.get("SpecID")),
        year=str(data.get("Year") or "").strip(),
        brand=str(data.get("Brand") or "").strip(),
        category=str(data.get("Category") or "").strip(),
        card_number=str(data.get("CardNumber") or "").strip(),
        subject=str(data.get("Subject") or "").strip(),
        variety=str(data.get("Variety") or "").strip(),
        grade=str(data.get("CardGrade") or data.get("GradeDescription") or "").strip(),
        total_population=_int(data.get("TotalPopulation")),
        population_higher=_int(data.get("PopulationHigher")),
        is_dna=bool(data.get("IsPSADNA")),
        valid=True,
    )
