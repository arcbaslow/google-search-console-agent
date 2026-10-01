"""Tests for the gsc_audit orchestrator. Mocks every adapter so the test
runs without an API."""


import gsc_audit
import pytest


def test_origin_of_handles_sc_domain():
    assert gsc_audit._origin_of("sc-domain:example.com") == "https://example.com"


def test_origin_of_handles_url_prefix():
    assert gsc_audit._origin_of("https://example.com/") == "https://example.com"


def test_origin_excludes_path_query_fragment_but_keeps_port():
    assert gsc_audit._origin_of("https://example.com:8443/shop/?q=x#top") == "https://example.com:8443"


def test_cwv_uses_origin_for_prefix_property(monkeypatch):
    from unittest.mock import MagicMock

    query = MagicMock(return_value={"status": "no_data"})
    monkeypatch.setattr(gsc_audit.gsc_crux, "query_record", query)
    gsc_audit.run_cwv("https://example.com/shop/")
    query.assert_called_once_with(origin="https://example.com", form_factor="ALL_FORM_FACTORS")


def test_backlink_prefix_property_matches_its_exact_domain(monkeypatch):
    from unittest.mock import MagicMock

    query = MagicMock(return_value={"rows": [
        {"domain": "notexample.com", "open_pagerank_decimal": 8},
        {"domain": "example.com", "open_pagerank_decimal": 1},
    ]})
    monkeypatch.setattr(gsc_audit.gsc_backlinks, "compare_domains", query)
    result = gsc_audit.run_backlinks("https://example.com/shop/", ["notexample.com"])
    query.assert_called_once_with(["example.com", "notexample.com"])
    assert result["findings"]


def test_run_overview_flags_zero_sitemaps(monkeypatch):
    monkeypatch.setattr(gsc_audit.gsc_admin, "list_sites", lambda: [
        {"site_url": "sc-domain:example.com", "permission_level": "siteOwner"},
    ])
    monkeypatch.setattr(gsc_audit.gsc_admin, "list_sitemaps", lambda s: [])
    monkeypatch.setattr(gsc_audit, "_probe_homepage", lambda origin: {"status": 200, "title": "Acme"})

    out, overview = gsc_audit.run_overview("example.com")
    titles = [f["title"] for f in out["findings"]]
    assert any("No sitemaps" in t for t in titles)
    assert overview["sitemap_count"] == 0


def test_run_overview_flags_missing_property(monkeypatch):
    monkeypatch.setattr(gsc_audit.gsc_admin, "list_sites", lambda: [
        {"site_url": "sc-domain:other.example", "permission_level": "siteOwner"},
    ])
    monkeypatch.setattr(gsc_audit.gsc_admin, "list_sitemaps", lambda s: [])
    monkeypatch.setattr(gsc_audit, "_probe_homepage", lambda origin: {"status": 200})

    out, _ = gsc_audit.run_overview("example.com")
    assert any(f["severity"] == "Critical" for f in out["findings"])


def test_run_overview_flags_sitemap_errors(monkeypatch):
    monkeypatch.setattr(gsc_audit.gsc_admin, "list_sites", lambda: [
        {"site_url": "sc-domain:example.com", "permission_level": "siteOwner"},
    ])
    monkeypatch.setattr(gsc_audit.gsc_admin, "list_sitemaps", lambda s: [
        {"path": "https://example.com/sitemap.xml", "errors": 5, "warnings": 0,
         "lastSubmitted": "2026-01-01"},
    ])
    monkeypatch.setattr(gsc_audit, "_probe_homepage", lambda origin: {"status": 200})

    out, _ = gsc_audit.run_overview("example.com")
    titles = [f["title"] for f in out["findings"]]
    assert any("reports 5 errors" in t for t in titles)


