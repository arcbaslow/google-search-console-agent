"""
Full GSC audit, end-to-end, from a single command. Works on any runtime.

Pipeline:

  1. verify auth
  2. resolve site overview (sites.list -> permission level + sitemaps + a
     plain-HTTP probe of the homepage for framework / platform hints)
  3. fan out the mechanical "agents":
       - site overview (synthetic)
       - search analytics (queries, pages, devices, countries, time-series)
       - CTR-vs-curve (uses position + CTR per query)
       - sitemaps (list + error checks)
       - Core Web Vitals (CrUX origin snapshot + history)
  4. render markdown / HTML / PDF report

CLI:
  python scripts/gsc_audit.py --site example.com
  python scripts/gsc_audit.py --site example.com --output audit.md
  python scripts/gsc_audit.py --site example.com --format html --output audit.html
  python scripts/gsc_audit.py --site example.com --days 90 --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import gsc_admin
import gsc_auth
import gsc_backlinks
import gsc_benchmarks
import gsc_crux
import gsc_data
import gsc_page_experience
import gsc_report
import gsc_structured_data
from gsc_utils import normalize_site_url


# ---------- Helpers ----------

def _ok(agent, summary, findings=None, data=None):
    return {"agent": agent, "summary": summary,
            "findings": findings or [], "data": data or {}}


def _origin_of(site_url):
    """Convert a GSC site URL or sc-domain entry to a fetchable origin."""
    if site_url.startswith("sc-domain:"):
        return "https://" + site_url[len("sc-domain:"):].rstrip("/")
    return site_url.rstrip("/")


def _probe_homepage(origin):
    """Light HTTP probe for framework / platform hints, mirroring
    ga4_context. Best-effort; never raises."""
    req = urllib.request.Request(origin, headers={
        "User-Agent": "google-search-console-agent/0.1 (+context-probe)",
        "Accept": "*/*",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read(400_000).decode("utf-8", errors="replace")
            status = resp.status
            server = resp.headers.get("server")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        return {"status": -1, "error": str(e)}

    title = None
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    if m:
        title = m.group(1).strip()[:200]

    framework = None
    for label, patterns in (
        ("nextjs",   [r'id="__next"', r"/_next/"]),
        ("nuxt",     [r'id="__nuxt"', r"/_nuxt/"]),
        ("react",    [r'id="root"',   r"react-dom"]),
        ("vue",      [r'id="app"',    r"vue\.runtime"]),
        ("angular",  [r"ng-version="]),
        ("astro",    [r"astro-island"]),
        ("svelte",   [r"sveltekit"]),
    ):
        if any(re.search(p, body, re.I) for p in patterns):
            framework = label
            break

    platform = None
    for label, patterns in (
        ("shopify",       [r"cdn\.shopify\.com", r"window\.Shopify"]),
        ("woocommerce",   [r"wp-content/plugins/woocommerce"]),
        ("magento",       [r"Magento_", r"mage/cookies"]),
        ("wordpress",     [r"wp-content/", r"wp-includes/"]),
        ("webflow",       [r"webflow\.com", r"data-wf-"]),
        ("wix",           [r"static\.wixstatic\.com"]),
        ("squarespace",   [r"static1\.squarespace\.com"]),
    ):
        if any(re.search(p, body, re.I) for p in patterns):
            platform = label
            break

    return {"status": status, "title": title, "server": server,
            "framework": framework, "platform": platform}


# ---------- Agents ----------

def run_overview(site_url):
    """Site overview: permission level, sitemap inventory, homepage probe."""
    site_url_norm = normalize_site_url(site_url)
    overview: dict[str, Any] = {"site_url": site_url_norm}
    findings = []

    try:
        sites = gsc_admin.list_sites()
        match = next((s for s in sites if s.get("site_url") == site_url_norm), None)
        if match:
            overview["permission_level"] = match.get("permission_level")
        else:
            findings.append({
                "severity": "Critical",
                "title": "Property not found in Search Console",
                "detail": f"`{site_url_norm}` does not appear in your accessible properties. Verify ownership or scope.",
            })
    except Exception as e:
        findings.append({"severity": "High", "title": "sites.list failed", "detail": str(e)})

    try:
        sitemaps = gsc_admin.list_sitemaps(site_url_norm)
        overview["sitemap_count"] = len(sitemaps)
        if sitemaps:
            recent = max(sitemaps, key=lambda s: s.get("lastSubmitted") or "")
            overview["last_sitemap_submitted"] = recent.get("lastSubmitted")
            for sm in sitemaps:
                errors = sm.get("errors") or 0
                warnings = sm.get("warnings") or 0
                if errors:
                    findings.append({
                        "severity": "High",
                        "title": f"Sitemap `{sm.get('path')}` reports {errors} errors",
                        "detail": "Open the sitemap in Search Console -> Sitemaps to see the failed URLs.",
                    })
                elif warnings:
                    findings.append({
                        "severity": "Medium",
                        "title": f"Sitemap `{sm.get('path')}` reports {warnings} warnings",
                        "detail": "Warnings are often duplicate URLs or non-indexable entries. Worth a review.",
                    })
            overview["sitemaps_raw"] = sitemaps
        else:
            findings.append({
                "severity": "High",
                "title": "No sitemaps registered",
                "detail": "Submit at least one sitemap so Google can discover URLs efficiently.",
            })
    except Exception as e:
        findings.append({"severity": "Medium", "title": "sitemaps.list failed", "detail": str(e)})

    origin = _origin_of(site_url_norm)
    overview["origin"] = origin
    overview["homepage"] = _probe_homepage(origin)

    return _ok("gsc-overview", f"site overview for {site_url_norm}", findings, overview), overview


def run_search_analytics(site_url, days=28):
    findings = []
    data: dict[str, Any] = {}
    site_url = normalize_site_url(site_url)

    try:
        data["top_queries"] = gsc_data.top_queries(site_url, days=days, row_limit=50)
    except Exception as e:
        findings.append({"severity": "High", "title": "top queries fetch failed", "detail": str(e)})

    try:
        data["top_pages"] = gsc_data.top_pages(site_url, days=days, row_limit=50)
    except Exception as e:
        findings.append({"severity": "High", "title": "top pages fetch failed", "detail": str(e)})

    try:
        data["by_device"] = gsc_data.by_device(site_url, days=days)
        device_rows = data["by_device"]["rows"]
        total_clicks = sum(r.get("clicks", 0) for r in device_rows)
        if total_clicks:
            mobile = next((r for r in device_rows if r.get("device") == "MOBILE"), None)
            mobile_share = (mobile.get("clicks", 0) / total_clicks) if mobile else 0
            data["mobile_click_share"] = round(mobile_share, 4)
    except Exception as e:
        findings.append({"severity": "Medium", "title": "device breakdown failed", "detail": str(e)})

    try:
        data["by_country"] = gsc_data.by_country(site_url, days=days, row_limit=15)
    except Exception as e:
        findings.append({"severity": "Low", "title": "country breakdown failed", "detail": str(e)})

    try:
        data["time_series"] = gsc_data.time_series(site_url, days=max(days, 90))
        ts_rows = data["time_series"]["rows"]
        if len(ts_rows) >= 14:
            mid = len(ts_rows) // 2
            recent = sum(r.get("clicks", 0) for r in ts_rows[mid:])
            previous = sum(r.get("clicks", 0) for r in ts_rows[:mid])
            if previous:
                change_pct = (recent - previous) / previous * 100
                data["click_trend_change_pct"] = round(change_pct, 1)
                if change_pct <= -20:
                    findings.append({
                        "severity": "High",
                        "title": "Organic clicks down >20% in the second half of the window",
                        "detail": f"First half: {previous:,} clicks; second half: {recent:,} clicks ({change_pct:+.1f}%).",
                    })
    except Exception as e:
        findings.append({"severity": "Low", "title": "time series failed", "detail": str(e)})

    rows = ((data.get("top_queries") or {}).get("rows")) or []
    summary = f"{len(rows)} top queries scanned"
    return _ok("gsc-search-analytics", summary, findings, data)


def run_ctr_curve(site_url, days=28, max_queries=30):
    """Compare per-query observed CTR to the position-CTR curve. Highlights
    underperforming queries (good ranks, weak clickthrough) — usually a
    title-tag / meta-description issue."""
    site_url = normalize_site_url(site_url)
    findings: list[dict[str, Any]] = []
    data: dict[str, Any] = {}

    try:
        result = gsc_data.top_queries(site_url, days=days, row_limit=max_queries)
    except Exception as e:
        return _ok("gsc-ctr-curve", "ctr scan failed", [
            {"severity": "Medium", "title": "top queries fetch failed", "detail": str(e)},
        ])

    below_curve = []
    above_curve = []
    for row in result.get("rows", []):
        pos = row.get("position")
        ctr = row.get("ctr")
        impressions = row.get("impressions", 0)
        if pos is None or ctr is None:
            continue
        verdict = gsc_benchmarks.compare_ctr(ctr, pos, impressions=impressions)
        v = verdict.get("verdict")
        if v in ("below_curve", "below_curve_critical"):
            below_curve.append({**row, "verdict": verdict})
        elif v == "above_curve":
            above_curve.append({**row, "verdict": verdict})

    data["below_curve_count"] = len(below_curve)
    data["above_curve_count"] = len(above_curve)
    data["below_curve_top"] = below_curve[:10]
    data["above_curve_top"] = above_curve[:10]

    for q in below_curve[:5]:
        v = q["verdict"]
        sev = "High" if v["verdict"] == "below_curve_critical" else "Medium"
        findings.append({
            "severity": sev,
            "title": f"Query `{q.get('query')}` clicks-through below expected curve",
            "detail": (
                f"Position {q.get('position'):.1f}, observed CTR {v['observed_ctr']:.2%}, "
                f"expected ~{v['expected_ctr']:.2%} (impressions: {q.get('impressions'):,}). "
                "Usually a title / meta-description fix."
            ),
        })

    return _ok(
        "gsc-ctr-curve",
        f"{len(below_curve)} queries below CTR curve, {len(above_curve)} above",
        findings, data,
    )


def run_cwv(site_url, form_factor="ALL_FORM_FACTORS", with_history=False):
    """Origin-level CWV via CrUX. Per-URL deep-dives are out of scope for
    the audit driver — call gsc_psi.py directly for that."""
    origin = _origin_of(normalize_site_url(site_url))
    findings: list[dict[str, Any]] = []
    data: dict[str, Any] = {"origin": origin}

    try:
        snapshot = gsc_crux.query_record(origin=origin, form_factor=form_factor)
        data["snapshot"] = snapshot
    except Exception as e:
        return _ok("gsc-core-web-vitals", f"CrUX query failed: {e}", [
            {"severity": "Medium", "title": "CrUX origin record failed", "detail": str(e)},
        ], data)

    if snapshot.get("status") == "no_data":
        return _ok("gsc-core-web-vitals",
                   "CrUX has no aggregated data for this origin",
                   [{"severity": "Low",
                     "title": "Insufficient CrUX traffic at the origin level",
                     "detail": "Origin-level CWV requires a meaningful volume of Chrome traffic. The site is either too small or too new."}],
                   data)

    for metric in ("lcp_p75_ms", "inp_p75_ms", "cls_p75", "fcp_p75_ms", "ttfb_p75_ms"):
        value = snapshot.get(metric)
        if value is None:
            continue
        verdict = gsc_benchmarks.compare_cwv(metric, value)
        if verdict["verdict"] == "poor":
            sev = "High"
        elif verdict["verdict"] == "needs_improvement":
            sev = "Medium"
        else:
            continue
        findings.append({
            "severity": sev,
            "title": f"{metric} above the {verdict['verdict'].replace('_', ' ')} threshold",
            "detail": (
                f"Observed p75 {value} (good ≤ {verdict['good_threshold']}, "
                f"needs improvement ≤ {verdict['needs_improvement_threshold']})."
            ),
            "metric": metric,
            "metric_value": value,
        })

    if with_history:
        try:
            data["history"] = gsc_crux.query_history(origin=origin, form_factor=form_factor)
        except Exception as e:
            findings.append({"severity": "Low", "title": "CrUX history failed", "detail": str(e)})

    snapshot_metrics = ", ".join(
        f"{k}={snapshot.get(k)}" for k in ("lcp_p75_ms", "inp_p75_ms", "cls_p75") if snapshot.get(k) is not None
    )
    return _ok("gsc-core-web-vitals", f"CrUX {form_factor}: {snapshot_metrics}", findings, data)


def run_url_inspect_stub():
    return _ok(
        "gsc-url-inspect",
        "stub — run `/gsc inspect <site> <url>` (or the Claude Code skill) for per-URL deep-dives",
        [],
        {"hint": "URL inspection is quota-heavy and one URL at a time; the audit driver omits it"},
    )


def run_structured_data(site_url, sample_size=20):
    """Sample N URLs from the sitemap and validate JSON-LD blocks against
    Google's required-field expectations per schema type."""
    site_url = normalize_site_url(site_url)
    findings: list[dict[str, Any]] = []
    try:
        out = gsc_structured_data.analyze_sitemap_sample(site_url, sample_size=sample_size)
    except Exception as e:
        return _ok("gsc-structured-data", f"structured-data scan failed: {e}", [
            {"severity": "Low", "title": "Structured-data analyzer error", "detail": str(e)},
        ])

    if out.get("error"):
        return _ok("gsc-structured-data", f"could not sample sitemap: {out['error']}", [
            {"severity": "Low",
             "title": "No sitemap URLs available for structured-data sampling",
             "detail": "Skipping. Submit a sitemap or pass a URL via /gsc structured-data --url ..."}
        ], out)

    rollup = out.get("rollup") or {}
    verdicts = rollup.get("block_verdicts") or {}
    has_jsonld = rollup.get("urls_with_jsonld", 0)
    analyzed = rollup.get("urls_analyzed", 0)
    coverage_pct = round((has_jsonld / analyzed) * 100, 1) if analyzed else 0

    if analyzed and has_jsonld == 0:
        findings.append({
            "severity": "Medium",
            "title": "No JSON-LD found on any sampled URL",
            "detail": (
                f"Sampled {analyzed} URLs from the sitemap; none carry "
                "JSON-LD structured data. Rich-results eligibility is lost. "
                "Add Schema.org markup for the relevant page types (Product, "
                "Article, FAQPage, BreadcrumbList, Organization)."
            ),
        })
    elif verdicts.get("fail", 0):
        findings.append({
            "severity": "High",
            "title": f"{verdicts['fail']} JSON-LD block(s) missing required fields",
            "detail": (
                f"Top missing fields across the sample: "
                f"{rollup.get('top_missing_required') or {}}. "
                "Fix these to restore rich-results eligibility."
            ),
        })
    elif verdicts.get("partial", 0):
        findings.append({
            "severity": "Medium",
            "title": f"{verdicts['partial']} JSON-LD block(s) missing recommended fields",
            "detail": (
                "Schemas validate but lack recommended fields that improve "
                "rich-results eligibility (e.g. Product.aggregateRating, "
                "Article.dateModified)."
            ),
        })

    summary = (
        f"{analyzed} URLs sampled, JSON-LD coverage {coverage_pct}%, "
        f"verdicts {verdicts}"
    )
    return _ok("gsc-structured-data", summary, findings, out)


