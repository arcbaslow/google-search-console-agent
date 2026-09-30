"""Direct PSI tests; all HTTP, tokens and caches are synthetic."""

import io
import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import gsc_psi
import pytest


@pytest.fixture
def psi_http(monkeypatch):
    payload = {
        "id": "https://example.com/",
        "analysisUTCTimestamp": "2026-09-30T00:00:00Z",
        "lighthouseResult": {
            "categories": {"performance": {"score": 0.91}},
            "audits": {
                "largest-contentful-paint": {"numericValue": 2500},
                "total-blocking-time": {"numericValue": 100},
                "diagnostic-example": {"details": {"items": [{"url": "https://example.com/a.js"}]}},
            },
        },
        "loadingExperience": {"metrics": {
            "INTERACTION_TO_NEXT_PAINT": {"percentile": 180, "category": "FAST"},
        }},
    }
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = json.dumps(payload).encode()
    opener = MagicMock(return_value=response)
    monkeypatch.setattr(gsc_psi.urllib.request, "urlopen", opener)
    monkeypatch.setattr(gsc_psi, "_bearer_token", lambda: "synthetic-token")
    return opener, payload


def test_request_and_flattening_keep_raw_diagnostics(psi_http):
    opener, payload = psi_http
    out = gsc_psi.run_psi("https://example.com/?a=1&b=2", strategy="desktop",
                          locale="fr", categories=("seo", "performance"), use_cache=False)
    opener.assert_called_once()
    req = opener.call_args.args[0]
    assert req.full_url.startswith(gsc_psi.PSI_ENDPOINT + "?")
    assert parse_qs(urlsplit(req.full_url).query) == {
        "url": ["https://example.com/?a=1&b=2"], "strategy": ["desktop"],
        "locale": ["fr"], "category": ["seo", "performance"],
    }
    assert req.get_header("Authorization") == "Bearer synthetic-token"
    assert opener.call_args.kwargs["timeout"] == 60
    assert out["lab"]["lcp_s"] == 2.5
    assert out["lab"]["tbt_ms"] == 100
    assert out["field"]["inp_p75_ms"] == 180
    assert out["lh_performance_score"] == 0.91
    assert out["lh_seo_score"] is None
    assert out["raw"] == payload


def test_missing_field_data_remains_unknown():
    out = gsc_psi._flatten_psi({}, "mobile")
    assert out["field"] == {"overall_category": None}
    assert all(value is None for value in out["lab"].values())


def test_cache_identity_and_bypass(psi_http):
    opener, _ = psi_http
    first = gsc_psi.run_psi("https://example.com", categories=("seo", "performance"))
    assert gsc_psi.run_psi("https://example.com", categories=("performance", "seo")) == first
    assert opener.call_count == 1
    gsc_psi.run_psi("https://example.com", strategy="desktop")
    gsc_psi.run_psi("https://example.com", locale="fr")
    gsc_psi.run_psi("https://example.com", categories=("seo",))
    gsc_psi.run_psi("https://example.org")
    assert opener.call_count == 5
    gsc_psi.run_psi("https://example.com", use_cache=False)
    assert opener.call_count == 6


@pytest.mark.parametrize("status", [403, 429, 500])
def test_http_failure_is_not_retried_or_cached(psi_http, status, monkeypatch):
    opener, _ = psi_http
    opener.side_effect = urllib.error.HTTPError(gsc_psi.PSI_ENDPOINT, status, "error", {}, io.BytesIO(b"service failed"))
    cache = MagicMock()
    monkeypatch.setattr(gsc_psi, "cache_set", cache)
    with pytest.raises(RuntimeError, match=f"PSI HTTP {status}"):
        gsc_psi.run_psi("https://example.com")
    opener.assert_called_once()
    cache.assert_not_called()


def test_transport_timeout_is_not_retried(psi_http):
    opener, _ = psi_http
    opener.side_effect = TimeoutError("slow PSI")
    with pytest.raises(TimeoutError):
        gsc_psi.run_psi("https://example.com", use_cache=False)
    opener.assert_called_once()


def test_invalid_strategy_does_not_authenticate(monkeypatch):
    token = MagicMock(side_effect=AssertionError("no authentication"))
    monkeypatch.setattr(gsc_psi, "_bearer_token", token)
    with pytest.raises(ValueError):
        gsc_psi.run_psi("https://example.com", strategy="tablet")
    token.assert_not_called()


@pytest.mark.parametrize("raw", [False, True])
def test_cli_raw_is_opt_in_without_mutating_cached_result(monkeypatch, capsys, raw):
    result = {"url": "https://example.com", "raw": {"lighthouseResult": {"audits": {"example": {}}}}}
    run = MagicMock(return_value=result)
    monkeypatch.setattr(gsc_psi, "run_psi", run)
    monkeypatch.setattr("sys.argv", ["gsc_psi.py", "--url", "https://example.com", "--no-cache"] + (["--raw"] if raw else []))
    assert gsc_psi.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert ("raw" in out) is raw
    assert "raw" in result
    assert run.call_args.kwargs["use_cache"] is False


def test_cli_failure_is_json_on_stderr(monkeypatch, capsys):
    monkeypatch.setattr(gsc_psi, "run_psi", MagicMock(side_effect=TimeoutError("slow PSI")))
    monkeypatch.setattr("sys.argv", ["gsc_psi.py", "--url", "https://example.com"])
    assert gsc_psi.main() == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)["type"] == "TimeoutError"


def test_token_refresh_stays_in_memory(monkeypatch):
    creds = SimpleNamespace(token=None, expired=True)
    creds.refresh = MagicMock(side_effect=lambda request: setattr(creds, "token", "refreshed-test-token"))
    get = MagicMock(return_value=creds)
    monkeypatch.setattr(gsc_psi, "get_credentials", get)
    assert gsc_psi._bearer_token() == "refreshed-test-token"
    get.assert_called_once_with(write=False)
    creds.refresh.assert_called_once()


def test_missing_token_reports_auth_failure(monkeypatch):
    creds = SimpleNamespace(token=None, expired=True, refresh=MagicMock())
    monkeypatch.setattr(gsc_psi, "get_credentials", lambda **kw: creds)
    with pytest.raises(RuntimeError, match="access token"):
        gsc_psi._bearer_token()
