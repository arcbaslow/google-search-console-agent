"""Tests for the gsc_audit orchestrator. Mocks every adapter so the test
runs without an API."""


import gsc_audit


def test_origin_of_handles_sc_domain():
    assert gsc_audit._origin_of("sc-domain:example.com") == "https://example.com"


def test_origin_of_handles_url_prefix():
    assert gsc_audit._origin_of("https://example.com/") == "https://example.com"


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
    ts_rows = [{"date": f"2026-{i:02d}", "clicks": 100} for i in range(45)] + \
              [{"date": f"2026-{i:02d}", "clicks": 50} for i in range(45)]
    monkeypatch.setattr(gsc_audit.gsc_data, "time_series", lambda *a, **kw: {"rows": ts_rows})

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