def run_backlinks(site_url, competitors=None):
    """Domain rank for the property plus optional competitor comparison."""
    site_url = normalize_site_url(site_url)
    bare_domain = site_url.split("sc-domain:")[-1] if site_url.startswith("sc-domain:") \
        else site_url
    findings: list[dict[str, Any]] = []

    domains = [bare_domain] + (competitors or [])
    out = gsc_backlinks.compare_domains(domains) if competitors else \
        {"rows": [_single_row(bare_domain)], "primary": bare_domain}

    primary_row = next((r for r in out.get("rows") or [] if r["domain"].endswith(bare_domain)), None)
    if not primary_row:
        return _ok("gsc-backlinks", "could not look up domain rank", [], out)

    band = primary_row.get("tranco_band")
    opr_dec = primary_row.get("open_pagerank_decimal")
    if opr_dec is not None and opr_dec < 2.0:
        findings.append({
            "severity": "Medium",
            "title": f"Open PageRank {opr_dec:.1f} suggests low backlink authority",
            "detail": (
                "Open PageRank below 2 / 10. Competitor outreach, digital PR, "
                "and editorial link-building have outsized ROI from this baseline."
            ),
        })

    if competitors:
        ranked = [r for r in out["rows"] if r.get("tranco_rank") is not None]
        ranked.sort(key=lambda r: r["tranco_rank"])
        position = next((i for i, r in enumerate(ranked, 1)
                          if r["domain"].endswith(bare_domain)), None)
        if position and position > 1 and len(ranked) > 1:
            findings.append({
                "severity": "Medium",
                "title": f"Site ranks #{position} of {len(ranked)} in the competitor set (Tranco)",
                "detail": (
                    "Tranco rank is a composite popularity signal, not pure authority. "
                    "Combined with Open PageRank it sketches the gap that needs closing."
                ),
            })

    summary = f"primary domain {bare_domain}: Tranco {band}"
    if opr_dec is not None:
        summary += f", Open PageRank {opr_dec:.1f}"
    return _ok("gsc-backlinks", summary, findings, out)


