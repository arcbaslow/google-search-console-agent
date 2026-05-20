"""
GSC audit report renderer. Plain markdown by default (no emoji). HTML and
PDF available via the same renderer pipeline as the analytics agent.

Agent output schema (matches the analytics agent):

  {"agent": "...", "summary": "...",
   "findings": [{"severity": "...", "title": "...", "detail": "...",
                  "metric": "...", "metric_value": ...}],
   "data": {...}}
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def _md_escape(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def _format_cwv_benchmark_md(b):
    if not b or "error" in b:
        return ""
    return (
        f" (value {b.get('value')}, good ≤ {b.get('good_threshold')}, "
        f"needs improvement ≤ {b.get('needs_improvement_threshold')}, "
        f"verdict {b.get('verdict')})"
    )


def render_property_context_md(site_url, overview):
    """The 'site overview' equivalent of the analytics agent's property
    context section. Pulled from gsc_admin.list_sites + sitemaps."""
    lines = ["## Site Context", ""]
    if site_url:
        lines.append(f"- Search Console property: `{site_url}`")
    if overview:
        permission = overview.get("permission_level")
        if permission:
            lines.append(f"- Permission level: {permission}")
        sitemap_count = overview.get("sitemap_count")
        if sitemap_count is not None:
            lines.append(f"- Sitemaps registered: {sitemap_count}")
        last_submitted = overview.get("last_sitemap_submitted")
        if last_submitted:
            lines.append(f"- Most recent sitemap submission: {last_submitted}")
        index_state = overview.get("indexing_summary")
        if index_state:
            lines.append(f"- Indexing snapshot: {index_state}")
        homepage = overview.get("homepage") or {}
        if homepage:
            if homepage.get("title"):
                lines.append(f"- Homepage title: {homepage['title']}")
            if homepage.get("status"):
                lines.append(f"- Homepage HTTP status: {homepage['status']}")
            if homepage.get("framework"):
                lines.append(f"- Inferred framework: {homepage['framework']}")
            if homepage.get("platform"):
                lines.append(f"- Inferred platform: {homepage['platform']}")
    return "\n".join(lines) + "\n"


def render_markdown(site_url, agents_output, confidence="medium", overview=None):
    """Build a markdown audit report. Plain markdown, no emoji."""
    all_findings = []
    summaries = []
    for ao in agents_output:
        agent_name = ao.get("agent", "unknown")
        for f in ao.get("findings", []):
            ff = dict(f)
            ff["source"] = agent_name
            all_findings.append(ff)
        if ao.get("summary"):
            summaries.append((agent_name, ao["summary"]))

    try:
        from gsc_benchmarks import enrich_findings
        all_findings = enrich_findings(all_findings)
    except Exception:
        pass

    sorted_findings = sorted(all_findings, key=lambda f: SEVERITY_ORDER.get(f.get("severity", "Low"), 4))

    lines = []
    lines.append(f"# GSC Audit — {site_url}")
    lines.append("")
    lines.append(f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}_  ")
    lines.append(f"_Data confidence: **{confidence}**_  ")
    lines.append("")

    lines.append(render_property_context_md(site_url, overview))

    lines.append("## Executive Summary")
    lines.append("")
    if summaries:
        for agent_name, summary in summaries:
            lines.append(f"- **{agent_name}**: {summary}")
    else:
        lines.append("_No agent summaries provided._")
    lines.append("")

    lines.append("## Action Plan")
    lines.append("")
    for sev in ("Critical", "High", "Medium", "Low"):
        items = [f for f in sorted_findings if f.get("severity") == sev]
        if not items:
            continue
        lines.append(f"### {sev}")
        lines.append("")
        for f in items:
            title = f.get("title", "(untitled)")
            detail = f.get("detail", "")
            source = f.get("source", "")
            bench = _format_cwv_benchmark_md(f.get("benchmark"))
            lines.append(f"- **{title}** _(source: {source})_{bench}")
            if detail:
                lines.append(f"  - {detail}")
        lines.append("")

    if not sorted_findings:
        lines.append("_No findings._")
        lines.append("")

    lines.append("## Per-Agent Output")
    lines.append("")
    for ao in agents_output:
        name = ao.get("agent", "unknown")
        summary = ao.get("summary", "")
        data = ao.get("data")
        lines.append(f"### {name}")
        lines.append("")
        if summary:
            lines.append(summary)
            lines.append("")
        if data is not None:
            lines.append("<details>")
            lines.append("<summary>raw output</summary>")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(data, indent=2, default=str))
            lines.append("```")
            lines.append("")
            lines.append("</details>")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_Generated by google-search-console-agent._")
    lines.append("")
    return "\n".join(lines)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>GSC Audit - __SITE__</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&display=swap');
  html, body { background: #F5F4EF; color: #252525; font-family: 'Manrope', -apple-system, sans-serif; margin: 0; padding: 0; }
  .wrap { max-width: 880px; margin: 0 auto; padding: 56px 32px 80px; }
  h1 { font-weight: 700; font-size: 32px; margin: 0 0 8px; letter-spacing: -0.02em; }
  h2 { font-weight: 600; font-size: 22px; margin: 48px 0 12px; letter-spacing: -0.01em; }
  h3 { font-weight: 600; font-size: 16px; margin: 24px 0 8px; }
  .meta { color: #6b6b6b; font-size: 14px; margin-bottom: 32px; }
  .conf { display: inline-block; padding: 4px 10px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; border: 1px solid #252525; }
  .conf.high { background: #d6f0d6; }
  .conf.medium { background: #fff3cc; }
  .conf.low { background: #ffe0cc; }
  .findings { list-style: none; padding: 0; margin: 0; }
  .findings li { border-left: 4px solid #252525; padding: 12px 16px; margin: 8px 0; background: #ffffff; }
  .findings li.crit { border-left-color: #c0392b; }
  .findings li.high { border-left-color: #d68910; }
  .findings li.med { border-left-color: #2874a6; }
  .findings li.low { border-left-color: #7d7d7d; }
  .sev { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-right: 8px; }
  pre { background: #ffffff; border: 1px solid #e5e2d8; padding: 12px; overflow-x: auto; font-size: 12px; }
  .footer { margin-top: 64px; padding-top: 16px; border-top: 1px solid #d8d4c8; color: #6b6b6b; font-size: 12px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>GSC Audit</h1>
  <div class="meta">__SITE__ - generated __GENERATED_AT__<br />Confidence: <span class="conf __CONFIDENCE__">__CONFIDENCE__</span></div>
  <h2>Findings</h2>
  <ul class="findings">__FINDINGS__</ul>
  <div class="footer">google-search-console-agent - __GENERATED_AT__</div>
</div>
</body>
</html>"""


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_html(site_url, agents_output, confidence="medium"):
    findings = []
    for ao in agents_output:
        agent = ao.get("agent", "")
        for f in ao.get("findings", []):
            findings.append({**f, "source": agent})
    findings.sort(key=lambda f: SEVERITY_ORDER.get(f.get("severity", "Low"), 4))
    items = []
    for f in findings:
        sev = f.get("severity", "Low")
        cls = {"Critical": "crit", "High": "high", "Medium": "med", "Low": "low"}.get(sev, "low")
        items.append(
            f'<li class="{cls}"><span class="sev">{sev}</span><strong>{_esc(f.get("title", ""))}</strong>'
            f'<div style="margin-top:6px;font-size:14px;color:#404040;">{_esc(f.get("detail", ""))}</div></li>'
        )
    return (HTML_TEMPLATE
            .replace("__SITE__", _esc(site_url))
            .replace("__GENERATED_AT__", datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__CONFIDENCE__", _esc(confidence))
            .replace("__FINDINGS__", "".join(items) or "<li><em>No findings.</em></li>"))


def render_pdf(html, output_path):
    from weasyprint import HTML
    HTML(string=html).write_pdf(output_path)


def render_pdf_bytes(html) -> bytes:
    from weasyprint import HTML
    return HTML(string=html).write_pdf()


def main():
    parser = argparse.ArgumentParser(description="GSC audit report generator")
    parser.add_argument("--site", required=True)
    parser.add_argument("--inputs", required=True, help="Comma-separated paths to agent JSON outputs")
    parser.add_argument("--format", choices=["md", "html", "pdf"], default="md")
    parser.add_argument("--output", required=True)
    parser.add_argument("--confidence", default="medium")
    args = parser.parse_args()

    inputs = []
    for p in args.inputs.split(","):
        p = p.strip()
        if not p:
            continue
        with open(p) as f:
            inputs.append(json.load(f))

    out_path = Path(args.output)
    if args.format == "md":
        out_path.write_text(render_markdown(args.site, inputs, confidence=args.confidence),
                            encoding="utf-8")
    elif args.format == "html":
        out_path.write_text(render_html(args.site, inputs, confidence=args.confidence),
                            encoding="utf-8")
    else:
        html = render_html(args.site, inputs, confidence=args.confidence)
        render_pdf(html, str(out_path))

    print(json.dumps({"status": "ok", "output": str(out_path), "format": args.format}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
