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
    monkeypatch.setattr(gsc_crux, "_auth_headers", lambda: {"Authorization": "Bearer synthetic"})
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
    monkeypatch.setattr(gsc_crux, "_auth_headers", lambda: {"Authorization": "Bearer synthetic"})
    fetch = MagicMock(side_effect=urllib.error.HTTPError(
        "url", status, "error", {}, io.BytesIO(b'{"error":"unavailable"}')))
    monkeypatch.setattr("urllib.request.urlopen", fetch)
    with pytest.raises(RuntimeError, match=f"CrUX HTTP {status}"):
        gsc_crux.query_record(origin="https://example.com")
    fetch.assert_called_once()


def test_no_data_is_cached_and_no_cache_bypasses_it(monkeypatch):
    monkeypatch.setattr(gsc_crux, "_auth_headers", lambda: {"Authorization": "Bearer synthetic"})
    fetch = MagicMock(side_effect=lambda *a, **kw: (_ for _ in ()).throw(
        urllib.error.HTTPError("url", 404, "absent", {}, io.BytesIO(b"no data"))))
    monkeypatch.setattr("urllib.request.urlopen", fetch)
    for _ in range(2):
        assert gsc_crux.query_record(origin="https://example.com")["status"] == "no_data"
    assert fetch.call_count == 1
    gsc_crux.query_record(origin="https://example.com", use_cache=False)
    assert fetch.call_count == 2

@pytest.mark.parametrize("history", [False, True])
def test_diagnostics_preserve_distributions_and_missing_periods(monkeypatch, history):
    metrics = {
        "largest_contentful_paint": {"histogram": [{"start": 0, "end": 2500, "density": .8}]},
        "round_trip_time": {"percentilesTimeseries": {"p75s": [150, "NaN"]}},
        "largest_contentful_paint_resource_type": {"fractions": {"image": .7, "text": .3}},
        "largest_contentful_paint_image_resource_load_delay": {"percentiles": {"p75": 150}},
    }
    post = MagicMock(return_value={"record": {"metrics": metrics}})
    monkeypatch.setattr(gsc_crux, "_post", post)
    method = gsc_crux.query_history if history else gsc_crux.query_record
    assert "diagnostics" not in method(origin="https://example.com")
    out = method(origin="https://example.com", diagnostics=True)
    assert post.call_count == 2
    detail = out["diagnostics"]["metrics"]
    assert detail["largest_contentful_paint_resource_type"]["fractions"]["image"] == .7
    assert detail["round_trip_time"]["percentilesTimeseries"]["p75s"] == [150, None]
    assert "histogram" in detail["largest_contentful_paint"]
    json.dumps(out, allow_nan=False)
    assert method(origin="https://example.com", diagnostics=True) == out
    assert post.call_count == 2


def test_crux_cli_exposes_diagnostics(monkeypatch, capsys):
    query = MagicMock(return_value={})
    monkeypatch.setattr(gsc_crux, "query_record", query)
    monkeypatch.setattr("sys.argv", ["gsc_crux", "--origin", "https://example.com", "--diagnostics"])
    assert gsc_crux.main() == 0
    assert query.call_args.kwargs["diagnostics"] is True



API_KEY = "synthetic-api-key-0123456789"


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("PAGESPEED_API_KEY", API_KEY)
    lookup = MagicMock(side_effect=AssertionError("no credential lookup with an API key"))
    monkeypatch.setattr(gsc_crux, "_auth_headers", lookup)
    monkeypatch.setattr(gsc_crux, "get_credentials", lookup)
    return lookup


def ok_response():
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b'{"record":{}}'
    return response


def test_api_key_is_a_query_parameter_with_no_authorization_or_credential_lookup(
        keyed, monkeypatch):
    fetch = MagicMock(return_value=ok_response())
    monkeypatch.setattr("urllib.request.urlopen", fetch)
    gsc_crux._post(gsc_crux.CRUX_QUERY_URL, {"origin": "https://example.com"})
    req = fetch.call_args.args[0]
    assert req.full_url == f"{gsc_crux.CRUX_QUERY_URL}?key={API_KEY}"
    assert req.method == "POST" and not req.has_header("Authorization")
    assert req.get_header("Content-type") == "application/json"
    assert json.loads(req.data) == {"origin": "https://example.com"}
    keyed.assert_not_called()


def test_without_a_key_the_url_has_no_query_and_the_bearer_token_is_sent(monkeypatch):
    monkeypatch.setattr(gsc_crux, "_auth_headers", lambda: {"Authorization": "Bearer synthetic"})
    fetch = MagicMock(return_value=ok_response())
    monkeypatch.setattr("urllib.request.urlopen", fetch)
    monkeypatch.setenv("PAGESPEED_API_KEY", "  ")
    gsc_crux._post(gsc_crux.CRUX_HISTORY_URL, {"origin": "https://example.com"})
    req = fetch.call_args.args[0]
    assert req.full_url == gsc_crux.CRUX_HISTORY_URL
    assert req.get_header("Authorization") == "Bearer synthetic"


@pytest.mark.parametrize("method", [gsc_crux.query_record, gsc_crux.query_history])
def test_api_key_stays_out_of_the_cache_and_does_not_change_its_identity(
        keyed, monkeypatch, tmp_cache_dir, method):
    fetch = MagicMock(side_effect=lambda *a, **kw: ok_response())
    monkeypatch.setattr("urllib.request.urlopen", fetch)
    first = method(origin="https://example.com")
    files = list((tmp_cache_dir / "gsc-cache").iterdir())
    assert files
    for path in files:
        assert API_KEY not in path.name and API_KEY not in path.read_text(encoding="utf-8")
    monkeypatch.delenv("PAGESPEED_API_KEY")
    assert method(origin="https://example.com") == first
    assert fetch.call_count == 1


@pytest.mark.parametrize("status", [400, 403, 429, 500])
def test_errors_never_echo_the_request_url_or_key(keyed, monkeypatch, status):
    echo = json.dumps({"error": {"message": f"Bad request: {gsc_crux.CRUX_QUERY_URL}?key={API_KEY}",
                                 "status": "INVALID_ARGUMENT"}}).encode()
    monkeypatch.setattr("urllib.request.urlopen", MagicMock(side_effect=urllib.error.HTTPError(
        f"{gsc_crux.CRUX_QUERY_URL}?key={API_KEY}", status, "error", {}, io.BytesIO(echo))))
    with pytest.raises(RuntimeError) as caught:
        gsc_crux.query_record(origin="https://example.com", use_cache=False)
    assert API_KEY not in str(caught.value) and API_KEY not in json.dumps(caught.value.details)


def test_no_data_result_does_not_carry_an_echoed_body_or_key(keyed, monkeypatch):
    body = f"no data for {gsc_crux.CRUX_QUERY_URL}?key={API_KEY}".encode()
    monkeypatch.setattr("urllib.request.urlopen", MagicMock(side_effect=urllib.error.HTTPError(
        "url", 404, "absent", {}, io.BytesIO(body))))
    out = gsc_crux.query_record(origin="https://example.com", use_cache=False)
    assert out["status"] == "no_data" and API_KEY not in json.dumps(out)


def test_cli_help_mentions_the_api_key_variable(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["gsc_crux.py", "--help"])
    with pytest.raises(SystemExit):
        gsc_crux.main()
    assert "PAGESPEED_API_KEY" in capsys.readouterr().out
