"""Tests for gsc_page_experience. All HTTP is mocked."""

import json
from unittest.mock import MagicMock, patch

import gsc_page_experience
import pytest

# ---------- helpers ----------

def test_strip_scheme_handles_sc_domain():
    assert gsc_page_experience._strip_scheme("sc-domain:example.com") == "example.com"


def test_strip_scheme_handles_url_prefix():
    assert gsc_page_experience._strip_scheme("https://example.com") == "example.com"


def test_strip_scheme_handles_bare_domain():
    assert gsc_page_experience._strip_scheme("Example.com") == "example.com"


# ---------- Local header probe ----------

def _mock_head_response(status=200, headers=None):
    resp = MagicMock()
    resp.status = status
    raw_headers = headers or {}
    resp.headers = MagicMock()
    resp.headers.items.return_value = list(raw_headers.items())
    resp.__enter__ = lambda s: s
    resp.__exit__ = lambda *a: False
    return resp


def test_probe_headers_grade_good_when_all_present(monkeypatch):
    headers = {h: "x" for h in gsc_page_experience.SECURITY_HEADERS}
    headers["server"] = "nginx"
    with patch("urllib.request.urlopen", return_value=_mock_head_response(200, headers)):
        out = gsc_page_experience.probe_headers("example.com")
    assert out["status"] == 200
    assert out["grade"] == "good"
    assert out["coverage_pct"] == 100.0
    assert out["headers_missing"] == []


def test_probe_headers_grade_poor_when_none_present(monkeypatch):
    with patch("urllib.request.urlopen", return_value=_mock_head_response(200, {})):
        out = gsc_page_experience.probe_headers("example.com")
    assert out["grade"] == "poor"
    assert out["coverage_pct"] == 0.0
    assert set(out["headers_missing"]) == set(gsc_page_experience.SECURITY_HEADERS)


def test_probe_headers_grade_needs_improvement_when_half(monkeypatch):
    half_headers = {h: "x" for h in list(gsc_page_experience.SECURITY_HEADERS)[:3]}
    with patch("urllib.request.urlopen", return_value=_mock_head_response(200, half_headers)):
        out = gsc_page_experience.probe_headers("example.com")
    assert out["grade"] == "needs_improvement"


def test_probe_headers_handles_transport_error(monkeypatch):
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("dns fail")):
        out = gsc_page_experience.probe_headers("example.com")
    assert out["error"] == "transport"


# ---------- Mozilla Observatory ----------

def _mock_observatory_response(state="FINISHED", grade="A+", score=120):
    resp = MagicMock()
    resp.read.return_value = json.dumps({
        "state": state,
        "grade": grade,
        "score": score,
        "tests_passed": 10,
        "tests_failed": 1,
        "tests_quantity": 11,
        "id": 42,
    }).encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = lambda *a: False
    return resp


def test_run_observatory_returns_grade(monkeypatch):
    """The v2 POST response is the result, with no GET polling."""
    monkeypatch.setattr(gsc_page_experience.time, "sleep", lambda *_a: None)
    response = _mock_observatory_response()
    with patch("urllib.request.urlopen", return_value=response) as fetch:
        out = gsc_page_experience.run_observatory("example.com")
    assert out["grade"] == "A+"
    assert out["score"] == 120
    assert out["scan_id"] == 42
    fetch.assert_called_once()
    request = fetch.call_args.args[0]
    assert request.full_url == "https://observatory-api.mdn.mozilla.net/api/v2/scan?host=example.com"
    assert request.method == "POST"


def test_run_observatory_http_error_does_not_get_or_retry(monkeypatch):
    import urllib.error
    monkeypatch.setattr(gsc_page_experience.time, "sleep", lambda *_a: None)
    post_err = urllib.error.HTTPError("u", 409, "conflict", {}, None)
    with patch("urllib.request.urlopen", side_effect=post_err) as fetch:
        out = gsc_page_experience.run_observatory("example.com")
    assert out["error"] == "observatory_http_409"
    fetch.assert_called_once()


@pytest.mark.parametrize("payload,error", [
    (b"not json", "invalid_response"),
    (b"[]", "invalid_response"),
    (b'{"error":"dns failed"}', "observatory_scan_failed"),
    (b'{"score":0}', "incomplete_response"),
])
def test_observatory_invalid_or_incomplete_response(payload, error):
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = payload
    with patch("urllib.request.urlopen", return_value=response):
        assert gsc_page_experience.run_observatory("example.com")["error"] == error
    response.__exit__.assert_called_once()


# ---------- SSL Labs ----------

def _mock_ssl_response(status="READY", endpoints=None):
    resp = MagicMock()
    resp.read.return_value = json.dumps({
        "status": status,
        "endpoints": endpoints or [{"grade": "A"}, {"grade": "A+"}],
        "testTime": "2026-05-21T00:00:00Z",
        "protocol": "HTTP",
    }).encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = lambda *a: False
    return resp


def test_run_ssl_labs_picks_worst_grade(monkeypatch):
    monkeypatch.setattr(gsc_page_experience.time, "sleep", lambda *_a: None)
    with patch("urllib.request.urlopen", return_value=_mock_ssl_response(
        endpoints=[{"grade": "A+"}, {"grade": "B"}, {"grade": "A"}],
    )):
        out = gsc_page_experience.run_ssl_labs("example.com")
    assert out["grade"] == "B"   # worst of A+, B, A
    assert out["endpoints_tested"] == 3


