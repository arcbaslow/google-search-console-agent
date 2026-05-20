"""Tests for gsc_backlinks. All HTTP is mocked."""

import json
from unittest.mock import patch, MagicMock


import gsc_backlinks


# ---------- helpers ----------

def test_strip_scheme_handles_sc_domain():
    assert gsc_backlinks._strip_scheme("sc-domain:example.com") == "example.com"


def test_strip_scheme_handles_url_prefix():
    assert gsc_backlinks._strip_scheme("https://example.com/") == "example.com"


def test_strip_scheme_handles_bare_domain():
    assert gsc_backlinks._strip_scheme("Example.COM") == "example.com"


def test_tranco_band_top_1k():
    assert gsc_backlinks._tranco_band(500) == "top_1k"


def test_tranco_band_outside_top_1m():
    assert gsc_backlinks._tranco_band(None) == "outside_top_1m"


def test_tranco_band_top_100k():
    assert gsc_backlinks._tranco_band(50000) == "top_100k"


# ---------- Open PageRank ----------

def test_open_pagerank_no_key_returns_hint(monkeypatch):
    monkeypatch.delenv("OPENPAGERANK_API_KEY", raising=False)
    out = gsc_backlinks.query_open_pagerank(["example.com"])
    assert out["error"] == "no_api_key"
    assert "openpagerank" in out["hint"]


def test_open_pagerank_no_domains_returns_error(monkeypatch):
    monkeypatch.setenv("OPENPAGERANK_API_KEY", "test-key")
    out = gsc_backlinks.query_open_pagerank([])
    assert out["error"] == "no_domains"


def test_open_pagerank_parses_response(monkeypatch):
    """Mock the urllib response and assert we flatten the fields right."""
    monkeypatch.setenv("OPENPAGERANK_API_KEY", "test-key")
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "response": [
            {"domain": "example.com", "rank": "42", "page_rank_decimal": 5.8,
             "page_rank_integer": 6, "status_code": 200},
            {"domain": "another.com", "rank": "99", "page_rank_decimal": 4.2,
             "page_rank_integer": 4, "status_code": 200},
        ],
        "rate_limit": {"limit_left": "999"},
    }).encode("utf-8")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = lambda *_a: False

    with patch("urllib.request.urlopen", return_value=mock_resp):
        out = gsc_backlinks.query_open_pagerank(["example.com", "another.com"])

    assert out["source"] == "open_pagerank"
    assert out["results"]["example.com"]["page_rank_decimal"] == 5.8
    assert out["results"]["example.com"]["page_rank_integer"] == 6
    assert out["results"]["another.com"]["rank"] == 99
    assert out["rate_limit"]["limit_left"] == "999"


# ---------- Tranco ----------

def test_tranco_rank_uses_dict_cache(monkeypatch, tmp_path):
    fake_csv = tmp_path / "tranco.csv"
    fake_csv.write_text("1,google.com\n2,facebook.com\n2543,example.com\n",
                        encoding="utf-8")
    monkeypatch.setattr(gsc_backlinks, "TRANCO_CACHE", fake_csv)
    monkeypatch.setattr(gsc_backlinks, "_tranco_dict_cache", None)
    monkeypatch.setattr(gsc_backlinks, "_ensure_tranco_cache", lambda: None)

    assert gsc_backlinks.tranco_rank("example.com") == 2543
    assert gsc_backlinks.tranco_rank("Google.com") == 1
    assert gsc_backlinks.tranco_rank("not-in-list.com") is None


def test_tranco_rank_strips_scheme(monkeypatch, tmp_path):
    fake_csv = tmp_path / "tranco.csv"
    fake_csv.write_text("17,example.com\n", encoding="utf-8")
    monkeypatch.setattr(gsc_backlinks, "TRANCO_CACHE", fake_csv)
    monkeypatch.setattr(gsc_backlinks, "_tranco_dict_cache", None)
    monkeypatch.setattr(gsc_backlinks, "_ensure_tranco_cache", lambda: None)

    assert gsc_backlinks.tranco_rank("https://example.com/") == 17
    assert gsc_backlinks.tranco_rank("sc-domain:example.com") == 17


# ---------- high-level helpers ----------

def test_domain_authority_returns_open_pagerank_error_when_no_key(monkeypatch, tmp_path):
    fake_csv = tmp_path / "tranco.csv"
    fake_csv.write_text("99,example.com\n", encoding="utf-8")
    monkeypatch.setattr(gsc_backlinks, "TRANCO_CACHE", fake_csv)
    monkeypatch.setattr(gsc_backlinks, "_tranco_dict_cache", None)
    monkeypatch.setattr(gsc_backlinks, "_ensure_tranco_cache", lambda: None)
    monkeypatch.delenv("OPENPAGERANK_API_KEY", raising=False)

    out = gsc_backlinks.domain_authority("example.com")
    assert out["domain"] == "example.com"
    assert out["tranco_rank"] == 99
    assert out["tranco_band"] == "top_1k"
    assert out["open_pagerank_error"] == "no_api_key"


def test_compare_domains_orders_rows(monkeypatch, tmp_path):
    fake_csv = tmp_path / "tranco.csv"
    fake_csv.write_text("1,me.com\n50,competitor.com\n", encoding="utf-8")
    monkeypatch.setattr(gsc_backlinks, "TRANCO_CACHE", fake_csv)
    monkeypatch.setattr(gsc_backlinks, "_tranco_dict_cache", None)
    monkeypatch.setattr(gsc_backlinks, "_ensure_tranco_cache", lambda: None)
    monkeypatch.delenv("OPENPAGERANK_API_KEY", raising=False)

    out = gsc_backlinks.compare_domains(["me.com", "competitor.com"])
    assert out["primary"] == "me.com"
    assert len(out["rows"]) == 2
    assert out["rows"][0]["tranco_rank"] == 1
    assert out["rows"][1]["tranco_rank"] == 50
