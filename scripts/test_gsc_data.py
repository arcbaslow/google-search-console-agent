"""Tests for the GSC search analytics adapter."""

from unittest.mock import MagicMock

import gsc_data
import pytest


def test_parse_filter_equals():
    out = gsc_data.parse_filter("query EQUALS 'pricing'")
    assert out == {"dimension": "query", "operator": "equals", "expression": "pricing"}


def test_parse_filter_contains():
    out = gsc_data.parse_filter("page CONTAINS '/blog/'")
    assert out == {"dimension": "page", "operator": "contains", "expression": "/blog/"}


def test_parse_filter_not_equals():
    out = gsc_data.parse_filter("country != 'usa'")
    assert out == {"dimension": "country", "operator": "notEquals", "expression": "usa"}


def test_parse_filter_regex():
    out = gsc_data.parse_filter("query INCLUDING_REGEX '^how to'")
    assert out == {"dimension": "query", "operator": "includingRegex", "expression": "^how to"}


def test_parse_filter_returns_none_for_empty():
    assert gsc_data.parse_filter("") is None
    assert gsc_data.parse_filter(None) is None


def test_parse_filter_raises_on_garbage():
    with pytest.raises(ValueError):
        gsc_data.parse_filter("not a filter")


def test_query_unknown_dimension_raises(monkeypatch):
    monkeypatch.setattr(gsc_data, "_get_service", lambda: None)
    with pytest.raises(ValueError, match="unknown dimension"):
        gsc_data.query("example.com", dimensions=["bogus"], days=7, use_cache=False)


def test_query_unknown_search_type_raises(monkeypatch):
    monkeypatch.setattr(gsc_data, "_get_service", lambda: None)
    with pytest.raises(ValueError, match="search_type"):
        gsc_data.query("example.com", dimensions=["query"], search_type="podcast", use_cache=False)


def test_query_flattens_rows_and_normalizes_site(monkeypatch):
    """Mock the searchconsole service and verify the response is flattened."""
    mock_service = MagicMock()
    mock_service.searchanalytics().query().execute.return_value = {
        "rows": [
            {"keys": ["pricing"], "clicks": 120, "impressions": 1000,
             "ctr": 0.12, "position": 3.2},
            {"keys": ["acme"], "clicks": 50, "impressions": 200,
             "ctr": 0.25, "position": 1.5},
        ],
        "responseAggregationType": "byProperty",
    }
    monkeypatch.setattr(gsc_data, "_get_service", lambda: mock_service)

    out = gsc_data.query("example.com", dimensions=["query"], days=7, use_cache=False)

    assert out["site_url"] == "sc-domain:example.com"   # bare domain → sc-domain:
    assert out["row_count"] == 2
    assert out["rows"][0] == {
        "query": "pricing", "clicks": 120, "impressions": 1000,
        "ctr": 0.12, "position": 3.2,
    }


def test_query_uses_cache(monkeypatch):
    mock_service = MagicMock()
    mock_service.searchanalytics().query().execute.return_value = {"rows": []}
    monkeypatch.setattr(gsc_data, "_get_service", lambda: mock_service)

    out1 = gsc_data.query("example.com", dimensions=["query"], days=7, use_cache=True)
    out2 = gsc_data.query("example.com", dimensions=["query"], days=7, use_cache=True)
    assert out1 == out2
    # Service should only be called once
    assert mock_service.searchanalytics().query().execute.call_count == 1


def test_top_queries_wraps_query(monkeypatch):
    """top_queries should call query() with dimensions=['query']."""
    captured = {}

    def fake_query(site_url, dimensions=None, **kw):
        captured["dimensions"] = dimensions
        return {"rows": []}

    monkeypatch.setattr(gsc_data, "query", fake_query)
    gsc_data.top_queries("example.com", days=7, row_limit=10)
    assert captured["dimensions"] == ["query"]

@pytest.mark.parametrize("row_limit,start_row", [
    (0, 0), (25001, 0), (1.5, 0), (True, 0), (100, -1), (100, 1.5), (100, True),
])
def test_page_bounds_fail_before_authentication(monkeypatch, row_limit, start_row):
    service = MagicMock(side_effect=AssertionError("no authentication"))
    monkeypatch.setattr(gsc_data, "_get_service", service)
    with pytest.raises(ValueError):
        gsc_data.query("example.com", row_limit=row_limit, start_row=start_row)
    service.assert_not_called()


def test_explicit_page_is_one_request_and_has_distinct_cache_identity(monkeypatch):
    service = MagicMock()
    execute = service.searchanalytics.return_value.query.return_value.execute
    execute.side_effect = [
        {"rows": [{"keys": ["first"], "clicks": 1}]},
        {"rows": [{"keys": ["second"], "clicks": 2}]},
    ]
    monkeypatch.setattr(gsc_data, "_get_service", lambda: service)
    first = gsc_data.query("example.com", dimensions=["query"], row_limit=25000)
    second = gsc_data.query("example.com", dimensions=["query"], row_limit=25000, start_row=25000)
    assert first["rows"][0]["query"] == "first"
    assert second["rows"][0]["query"] == "second"
    assert service.searchanalytics.return_value.query.call_args.kwargs["body"]["startRow"] == 25000
    assert service.searchanalytics.return_value.query.call_args.kwargs["body"]["rowLimit"] == 25000
    assert gsc_data.query("example.com", dimensions=["query"], row_limit=25000, start_row=25000) == second
    assert execute.call_count == 2