def test_run_search_analytics_flags_traffic_drop(monkeypatch):
    """If second-half clicks are >20% below first-half, flag a High finding."""
    monkeypatch.setattr(gsc_audit.gsc_data, "top_queries", lambda *a, **kw: {"rows": []})
    monkeypatch.setattr(gsc_audit.gsc_data, "top_pages", lambda *a, **kw: {"rows": []})
    monkeypatch.setattr(gsc_audit.gsc_data, "by_device", lambda *a, **kw: {
        "rows": [
            {"device": "MOBILE", "clicks": 100, "impressions": 1000, "ctr": 0.1, "position": 5},
            {"device": "DESKTOP", "clicks": 50, "impressions": 800, "ctr": 0.0625, "position": 6},
        ],
    })
    monkeypatch.setattr(gsc_audit.gsc_data, "by_country", lambda *a, **kw: {"rows": []})

    # 90-day series: first 45 days strong, second 45 weak
    from datetime import date, timedelta
    ts_rows = [{"date": str(date(2026, 1, 1) + timedelta(days=i)),
                "clicks": 100 if i < 45 else 50} for i in range(90)]
    monkeypatch.setattr(gsc_audit.gsc_data, "time_series", lambda *a, **kw: {
        "rows": ts_rows, "start_date": "2026-01-01", "end_date": "2026-03-31"})

    out = gsc_audit.run_search_analytics("example.com", days=28)
    titles = [f["title"] for f in out["findings"]]
    assert any("clicks down" in t.lower() for t in titles)


def test_run_ctr_curve_flags_below_curve(monkeypatch):
    monkeypatch.setattr(gsc_audit.gsc_data, "top_queries", lambda *a, **kw: {
        "rows": [
            # Position 1, 30% CTR — expected ~40%, below curve
            {"query": "acme reviews", "clicks": 300, "impressions": 1000,
             "ctr": 0.30, "position": 1.0},
            # Position 5, 5.3% CTR — on curve
            {"query": "acme login", "clicks": 53, "impressions": 1000,
             "ctr": 0.053, "position": 5.0},
        ],
    })
    out = gsc_audit.run_ctr_curve("example.com", days=28)
    assert out["data"]["below_curve_count"] >= 1


def test_run_cwv_flags_poor_lcp(monkeypatch):
    monkeypatch.setattr(gsc_audit.gsc_crux, "query_record", lambda **kw: {
        "target": "https://example.com",
        "form_factor": "ALL_FORM_FACTORS",
        "status": "ok",
        "lcp_p75_ms": 4500,
        "inp_p75_ms": 150,
        "cls_p75": 0.05,
    })
    out = gsc_audit.run_cwv("example.com")
    lcp_findings = [f for f in out["findings"] if f.get("metric") == "lcp_p75_ms"]
    assert lcp_findings and lcp_findings[0]["metric_value"] == 4500


def test_run_cwv_reports_no_data(monkeypatch):
    monkeypatch.setattr(gsc_audit.gsc_crux, "query_record", lambda **kw: {
        "target": "https://example.com",
        "form_factor": "ALL_FORM_FACTORS",
        "status": "no_data",
    })
    out = gsc_audit.run_cwv("example.com")
    titles = [f["title"] for f in out["findings"]]
    assert any("Insufficient" in t for t in titles)


def test_orchestrate_end_to_end(monkeypatch):
    """orchestrate() returns the right shape with all agents stubbed."""
    def _ok_overview(s):
        return (gsc_audit._ok("gsc-overview", "ok", [], {"foo": "bar"}),
                {"site_url": "sc-domain:example.com", "homepage": {"status": 200}})

    monkeypatch.setattr(gsc_audit, "run_overview", _ok_overview)
    monkeypatch.setattr(gsc_audit, "run_search_analytics", lambda s, d: gsc_audit._ok("gsc-search-analytics", "ok"))
    monkeypatch.setattr(gsc_audit, "run_ctr_curve", lambda s, d, m: gsc_audit._ok("gsc-ctr-curve", "ok"))
    monkeypatch.setattr(gsc_audit, "run_cwv", lambda s, ff, h: gsc_audit._ok("gsc-core-web-vitals", "ok"))
    monkeypatch.setattr(gsc_audit, "run_structured_data",
                        lambda s, n: gsc_audit._ok("gsc-structured-data", "ok"))

    agents_out, overview, confidence = gsc_audit.orchestrate("example.com")
    agent_names = [a["agent"] for a in agents_out]
    assert agent_names == [
        "gsc-overview", "gsc-search-analytics", "gsc-ctr-curve",
        "gsc-core-web-vitals", "gsc-structured-data", "gsc-url-inspect",
    ]
    assert overview["site_url"] == "sc-domain:example.com"
    assert confidence == "medium"