def _single_row(domain):
    rank = gsc_backlinks.tranco_rank(domain)
    return {"domain": domain, "tranco_rank": rank,
            "tranco_band": gsc_backlinks._tranco_band(rank)}


def run_page_experience(site_url):
    """Local header probe + Mozilla Observatory + SSL Labs."""
    origin = _origin_of(normalize_site_url(site_url))
    host = origin.replace("https://", "").replace("http://", "").rstrip("/")
    findings: list[dict[str, Any]] = []

    report = gsc_page_experience.full_report(host)

    headers_report = report.get("headers") or {}
    if headers_report.get("error"):
        findings.append({
            "severity": "Medium",
            "title": "Could not probe security headers",
            "detail": headers_report.get("message") or headers_report.get("error"),
        })
    elif headers_report.get("grade") == "poor":
        findings.append({
            "severity": "High",
            "title": f"Security-header coverage {headers_report.get('coverage_pct')}% (poor)",
            "detail": "Missing: " + ", ".join(headers_report.get("headers_missing", [])),
        })
    elif headers_report.get("grade") == "needs_improvement":
        findings.append({
            "severity": "Medium",
            "title": f"Security-header coverage {headers_report.get('coverage_pct')}% (needs improvement)",
            "detail": "Missing: " + ", ".join(headers_report.get("headers_missing", [])),
        })

    obs = report.get("observatory") or {}
    if obs.get("grade") and obs.get("grade") in ("D", "E", "F"):
        findings.append({
            "severity": "High",
            "title": f"Mozilla Observatory grade {obs['grade']}",
            "detail": (
                f"Score {obs.get('score')}; tests passed "
                f"{obs.get('tests_passed')} / {obs.get('tests_quantity')}. "
                "See https://developer.mozilla.org/en-US/observatory for the rule list."
            ),
        })
    elif obs.get("grade") in ("B", "C"):
        findings.append({
            "severity": "Medium",
            "title": f"Mozilla Observatory grade {obs['grade']}",
            "detail": f"Score {obs.get('score')}. Headroom for CSP / Referrer-Policy hardening.",
        })

    ssl = report.get("ssl_labs") or {}
    if ssl.get("grade") in ("B", "C", "D", "E", "F", "T", "M"):
        findings.append({
            "severity": "High" if ssl.get("grade") in ("D", "E", "F", "T", "M") else "Medium",
            "title": f"SSL Labs grade {ssl['grade']}",
            "detail": (
                "TLS configuration falls short of A. Check supported protocol "
                "versions (TLS 1.0 / 1.1 should be disabled), cipher suites, "
                "and certificate-chain completeness."
            ),
        })

    summary_bits = []
    if headers_report.get("grade"):
        summary_bits.append(f"headers {headers_report['grade']}")
    if obs.get("grade"):
        summary_bits.append(f"observatory {obs['grade']}")
    if ssl.get("grade"):
        summary_bits.append(f"ssl-labs {ssl['grade']}")
    summary = "; ".join(summary_bits) or "page-experience scan complete"

    return _ok("gsc-page-experience", summary, findings, report)