@pytest.mark.parametrize("mode", ["--queries", "--pages", "--devices", "--countries", "--appearance", "--timeseries", "--report"])
def test_cli_forwards_explicit_offset_to_every_read_mode(monkeypatch, mode, capsys):
    import json

    query = MagicMock(return_value={"rows": []})
    monkeypatch.setattr(gsc_data, "query", query)
    monkeypatch.setattr("sys.argv", ["gsc_data.py", "--site", "example.com", mode, "--start-row", "200"])
    assert gsc_data.main() == 0
    query.assert_called_once()
    assert query.call_args.kwargs["start_row"] == 200
    assert json.loads(capsys.readouterr().out) == {"rows": []}

def test_cached_queries_repair_mixed_redaction_without_api_call(monkeypatch):
    import gsc_utils

    monkeypatch.setattr(gsc_data, "date_range", lambda days: ("2026-09-01", "2026-09-28"))
    parts = ("query", "sc-domain:example.com", ("query",), "web", 1000, 0,
             None, "final", "2026-09-01", "2026-09-28")
    cached = {"rows": [{"query": "[email-redacted] and encoded%40example.com", "clicks": 10}]}
    gsc_utils.cache_set(cached, *parts)
    factory = MagicMock(side_effect=AssertionError("cached result must not fetch"))
    monkeypatch.setattr(gsc_data, "_get_service", factory)
    result = gsc_data.query("example.com", dimensions=["query"])
    assert result["rows"][0] == {"query": "[email-redacted] and [email-redacted]", "clicks": 10}
    assert gsc_utils.cache_get(*parts) == result
    factory.assert_not_called()


def test_clean_cached_query_does_not_extend_its_lifetime(monkeypatch):
    cached = {"rows": [{"query": "example", "clicks": 10}]}
    monkeypatch.setattr(gsc_data, "cache_get", lambda *parts: cached)
    write = MagicMock()
    monkeypatch.setattr(gsc_data, "cache_set", write)
    assert gsc_data.query("example.com", dimensions=["query"]) == cached
    write.assert_not_called()

@pytest.mark.parametrize("kw", [
    {"start_date": "2026-01-01"}, {"days": 0},
    {"start_date": "2026-02-30", "end_date": "2026-03-01"},
    {"start_date": "2026-02-02", "end_date": "2026-02-01"},
    {"start_date": "20260101", "end_date": "2026-01-02"},
    {"dimensions": ["hour"]}, {"data_state": "hourly_all"},
    {"dimensions": ["hour"], "data_state": "hourly_all"},
    {"dimensions": ["query", "query"]},
])
def test_date_and_hour_validation_before_auth(monkeypatch, kw):
    monkeypatch.setattr(gsc_data, "_get_service", lambda: pytest.fail("no auth"))
    with pytest.raises(ValueError):
        gsc_data.query("example.com", **kw)


def test_hourly_request_preserves_partial_metadata_and_offset(monkeypatch):
    service = MagicMock()
    metadata = {"first_incomplete_hour": "2026-10-01T02:00:00-07:00"}
    service.searchanalytics().query().execute.return_value = {
        "rows": [{"keys": ["2026-10-01T02:00:00-07:00"], "clicks": 2}], "metadata": metadata}
    monkeypatch.setattr(gsc_data, "_get_service", lambda: service)
    out = gsc_data.query("example.com", dimensions=["hour"], data_state="hourly_all",
                         start_date="2026-10-01", end_date="2026-10-01")
    body = service.searchanalytics.return_value.query.call_args.kwargs["body"]
    assert body["startDate"] == body["endDate"] == "2026-10-01"
    assert body["dimensions"] == ["hour"]
    assert out["metadata"] == metadata
    assert out["rows"][0]["hour"] == "2026-10-01T02:00:00-07:00"


def test_explicit_timeseries_sizes_rows_for_date_range(monkeypatch):
    query = MagicMock(return_value={})
    monkeypatch.setattr(gsc_data, "query", query)
    gsc_data.time_series("example.com", start_date="2026-01-01", end_date="2026-03-31")
    assert query.call_args.kwargs["row_limit"] == 95


def test_paired_comparison_uses_two_aggregate_requests(monkeypatch):
    service = MagicMock()
    execute = service.searchanalytics.return_value.query.return_value.execute
    execute.side_effect = [{"rows": [{"clicks": 12, "impressions": 100, "ctr": .12, "position": 2}]},
                           {"rows": [{"clicks": 10, "impressions": 100, "ctr": .1, "position": 3}]}]
    monkeypatch.setattr(gsc_data, "_get_service", lambda: service)
    out = gsc_data.compare_periods("example.com", "2026-03-01", "2026-03-07")
    assert out["previous"]["start_date"] == "2026-02-22"
    assert out["previous"]["end_date"] == "2026-02-28"
    assert out["changes"]["clicks_change_pct"] == 20
    assert out["changes"]["ctr_change_percentage_points"] == 2
    assert out["changes"]["position_change"] == -1
    assert execute.call_count == 2


def test_cli_explicit_dates_and_comparison(monkeypatch, capsys):
    query = MagicMock(return_value={"rows": [{"clicks": 0, "impressions": 0, "ctr": 0, "position": 0}]})
    monkeypatch.setattr(gsc_data, "query", query)
    monkeypatch.setattr("sys.argv", ["gsc_data", "--site", "example.com", "--compare-previous",
        "--start-date", "2026-01-01", "--end-date", "2026-01-07"])
    assert gsc_data.main() == 0
    assert query.call_count == 2
    assert '"clicks_change_pct": null' in capsys.readouterr().out