def test_orchestrate_includes_optional_agents_when_flagged(monkeypatch):
    """Backlinks and page-experience are off by default; on when flagged."""
    def _ok_overview(s):
        return (gsc_audit._ok("gsc-overview", "ok"),
                {"site_url": "sc-domain:example.com"})

    monkeypatch.setattr(gsc_audit, "run_overview", _ok_overview)
    monkeypatch.setattr(gsc_audit, "run_search_analytics", lambda s, d: gsc_audit._ok("gsc-search-analytics", "ok"))
    monkeypatch.setattr(gsc_audit, "run_ctr_curve", lambda s, d, m: gsc_audit._ok("gsc-ctr-curve", "ok"))
    monkeypatch.setattr(gsc_audit, "run_cwv", lambda s, ff, h: gsc_audit._ok("gsc-core-web-vitals", "ok"))
    monkeypatch.setattr(gsc_audit, "run_structured_data",
                        lambda s, n: gsc_audit._ok("gsc-structured-data", "ok"))
    monkeypatch.setattr(gsc_audit, "run_backlinks",
                        lambda s, competitors: gsc_audit._ok("gsc-backlinks", "ok"))
    monkeypatch.setattr(gsc_audit, "run_page_experience",
                        lambda s: gsc_audit._ok("gsc-page-experience", "ok"))

    agents_out, _o, _c = gsc_audit.orchestrate(
        "example.com",
        with_backlinks=True, competitors=["competitor.com"],
        with_page_experience=True,
    )
    names = [a["agent"] for a in agents_out]
    assert "gsc-backlinks" in names
    assert "gsc-page-experience" in names
    # Stable ordering: backlinks before page-experience before url-inspect
    assert names.index("gsc-backlinks") < names.index("gsc-page-experience")
    assert names.index("gsc-page-experience") < names.index("gsc-url-inspect")


def test_run_structured_data_flags_no_jsonld(monkeypatch):
    monkeypatch.setattr(gsc_audit.gsc_structured_data, "analyze_sitemap_sample",
                        lambda site, sample_size: {
                            "site_url": site,
                            "sample_size": 10,
                            "rollup": {
                                "urls_analyzed": 10,
                                "urls_with_jsonld": 0,
                                "block_verdicts": {"pass": 0, "partial": 0, "fail": 0, "untyped": 0},
                            },
                            "per_url": [],
                        })
    out = gsc_audit.run_structured_data("example.com", sample_size=10)
    titles = [f["title"] for f in out["findings"]]
    assert any("No JSON-LD" in t for t in titles)


def test_run_backlinks_flags_low_open_pagerank(monkeypatch):
    monkeypatch.setattr(gsc_audit.gsc_backlinks, "compare_domains",
                        lambda doms: {"primary": "example.com",
                                       "rows": [{"domain": "example.com",
                                                  "tranco_rank": 50000,
                                                  "tranco_band": "top_100k",
                                                  "open_pagerank_decimal": 1.2}]})
    out = gsc_audit.run_backlinks("example.com", competitors=["competitor.com"])
    titles = [f["title"] for f in out["findings"]]
    assert any("low backlink authority" in t.lower() for t in titles)


def test_run_page_experience_flags_low_observatory(monkeypatch):
    monkeypatch.setattr(gsc_audit.gsc_page_experience, "full_report",
                        lambda host: {
                            "host": host,
                            "headers": {"grade": "good", "coverage_pct": 100, "headers_missing": []},
                            "observatory": {"grade": "F", "score": -10,
                                            "tests_passed": 5, "tests_quantity": 11},
                            "ssl_labs": {"grade": "A"},
                        })
    out = gsc_audit.run_page_experience("example.com")
    titles = [f["title"] for f in out["findings"]]
    assert any("Mozilla Observatory grade F" in t for t in titles)


