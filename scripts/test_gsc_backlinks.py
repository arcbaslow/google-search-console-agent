"""Tests for gsc_backlinks. All HTTP is mocked."""

import json
from unittest.mock import MagicMock, patch

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
    monkeypatch.delenv("OPENPAGERANK_V1_API_KEY", raising=False)
    out = gsc_backlinks.query_open_pagerank(["example.com"])
    assert out["error"] == "no_api_key"
    assert "openpagerank" in out["hint"]


def test_open_pagerank_no_domains_returns_error(monkeypatch):
    monkeypatch.setenv("OPENPAGERANK_V1_API_KEY", "opr_live_synthetic")
    out = gsc_backlinks.query_open_pagerank([])
    assert out["error"] == "no_domains"


def test_open_pagerank_parses_response(monkeypatch):
    """Mock the urllib response and assert we flatten the fields right."""
    monkeypatch.setenv("OPENPAGERANK_V1_API_KEY", "opr_live_synthetic")
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "results": [
            {"domain": "example.com", "rank": 42, "open_page_rank": 5.8, "found": True},
            {"domain": "another.com", "rank": 99, "open_page_rank": 4.2, "found": True},
        ],
    }).encode("utf-8")
    mock_resp.headers = {"X-Domains-Remaining": "999"}
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = lambda *_a: False

    with patch("urllib.request.urlopen", return_value=mock_resp):
        out = gsc_backlinks.query_open_pagerank(["example.com", "another.com"])

    assert out["source"] == "open_pagerank"
    assert out["results"]["example.com"]["page_rank_decimal"] == 5.8
    assert out["results"]["example.com"]["page_rank_integer"] is None
    assert out["results"]["another.com"]["rank"] == 99
    assert out["rate_limit"]["X-Domains-Remaining"] == "999"


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
    monkeypatch.delenv("OPENPAGERANK_V1_API_KEY", raising=False)

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
    monkeypatch.delenv("OPENPAGERANK_V1_API_KEY", raising=False)

    out = gsc_backlinks.compare_domains(["me.com", "competitor.com"])
    assert out["primary"] == "me.com"
    assert len(out["rows"]) == 2
    assert out["rows"][0]["tranco_rank"] == 1
    assert out["rows"][1]["tranco_rank"] == 50

def test_open_pagerank_rejects_oversize_request_without_sending(monkeypatch):
    opener = MagicMock(side_effect=AssertionError("must not send a truncated request"))
    monkeypatch.setattr(gsc_backlinks.urllib.request, "urlopen", opener)
    out = gsc_backlinks.query_open_pagerank([f"site{i}.example" for i in range(101)], api_key="test-key")
    assert out["error"] == "too_many_domains"
    opener.assert_not_called()


def test_cli_key_override_reaches_comparison_without_mutating_environment(monkeypatch, capsys):
    monkeypatch.setenv("OPENPAGERANK_API_KEY", "environment-key")
    query = MagicMock(return_value={"results": {}})
    monkeypatch.setattr(gsc_backlinks, "query_open_pagerank", query)
    monkeypatch.setattr(gsc_backlinks, "tranco_rank", lambda domain: None)
    monkeypatch.setattr("sys.argv", ["gsc_backlinks.py", "--compare", "a.example,b.example", "--api-key", "override-key"])
    assert gsc_backlinks.main() == 0
    query.assert_called_once_with(["a.example", "b.example"], api_key="override-key")
    assert gsc_backlinks.os.environ["OPENPAGERANK_API_KEY"] == "environment-key"
    assert len(json.loads(capsys.readouterr().out)["rows"]) == 2


def test_single_domain_key_override_reaches_query(monkeypatch):
    query = MagicMock(return_value={"results": {}})
    monkeypatch.setattr(gsc_backlinks, "query_open_pagerank", query)
    monkeypatch.setattr(gsc_backlinks, "tranco_rank", lambda domain: None)
    gsc_backlinks.domain_authority("a.example", api_key="override-key")
    query.assert_called_once_with(["a.example"], api_key="override-key")

def test_tranco_failure_preserves_open_pagerank_in_both_modes(monkeypatch):
    monkeypatch.setattr(gsc_backlinks, "tranco_rank", MagicMock(side_effect=TimeoutError("slow source")))
    query = MagicMock(return_value={"results": {"a.example": {"page_rank_decimal": 4.2}}})
    monkeypatch.setattr(gsc_backlinks, "query_open_pagerank", query)
    single = gsc_backlinks.domain_authority("a.example")
    assert single["tranco_band"] == "unavailable"
    assert single["tranco_error"] == "TimeoutError"
    assert single["open_pagerank"]["page_rank_decimal"] == 4.2
    compared = gsc_backlinks.compare_domains(["a.example", "b.example"])
    assert compared["rows"][0]["open_pagerank_decimal"] == 4.2
    assert all(row["tranco_band"] == "unavailable" for row in compared["rows"])


