"""Tests for the gsc_report markdown renderer."""

import gsc_report

AGENT_OUTPUTS = [
    {
        "agent": "gsc-overview",
        "summary": "site overview for sc-domain:example.com",
        "findings": [],
        "data": {"sitemap_count": 2},
    },
    {
        "agent": "gsc-core-web-vitals",
        "summary": "CrUX ALL_FORM_FACTORS: lcp_p75_ms=4500, inp_p75_ms=320, cls_p75=0.05",
        "findings": [
            {"severity": "High", "title": "lcp_p75_ms above the poor threshold",
             "detail": "Observed p75 4500 (good ≤ 2500, needs improvement ≤ 4000).",
             "metric": "lcp_p75_ms", "metric_value": 4500},
            {"severity": "Medium", "title": "inp_p75_ms above the needs-improvement threshold",
             "detail": "Observed p75 320 (good ≤ 200, needs improvement ≤ 500).",
             "metric": "inp_p75_ms", "metric_value": 320},
        ],
        "data": {"origin": "https://example.com"},
    },
]


OVERVIEW = {
    "site_url": "sc-domain:example.com",
    "permission_level": "siteOwner",
    "sitemap_count": 2,
    "last_sitemap_submitted": "2026-04-01T12:34:56Z",
    "homepage": {"status": 200, "title": "Acme Outfitters", "framework": "nextjs",
                  "platform": "shopify"},
}


def test_render_markdown_includes_site_context_section():
    md = gsc_report.render_markdown("sc-domain:example.com", AGENT_OUTPUTS,
                                     confidence="medium", overview=OVERVIEW)
    assert "## Site Context" in md
    assert "Acme Outfitters" in md
    assert "Inferred framework: nextjs" in md
    assert "Permission level: siteOwner" in md


def test_render_markdown_includes_confidence_in_header():
    md = gsc_report.render_markdown("sc-domain:example.com", AGENT_OUTPUTS,
                                     confidence="medium", overview=OVERVIEW)
    assert "Data confidence: **medium**" in md


def test_render_markdown_groups_findings_by_severity():
    md = gsc_report.render_markdown("sc-domain:example.com", AGENT_OUTPUTS,
                                     confidence="medium", overview=OVERVIEW)
    assert "### High" in md
    assert "### Medium" in md


def test_render_markdown_attaches_cwv_benchmark_annotation():
    md = gsc_report.render_markdown("sc-domain:example.com", AGENT_OUTPUTS,
                                     confidence="medium", overview=OVERVIEW)
    assert "verdict poor" in md
    assert "verdict needs_improvement" in md


def test_render_markdown_no_emoji():
    md = gsc_report.render_markdown("sc-domain:example.com", AGENT_OUTPUTS,
                                     confidence="medium", overview=OVERVIEW)
    for ch in md:
        cp = ord(ch)
        assert cp < 128 or ch in "–—‘’“”≤≥", (
            f"non-ASCII char in markdown output: {ch!r} (cp={cp})"
        )


def test_render_markdown_handles_no_overview():
    md = gsc_report.render_markdown("sc-domain:example.com", AGENT_OUTPUTS,
                                     confidence="medium", overview=None)
    assert "## Site Context" in md
    # No overview = no specific bullets, just the heading
    assert "Acme" not in md


def test_render_markdown_handles_no_findings():
    md = gsc_report.render_markdown("sc-domain:example.com", [],
                                     confidence="medium", overview=OVERVIEW)
    assert "_No findings._" in md

def test_html_has_context_benchmarks_summaries_and_source_data():
    html = gsc_report.render_html("example.com", AGENT_OUTPUTS, overview=OVERVIEW)
    for text in ["Acme Outfitters", "siteOwner", "verdict poor", "verdict needs_improvement",
                 "Executive Summary", "Per-Agent Output", "Source: gsc-core-web-vitals", "sitemap_count"]:
        assert text in html
    assert "@import" not in html


def test_html_escapes_all_payload_fields_and_does_not_expand_payload_placeholders():
    payload = '<script>alert(1)</script>" onmouseover="x'
    html = gsc_report.render_html("__FINDINGS__", [{"agent": payload, "summary": payload,
        "findings": [{"severity": payload, "title": payload, "detail": payload}],
        "data": {"value": payload}}], confidence=payload,
        overview={"homepage": {"title": payload}})
    assert '<script>' not in html
    assert '" onmouseover="' not in html
    assert "&lt;script&gt;" in html
    assert "__FINDINGS__" in html


def test_html_recovers_context_from_precollected_overview():
    html = gsc_report.render_html("example.com", [dict(agent="gsc-overview", data=OVERVIEW)])
    assert "Acme Outfitters" in html


def test_pdf_receives_the_complete_html_without_network(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    engine = MagicMock()
    monkeypatch.setitem(sys.modules, "weasyprint", SimpleNamespace(HTML=engine))
    html = gsc_report.render_html("example.com", AGENT_OUTPUTS, overview=OVERVIEW)
    path = str(tmp_path / "report.pdf")
    gsc_report.render_pdf(html, path)
    engine.assert_called_once_with(string=html)
    engine.return_value.write_pdf.assert_called_once_with(path)
