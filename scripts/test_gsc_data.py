"""Tests for the GSC search analytics adapter."""

from unittest.mock import MagicMock

import pytest

import gsc_data


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
