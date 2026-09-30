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
