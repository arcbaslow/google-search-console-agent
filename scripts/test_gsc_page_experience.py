"""Tests for gsc_page_experience. All HTTP is mocked."""

import json
from unittest.mock import MagicMock, patch

import gsc_page_experience


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
        "scan_id": 42,
    }).encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = lambda *a: False
    return resp


def test_run_observatory_returns_grade(monkeypatch):
    """First POST succeeds, GET returns FINISHED on first poll."""
    monkeypatch.setattr(gsc_page_experience.time, "sleep", lambda *_a: None)
    with patch("urllib.request.urlopen", return_value=_mock_observatory_response()):
        out = gsc_page_experience.run_observatory("example.com")
    assert out["grade"] == "A+"
    assert out["score"] == 120


def test_run_observatory_post_409_continues_to_get(monkeypatch):
    """If POST returns 409 (cached scan), GET should still work."""
    import urllib.error
    monkeypatch.setattr(gsc_page_experience.time, "sleep", lambda *_a: None)
    post_err = urllib.error.HTTPError("u", 409, "conflict", {}, None)
    get_ok = _mock_observatory_response(grade="B")
    with patch("urllib.request.urlopen", side_effect=[post_err, get_ok]):
        out = gsc_page_experience.run_observatory("example.com")
    assert out["grade"] == "B"


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
    with patch("urllib.request.urlopen", side_effect=[in_progress, ready]):
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