@pytest.mark.parametrize("failed,name", [
    ("run_overview", "gsc-overview"),
    ("run_search_analytics", "gsc-search-analytics"),
    ("run_ctr_curve", "gsc-ctr-curve"),
    ("run_cwv", "gsc-core-web-vitals"),
    ("run_structured_data", "gsc-structured-data"),
    ("run_backlinks", "gsc-backlinks"),
    ("run_page_experience", "gsc-page-experience"),
])
def test_orchestrate_preserves_other_workers_when_one_raises(monkeypatch, failed, name):
    names = {
        "run_search_analytics": "gsc-search-analytics", "run_ctr_curve": "gsc-ctr-curve",
        "run_cwv": "gsc-core-web-vitals", "run_structured_data": "gsc-structured-data",
        "run_backlinks": "gsc-backlinks", "run_page_experience": "gsc-page-experience",
    }
    monkeypatch.setattr(gsc_audit, "run_overview", lambda _: (
        gsc_audit._ok("gsc-overview", "ok"), {"site_url": "sc-domain:example.com"}))
    for function, agent in names.items():
        monkeypatch.setattr(gsc_audit, function,
                            lambda *a, _agent=agent, **kw: gsc_audit._ok(_agent, "retained"))

    def broken(*a, **kw):
        raise TimeoutError("source timed out")

    monkeypatch.setattr(gsc_audit, failed, broken)
    output, overview, confidence = gsc_audit.orchestrate(
        "example.com", with_backlinks=True, with_page_experience=True)
    assert len(output) == 8
    assert [a["agent"] for a in output] == ["gsc-overview", *names.values(), "gsc-url-inspect"]
    failure = next(a for a in output if a["agent"] == name)
    assert failure["status"] == "error"
    assert failure["data"]["error"] == "TimeoutError"
    assert all(a["summary"] == "retained" for a in output
               if a["agent"] in names.values() and a["agent"] != name)
    assert overview["site_url"] == "sc-domain:example.com"
    assert confidence == ("low" if name == "gsc-search-analytics" else "medium")


def test_page_experience_errors_are_visible_findings(monkeypatch):
    monkeypatch.setattr(gsc_audit.gsc_page_experience, "full_report", lambda _: {
        "headers": {"grade": "good"}, "observatory": {"error": "transport"},
        "ssl_labs": {"error": "timeout"},
    })
    out = gsc_audit.run_page_experience("example.com")
    assert "headers good" in out["summary"]
    assert "observatory unavailable" in out["summary"]
    assert len(out["findings"]) == 2


@pytest.mark.parametrize("errors,warnings,expected", [
    ("0", "0", None), ("0", "3", "3 warnings"), ("2", "0", "2 errors"),
    (0, 0, None), (None, None, None),
])
def test_sitemap_counts_use_numeric_values(monkeypatch, errors, warnings, expected):
    monkeypatch.setattr(gsc_audit.gsc_admin, "list_sites", lambda: [
        {"site_url": "sc-domain:example.com"},
    ])
    monkeypatch.setattr(gsc_audit.gsc_admin, "list_sitemaps", lambda _: [
        {"path": "https://example.com/sitemap.xml", "errors": errors, "warnings": warnings},
    ])
    monkeypatch.setattr(gsc_audit, "_probe_homepage", lambda _: {"status": 200})
    output, overview = gsc_audit.run_overview("example.com")
    if expected:
        assert expected in output["findings"][0]["title"]
    else:
        assert output["findings"] == []
    assert overview["sitemap_count"] == 1


def test_failed_fetches_do_not_claim_missing_structured_data(monkeypatch):
    monkeypatch.setattr(gsc_audit.gsc_structured_data, "analyze_sitemap_sample", lambda *a, **kw: {
        "rollup": {"urls_analyzed": 0, "urls_attempted": 2, "fetch_failures": 2,
                   "urls_with_jsonld": 0, "block_verdicts": {}},
    })
    out = gsc_audit.run_structured_data("example.com")
    assert any("could not be fetched" in f["title"] for f in out["findings"])
    assert not any("No JSON-LD" in f["title"] for f in out["findings"])

def test_backlink_audit_uses_both_sources_without_competitors(monkeypatch):
    from unittest.mock import MagicMock

    query = MagicMock(return_value={"rows": [
        {"domain": "example.com", "tranco_band": "unavailable", "tranco_error": "timeout",
         "open_pagerank_decimal": 4.2},
    ]})
    monkeypatch.setattr(gsc_audit.gsc_backlinks, "compare_domains", query)
    out = gsc_audit.run_backlinks("example.com")
    query.assert_called_once_with(["example.com"])
    assert "Open PageRank 4.2" in out["summary"]
    assert any(f["title"] == "Tranco unavailable" for f in out["findings"])


def test_competitor_rank_does_not_match_a_domain_suffix(monkeypatch):
    monkeypatch.setattr(gsc_audit.gsc_backlinks, "compare_domains", lambda domains: {"rows": [
        {"domain": "notexample.com", "tranco_rank": 10},
        {"domain": "example.com", "tranco_rank": 20},
    ]})
    out = gsc_audit.run_backlinks("example.com", ["notexample.com"])
    assert any("#2 of 2" in f["title"] for f in out["findings"])