def test_unexpected_open_pagerank_failure_preserves_tranco(monkeypatch):
    monkeypatch.setattr(gsc_backlinks, "query_open_pagerank", MagicMock(side_effect=ValueError("bad JSON")))
    monkeypatch.setattr(gsc_backlinks, "tranco_rank", lambda domain: 10)
    for out in [gsc_backlinks.domain_authority("a.example"), gsc_backlinks.compare_domains(["a.example"])]:
        assert out["open_pagerank_error"] == "ValueError"
        row = out.get("rows", [out])[0]
        assert row["tranco_rank"] == 10
        assert row["tranco_band"] == "top_1k"


def test_missing_tranco_domain_is_not_a_source_failure(monkeypatch):
    monkeypatch.setattr(gsc_backlinks, "tranco_rank", lambda domain: None)
    monkeypatch.setattr(gsc_backlinks, "query_open_pagerank", lambda *a, **kw: {"error": "no_api_key"})
    row = gsc_backlinks.compare_domains(["a.example"])["rows"][0]
    assert row["tranco_band"] == "outside_top_1m"
    assert "tranco_error" not in row

def test_legacy_key_is_not_transferred_to_new_host(monkeypatch):
    monkeypatch.setenv("OPENPAGERANK_API_KEY", "legacy-synthetic")
    monkeypatch.delenv("OPENPAGERANK_V1_API_KEY", raising=False)
    fetch = MagicMock()
    monkeypatch.setattr("urllib.request.urlopen", fetch)
    assert gsc_backlinks.query_open_pagerank(["example.com"])["error"] == "no_api_key"
    assert gsc_backlinks.query_open_pagerank(["example.com"], api_key="legacy-synthetic")["error"] == "migration_required"
    fetch.assert_not_called()


def test_current_opr_request_hosts_and_budgets(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers = {"X-Domains-Remaining": "0", "X-RateLimit-Remaining": "59"}
    response.read.return_value = json.dumps({"as_of": "2026-09-01", "results": [
        {"domain": "example.com", "found": True, "open_page_rank": 5, "hosts": [
            {"host": "blog.example.com", "found": True, "open_page_rank": 3, "rank": 77}]},
        {"domain": "absent.test", "found": False}]}).encode()
    fetch = MagicMock(return_value=response)
    monkeypatch.setattr("urllib.request.urlopen", fetch)
    out = gsc_backlinks.query_open_pagerank(["blog.example.com", "www.example.com", "absent.test"], api_key="opr_live_synthetic")
    request = fetch.call_args.args[0]
    assert request.method == "POST"
    assert request.get_header("Authorization") == "Bearer opr_live_synthetic"
    assert json.loads(request.data)["include_history"] is False
    assert out["results"]["blog.example.com"]["page_rank_decimal"] == 3
    assert out["results"]["blog.example.com"]["rank_scope"] == "host"
    assert out["results"]["www.example.com"]["source_domain"] == "example.com"
    assert out["results"]["absent.test"]["page_rank_decimal"] is None
    assert out["rate_limit"]["X-Domains-Remaining"] == "0"


def test_opr_quota_error_exposes_retry_hint_without_retry(monkeypatch):
    import io
    import urllib.error
    fetch = MagicMock(side_effect=urllib.error.HTTPError("url", 429, "quota", {"Retry-After": "60"},
        io.BytesIO(b'{"error":{"type":"quota_error"}}')))
    monkeypatch.setattr("urllib.request.urlopen", fetch)
    out = gsc_backlinks.query_open_pagerank(["example.com"], api_key="opr_live_synthetic")
    assert out["error_type"] == "quota_error"
    assert out["retry_after"] == "60"
    fetch.assert_called_once()

def test_tranco_replacement_failure_retains_old_csv(monkeypatch, tmp_path):
    import io
    import zipfile

    import pytest
    path = tmp_path / "tranco.csv"
    path.write_text("1,old.example\n")
    monkeypatch.setattr(gsc_backlinks, "TRANCO_CACHE", path)
    monkeypatch.setattr(gsc_backlinks, "TRANCO_REFRESH_SECONDS", -1)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("top.csv", "2,new.example\n")
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = archive.getvalue()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: response)
    monkeypatch.setattr(gsc_backlinks.os, "replace", MagicMock(side_effect=PermissionError("locked")))
    with pytest.raises(PermissionError):
        gsc_backlinks._ensure_tranco_cache()
    assert path.read_text() == "1,old.example\n"
    assert list(tmp_path.iterdir()) == [path]


def test_tranco_memory_cache_reloads_changed_file(monkeypatch, tmp_path):
    path = tmp_path / "tranco.csv"
    path.write_text("1,example.com\n")
    monkeypatch.setattr(gsc_backlinks, "TRANCO_CACHE", path)
    monkeypatch.setattr(gsc_backlinks, "_ensure_tranco_cache", lambda: None)
    assert gsc_backlinks.tranco_rank("example.com") == 1
    path.write_text("200,example.com\n")
    assert gsc_backlinks.tranco_rank("example.com") == 200


def test_empty_tranco_file_is_unavailable_not_outside_list(monkeypatch, tmp_path):
    path = tmp_path / "tranco.csv"
    path.write_text("")
    monkeypatch.setattr(gsc_backlinks, "TRANCO_CACHE", path)
    monkeypatch.setattr(gsc_backlinks, "_ensure_tranco_cache", lambda: None)
    assert gsc_backlinks._tranco_rows(["example.com"])[0]["tranco_band"] == "unavailable"