# ---------- Orchestrator ----------

def orchestrate(site_url, days=28, form_factor="ALL_FORM_FACTORS",
                with_history=False, max_queries=30,
                with_backlinks=False, competitors=None,
                with_page_experience=False, structured_data_sample=20):
    site_url_norm = normalize_site_url(site_url)
    overview_agent, overview_data = run_overview(site_url_norm)

    agents_output: list[dict[str, Any]] = [overview_agent]

    # The default audit fans out the cheap / always-on agents.
    # Backlinks and page-experience are opt-in (external network polling).
    futures = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures["search"] = ex.submit(run_search_analytics, site_url_norm, days)
        futures["ctr"] = ex.submit(run_ctr_curve, site_url_norm, days, max_queries)
        futures["cwv"] = ex.submit(run_cwv, site_url_norm, form_factor, with_history)
        futures["structured"] = ex.submit(run_structured_data, site_url_norm,
                                           structured_data_sample)
        if with_backlinks:
            futures["backlinks"] = ex.submit(run_backlinks, site_url_norm,
                                              competitors=competitors)
        if with_page_experience:
            futures["page_exp"] = ex.submit(run_page_experience, site_url_norm)
        futures["url_stub"] = ex.submit(run_url_inspect_stub)

        # Collect in a stable order so the report sections are predictable.
        ordered = ["search", "ctr", "cwv", "structured", "backlinks",
                    "page_exp", "url_stub"]
        for key in ordered:
            if key in futures:
                agents_output.append(futures[key].result())

    confidence = "medium"
    sa = next((a for a in agents_output if a["agent"] == "gsc-search-analytics"), None)
    if sa and any(f.get("severity") == "High" for f in sa.get("findings", [])):
        confidence = "low"

    return agents_output, overview_data, confidence


# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(description="Full GSC audit, one command, any runtime")
    parser.add_argument("--site", required=True, help="GSC property (domain or URL prefix)")
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--form-factor", default="ALL_FORM_FACTORS",
                        choices=("PHONE", "DESKTOP", "TABLET", "ALL_FORM_FACTORS"))
    parser.add_argument("--with-history", action="store_true",
                        help="Include CrUX 25-week history")
    parser.add_argument("--with-backlinks", action="store_true",
                        help="Run the domain-authority agent (Open PageRank + Tranco)")
    parser.add_argument("--competitors", help="Comma-separated competitor domains for --with-backlinks")
    parser.add_argument("--with-page-experience", action="store_true",
                        help="Run Mozilla Observatory + SSL Labs + local header probe")
    parser.add_argument("--structured-data-sample", type=int, default=20,
                        help="URLs to sample from the sitemap for structured-data validation")
    parser.add_argument("--max-queries", type=int, default=30,
                        help="Number of top queries scanned for the CTR-curve check")
    parser.add_argument("--format", choices=("md", "html", "pdf", "json"), default="md")
    parser.add_argument("--output", help="Write report to this path instead of stdout")
    args = parser.parse_args()

    try:
        gsc_auth.get_credentials(write=False)
    except gsc_auth.AuthRequiredError as e:
        print(json.dumps({"error": "no_credentials", "hint": e.hint}), file=sys.stderr)
        return 2

    competitors = None
    if args.competitors:
        competitors = [c.strip() for c in args.competitors.split(",") if c.strip()]

    try:
        agents_output, overview, confidence = orchestrate(
            site_url=args.site, days=args.days, form_factor=args.form_factor,
            with_history=args.with_history, max_queries=args.max_queries,
            with_backlinks=args.with_backlinks, competitors=competitors,
            with_page_experience=args.with_page_experience,
            structured_data_sample=args.structured_data_sample,
        )
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}), file=sys.stderr)
        return 1

    site_url_norm = normalize_site_url(args.site)
    body: str | bytes
    if args.format == "json":
        body = json.dumps({
            "site_url": site_url_norm,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "confidence": confidence,
            "overview": overview,
            "agents": agents_output,
        }, indent=2, default=str)
    elif args.format == "md":
        body = gsc_report.render_markdown(site_url_norm, agents_output,
                                          confidence=confidence, overview=overview)
    elif args.format == "html":
        body = gsc_report.render_html(site_url_norm, agents_output, confidence=confidence)
    else:
        html = gsc_report.render_html(site_url_norm, agents_output, confidence=confidence)
        body = gsc_report.render_pdf_bytes(html)

    if args.output:
        path = Path(args.output)
        if isinstance(body, bytes):
            path.write_bytes(body)
        else:
            path.write_text(body, encoding="utf-8")
        print(json.dumps({"status": "ok", "output": str(path), "format": args.format,
                          "confidence": confidence}))
    else:
        if isinstance(body, bytes):
            sys.stdout.buffer.write(body)
        else:
            print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