def test_header_failure_is_reported_once_with_other_source_results(monkeypatch):
    monkeypatch.setattr(gsc_audit.gsc_page_experience, "full_report", lambda _: {
        "headers": {"error": "transport", "message": "header timeout"},
        "observatory": {"grade": "A"}, "ssl_labs": {"grade": "A"},
    })
    out = gsc_audit.run_page_experience("example.com")
    assert len(out["findings"]) == 1
    assert out["findings"][0]["detail"] == "header timeout"
    assert "headers unavailable" in out["summary"]
    assert "observatory A" in out["summary"]
    assert "ssl-labs A" in out["summary"]

def test_calendar_trend_uses_equal_windows_and_ignores_leading_odd_day():
    series = {"start_date": "2026-01-01", "end_date": "2026-01-15",
              "rows": [{"date": f"2026-01-{i:02d}", "clicks": 999 if i == 1 else 10}
                       for i in range(1, 16)]}
    result = gsc_audit.calendar_trend(series)
    assert result["change_pct"] == 0
    assert result["previous_start"] == "2026-01-02"
    assert result["days_per_period"] == 7
    assert result["excluded_leading_days"] == 1
    series["rows"].pop()
    result = gsc_audit.calendar_trend(series)
    assert result["status"] == "incomplete"
    assert result["recent_missing_days"] == 1
    assert result["change_pct"] is None


def test_calendar_trend_zero_baseline_and_partial_data_have_no_percentage():
    series = {"start_date": "2026-01-01", "end_date": "2026-01-14",
              "rows": [{"date": f"2026-01-{i:02d}", "clicks": 0} for i in range(1, 15)]}
    assert gsc_audit.calendar_trend(series)["reason"] == "zero_previous_clicks"
    series["metadata"] = {"first_incomplete_date": "2026-01-14"}
    assert gsc_audit.calendar_trend(series)["status"] == "incomplete"

@pytest.mark.parametrize("data,status,expected", [
    ({}, None, "medium"),
    ({"source_errors": {"by_country": "TimeoutError"}}, None, "low"),
    ({"click_trend": {"status": "incomplete"}}, None, "low"),
    ({}, "error", "low"),
])
def test_confidence_uses_availability_not_finding_severity(monkeypatch, data, status, expected):
    monkeypatch.setattr(gsc_audit, "run_overview", lambda *a: (gsc_audit._ok("overview", "ok"), {}))
    for name in ["run_ctr_curve", "run_cwv", "run_structured_data"]:
        monkeypatch.setattr(gsc_audit, name, lambda *a: gsc_audit._ok("other", "ok"))
    result = gsc_audit._ok("gsc-search-analytics", "ok", [
        {"severity": "High", "title": "Confirmed traffic decline"}], data)
    result["status"] = status
    monkeypatch.setattr(gsc_audit, "run_search_analytics", lambda *a: result)
    assert gsc_audit.orchestrate("example.com")[2] == expected


def test_partial_search_failure_is_machine_readable(monkeypatch):
    for name in ["top_queries", "top_pages", "by_device", "by_country", "time_series"]:
        monkeypatch.setattr(gsc_audit.gsc_data, name, lambda *a, **kw: {"rows": []})
    def failed(*a, **kw):
        raise TimeoutError("unavailable")
    monkeypatch.setattr(gsc_audit.gsc_data, "by_country", failed)
    out = gsc_audit.run_search_analytics("example.com")
    assert out["data"]["source_errors"] == {"by_country": "TimeoutError"}
    assert "top_queries" in out["data"]

def test_audit_redacts_display_after_using_exact_target(monkeypatch, capsys):
    import json
    from unittest.mock import MagicMock
    site = "https://example.com/user@example.com/"
    source = {"agent": "test", "data": {"url": site}, "findings": []}
    runner = MagicMock(return_value=([source], {"site_url": site}, "medium"))
    monkeypatch.setattr(gsc_audit, "orchestrate", runner)
    monkeypatch.setattr(gsc_audit.gsc_auth, "get_credentials", lambda **kw: object())
    monkeypatch.setattr("sys.argv", ["gsc_audit", "--site", site, "--format", "json", "--redact"])
    assert gsc_audit.main() == 0
    assert runner.call_args.kwargs["site_url"] == site
    out = json.loads(capsys.readouterr().out)
    assert "user@example.com" not in json.dumps(out)
    assert source["data"]["url"] == site
