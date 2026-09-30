"""CrUX wire contracts, missing data and cache behavior; no live calls."""

import io
import json
import urllib.error
from unittest.mock import MagicMock

import gsc_crux
import pytest


@pytest.mark.parametrize("method", [gsc_crux.query_record, gsc_crux.query_history])
@pytest.mark.parametrize("factor", gsc_crux.FORM_FACTORS)
def test_request_form_factor_contract(monkeypatch, method, factor):
    post = MagicMock(return_value={"record": {}})
    monkeypatch.setattr(gsc_crux, "_post", post)
    method(origin="https://example.com", form_factor=factor)
    body = post.call_args.args[1]
    assert body["origin"] == "https://example.com"
    if factor == "ALL_FORM_FACTORS":
        assert "formFactor" not in body
    else:
        assert body["formFactor"] == factor
    assert "url" not in body


@pytest.mark.parametrize("periods", [0, -1, 41, 2.5, True])
def test_invalid_history_periods_do_not_request(monkeypatch, periods):
    post = MagicMock()
    monkeypatch.setattr(gsc_crux, "_post", post)
    with pytest.raises(ValueError, match="between 1 and 40"):
        gsc_crux.query_history(url="https://example.com/a", collection_period_count=periods)
    post.assert_not_called()


def test_history_periods_and_target_are_part_of_cache_key(monkeypatch):
    post = MagicMock(return_value={"record": {}})
    monkeypatch.setattr(gsc_crux, "_post", post)
    for periods in [25, 40, 40]:
        gsc_crux.query_history(url="https://example.com/a", collection_period_count=periods)
    assert post.call_count == 2
    assert post.call_args.args == (gsc_crux.CRUX_HISTORY_URL, {
        "url": "https://example.com/a", "collectionPeriodCount": 40,
    })


def test_history_missing_values_are_json_null():
    response = {"record": {"collectionPeriods": [{}, {}, {}, {}], "metrics": {
        "cumulative_layout_shift": {"percentilesTimeseries": {"p75s": ["0.10", "NaN", None, "0.2"]}},
        "largest_contentful_paint": {"percentilesTimeseries": {"p75s": [1000, "NaN", None, 3000]}},
    }}}
    result = gsc_crux._flatten_history(response, "https://example.com", "PHONE")
    assert result["history"]["cls_p75"] == [0.1, None, None, 0.2]
    assert result["history"]["lcp_p75_ms"] == [1000, None, None, 3000]
    json.dumps(result, allow_nan=False)


def test_snapshot_numeric_cls_and_absent_metrics():
    result = gsc_crux._flatten_record({"record": {"metrics": {
        "cumulative_layout_shift": {"percentiles": {"p75": "0.05"}},
    }}}, "https://example.com", "PHONE")
    assert result["cls_p75"] == 0.05
    assert "lcp_p75_ms" not in result


def test_post_uses_json_bearer_and_timeout(monkeypatch):
    monkeypatch.setattr(gsc_crux, "_bearer_token", lambda: "synthetic")
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b'{"record":{}}'
    fetch = MagicMock(return_value=response)
    monkeypatch.setattr("urllib.request.urlopen", fetch)
    assert gsc_crux._post(gsc_crux.CRUX_QUERY_URL, {"origin": "https://example.com"}) == {"record": {}}
    req = fetch.call_args.args[0]
    assert req.method == "POST"
    assert req.get_header("Authorization") == "Bearer synthetic"
    assert json.loads(req.data) == {"origin": "https://example.com"}
    assert fetch.call_args.kwargs["timeout"] == 30
    response.__exit__.assert_called_once()


@pytest.mark.parametrize("status", [403, 429, 500])
def test_post_errors_are_not_retried(monkeypatch, status):
    monkeypatch.setattr(gsc_crux, "_bearer_token", lambda: "synthetic")
    fetch = MagicMock(side_effect=urllib.error.HTTPError(
        "url", status, "error", {}, io.BytesIO(b'{"error":"unavailable"}')))
    monkeypatch.setattr("urllib.request.urlopen", fetch)
    with pytest.raises(RuntimeError, match=f"CrUX HTTP {status}"):
        gsc_crux.query_record(origin="https://example.com")
    fetch.assert_called_once()


def test_no_data_is_cached_and_no_cache_bypasses_it(monkeypatch):
    monkeypatch.setattr(gsc_crux, "_bearer_token", lambda: "synthetic")
    fetch = MagicMock(side_effect=lambda *a, **kw: (_ for _ in ()).throw(
        urllib.error.HTTPError("url", 404, "absent", {}, io.BytesIO(b"no data"))))
    monkeypatch.setattr("urllib.request.urlopen", fetch)
    for _ in range(2):
        assert gsc_crux.query_record(origin="https://example.com")["status"] == "no_data"
    assert fetch.call_count == 1
    gsc_crux.query_record(origin="https://example.com", use_cache=False)
    assert fetch.call_count == 2
