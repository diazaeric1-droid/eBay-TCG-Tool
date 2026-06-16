"""Tests for the PSA cert-verification source (mocked HTTP)."""
from __future__ import annotations

import pytest

from tcg.config import Settings
from tcg.models import PsaCert
from tcg.psa import PsaError, PsaSource, PsaUnavailable, normalize_cert


# A real-shaped PSA response (the Dark Magician Girl slab, cert 108149771).
SAMPLE = {
    "PSACert": {
        "CertNumber": "108149771",
        "SpecID": 2597442,
        "SpecNumber": "SB99000002",
        "LabelType": "LighthouseLabel",
        "ReverseBarCode": True,
        "Year": "2005",
        "Brand": "YU-GI-OH! RISE OF DESTINY: SPECIAL EDITION",
        "Category": "TCG Cards",
        "CardNumber": "ENSE2",
        "Subject": "DARK MAGICIAN GIRL",
        "Variety": "SPECIAL EDITION",
        "IsPSADNA": False,
        "IsDualCert": False,
        "GradeDescription": "VG 3",
        "CardGrade": "VG 3",
        "TotalPopulation": 33,
        "TotalPopulationWithQualifier": 1,
        "PopulationHigher": 1478,
    }
}


class _FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else SAMPLE

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code}")


def _settings(token="tok-123"):
    return Settings(psa_api_token=token, http_timeout=20)


def test_normalize_cert_strips_non_digits():
    assert normalize_cert(" 1081-4977 1 ") == "108149771"
    assert normalize_cert("PSA #12345") == "12345"
    assert normalize_cert("") == ""


def test_disabled_without_token():
    src = PsaSource(_settings(token=None))
    assert src.enabled is False
    with pytest.raises(PsaUnavailable):
        src.verify_cert("108149771")


def test_verify_cert_parses_identity_and_population(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResp()

    monkeypatch.setattr("tcg.psa._req.get", fake_get)
    src = PsaSource(_settings())
    cert = src.verify_cert("1081-4977-1")  # punctuation tolerated

    assert isinstance(cert, PsaCert)
    assert cert.cert_number == "108149771"
    assert cert.year == "2005"
    assert cert.subject == "DARK MAGICIAN GIRL"
    assert cert.card_number == "ENSE2"
    assert cert.grade == "VG 3"
    assert cert.grader == "PSA"
    assert cert.total_population == 33
    assert cert.population_higher == 1478
    # cert number was normalized into the request URL
    assert captured["url"].endswith("/108149771")
    # browser UA is required to dodge Cloudflare 1010
    assert "Mozilla" in captured["headers"]["User-Agent"]
    assert captured["headers"]["Authorization"] == "Bearer tok-123"


def test_search_query_builds_clean_phrase(monkeypatch):
    monkeypatch.setattr("tcg.psa._req.get", lambda *a, **k: _FakeResp())
    cert = PsaSource(_settings()).verify_cert("108149771")
    q = cert.search_query()
    assert "2005" in q
    assert "DARK MAGICIAN GIRL" in q
    assert "PSA" in q
    assert q.endswith("3")          # grade number appended
    assert q.count("PSA") == 1      # no duplicate tokens


def test_unknown_cert_raises(monkeypatch):
    monkeypatch.setattr(
        "tcg.psa._req.get", lambda *a, **k: _FakeResp(payload={"PSACert": {}})
    )
    with pytest.raises(PsaError):
        PsaSource(_settings()).verify_cert("000000000")


def test_blank_cert_raises(monkeypatch):
    monkeypatch.setattr("tcg.psa._req.get", lambda *a, **k: _FakeResp())
    with pytest.raises(PsaError):
        PsaSource(_settings()).verify_cert("no-digits-here")


def test_http_429_raises_clear_error(monkeypatch):
    monkeypatch.setattr(
        "tcg.psa._req.get", lambda *a, **k: _FakeResp(status=429, payload={})
    )
    with pytest.raises(PsaError, match="rate limit"):
        PsaSource(_settings()).verify_cert("108149771")


def _cert(**over) -> PsaCert:
    base = dict(
        cert_number="108149771", year="2005",
        brand="YU-GI-OH! RISE OF DESTINY: SPECIAL EDITION",
        card_number="ENSE2", subject="DARK MAGICIAN GIRL",
        variety="SPECIAL EDITION", grade="VG 3",
        total_population=33, population_higher=1478,
    )
    base.update(over)
    return PsaCert(**base)


def test_condition_prefixes_psa():
    assert _cert().condition == "PSA VG 3"
    assert _cert(grade="GEM MT 10").condition == "PSA GEM MT 10"
    assert _cert(grade="").condition == "PSA Graded"


def test_listing_title_is_titlecased_and_capped():
    t = _cert().listing_title()
    assert "Dark Magician Girl" in t          # ALL-CAPS subject title-cased
    assert "PSA VG 3" in t                     # grade is never dropped
    assert "2005" in t
    assert len(t) <= 80


def test_listing_title_keeps_grade_even_with_long_brand():
    # The Yu-Gi-Oh brand string alone is ~42 chars; the grade must still survive.
    t = _cert().listing_title()
    assert t.endswith("PSA VG 3")
    assert len(t) <= 80


def test_listing_title_includes_card_number_when_room():
    # A short brand leaves room for the #card number.
    t = _cert(brand="Topps Chrome", subject="Shohei Ohtani",
              card_number="150", variety="").listing_title()
    assert "#150" in t
    assert "PSA VG 3" in t
    assert len(t) <= 80


def test_listing_description_includes_population_and_cert():
    d = _cert().listing_description()
    assert "Dark Magician Girl" in d
    assert "PSA VG 3 — cert #108149771" in d
    assert "33 at this grade" in d
    assert "1,478 graded higher" in d
    assert "psacard.com/cert/108149771" in d


def test_listing_title_handles_missing_card_number():
    t = _cert(card_number="").listing_title()
    assert "#" not in t                        # no stray hash when no card number