def test_run_ssl_labs_polls_until_ready(monkeypatch):
    """First call IN_PROGRESS, second call READY."""
    monkeypatch.setattr(gsc_page_experience.time, "sleep", lambda *_a: None)
    in_progress = _mock_ssl_response(status="IN_PROGRESS", endpoints=[])
    ready = _mock_ssl_response(status="READY")
    with patch("urllib.request.urlopen", side_effect=[_mock_ssl_response(), in_progress, ready]):
        out = gsc_page_experience.run_ssl_labs("example.com")
    assert out["status"] == "READY"
    assert out["grade"] == "A"


def test_run_ssl_labs_reports_error_status(monkeypatch):
    monkeypatch.setattr(gsc_page_experience.time, "sleep", lambda *_a: None)
    error_resp = MagicMock()
    error_resp.read.return_value = json.dumps({
        "status": "ERROR", "statusMessage": "Host name resolution failed",
    }).encode("utf-8")
    error_resp.__enter__ = lambda s: s
    error_resp.__exit__ = lambda *a: False
    with patch("urllib.request.urlopen", return_value=error_resp):
        out = gsc_page_experience.run_ssl_labs("example.com")
    assert out["error"] == "ssllabs_error"


def test_ssl_timeout_caps_requests_and_sleep(monkeypatch):
    now = [0.0]
    sleeps = []
    monkeypatch.setattr(gsc_page_experience.time, "monotonic", lambda: now[0])

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(gsc_page_experience.time, "sleep", sleep)
    with patch("urllib.request.urlopen", return_value=_mock_ssl_response("IN_PROGRESS")) as fetch:
        out = gsc_page_experience.run_ssl_labs("example.com", poll_budget_s=2)
    assert out["error"] == "timeout"
    assert "grade" not in out
    assert sleeps == [2]
    assert fetch.call_count == 2  # info, then one assessment
    assert all(c.kwargs["timeout"] <= 2 for c in fetch.call_args_list)


def test_ssl_notices_precede_assessment_and_start_new_only_once(monkeypatch, capsys):
    from urllib.parse import parse_qs, urlsplit

    monkeypatch.setattr(gsc_page_experience.time, "sleep", lambda _: None)
    requests = []

    def fetch(req, timeout):
        requests.append(req.full_url)
        if req.full_url.endswith("/info"):
            resp = _mock_ssl_response()
            resp.read.return_value = b'{"messages":["maintenance soon"]}'
            return resp
        if len(requests) == 2:
            notice = capsys.readouterr().err
            assert "maintenance soon" in notice
            assert "Terms:" in notice
            return _mock_ssl_response("IN_PROGRESS")
        return _mock_ssl_response()

    monkeypatch.setattr("urllib.request.urlopen", fetch)
    assert gsc_page_experience.run_ssl_labs("example.com", use_cache=False)["status"] == "READY"
    first, second = [parse_qs(urlsplit(u).query) for u in requests[1:]]
    assert first["startNew"] == ["on"]
    assert "startNew" not in second
    assert "fromCache" not in first


@pytest.mark.parametrize("status,wait", [(429, 60), (503, 900), (529, 1800)])
def test_ssl_overload_returns_hint_without_retry(status, wait):
    import urllib.error

    error = urllib.error.HTTPError("u", status, "busy", {}, None)
    with patch("urllib.request.urlopen", side_effect=error) as fetch:
        out = gsc_page_experience.run_ssl_labs("example.com")
    assert out["retry_after_seconds"] == wait
    fetch.assert_called_once()


def test_ssl_honors_retry_after_header():
    import urllib.error

    error = urllib.error.HTTPError("u", 429, "busy", {"Retry-After": "120"}, None)
    with patch("urllib.request.urlopen", side_effect=error):
        assert gsc_page_experience.run_ssl_labs("example.com")["retry_after"] == "120"


def test_full_report_retains_sources_and_forwards_no_cache(monkeypatch):
    monkeypatch.setattr(gsc_page_experience, "probe_headers", lambda _: {"grade": "good"})
    monkeypatch.setattr(gsc_page_experience, "run_observatory",
                        MagicMock(side_effect=ValueError("invalid JSON")))
    ssl = MagicMock(return_value={"grade": "A"})
    monkeypatch.setattr(gsc_page_experience, "run_ssl_labs", ssl)
    out = gsc_page_experience.full_report("example.com", use_cache=False)
    assert out["headers"]["grade"] == "good"
    assert out["observatory"]["error"] == "ValueError"
    assert out["ssl_labs"]["grade"] == "A"
    ssl.assert_called_once_with("example.com", use_cache=False)


def test_combined_cli_forwards_no_cache(monkeypatch, capsys):
    report = MagicMock(return_value={"host": "example.com"})
    monkeypatch.setattr(gsc_page_experience, "full_report", report)
    monkeypatch.setattr("sys.argv", ["gsc_page_experience", "--host", "example.com", "--no-cache"])
    assert gsc_page_experience.main() == 0
    report.assert_called_once_with("example.com", use_cache=False)
    assert json.loads(capsys.readouterr().out)["host"] == "example.com"
