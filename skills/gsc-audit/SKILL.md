---
name: gsc-audit
description: "Full GSC audit. Profiles the property, pulls search analytics, runs the CTR-vs-position curve check, fetches Core Web Vitals via CrUX, checks sitemap health, and renders a benchmarked markdown report. Use when user says 'audit', 'full SEO check', 'analyze my Search Console'."
user-invokable: true
argument-hint: "<site> [--days N] [--form-factor PHONE|DESKTOP|ALL_FORM_FACTORS] [--with-history] [--format md|html|pdf] [--output PATH]"
license: MIT
metadata:
  author: arcbaslow
  version: "0.1.0"
  category: gsc
---

# Full GSC Audit

## Process

1. **Verify auth**: `python scripts/gsc_auth.py --check`
2. **Pick a property**: if user does not supply one, `python scripts/gsc_auth.py --sites` and ask.
3. **Run the one-command driver**:
   ```
   python scripts/gsc_audit.py --site <site> --format md --output gsc-audit-<site>-<YYYYMMDD>.md
   ```
   The driver orchestrates context profiling → search-analytics →
   CTR-curve → sitemap health → Core Web Vitals (CrUX) in parallel,
   then renders the markdown report with benchmark verdicts inline.
4. **Read the report** and present the executive summary + top findings.

## What the audit covers

- **Site overview**: permission level, registered sitemap count + last submission, homepage HTTP probe (framework / platform hints)
- **Search analytics**: top 50 queries, top 50 pages, device + country splits, 90-day time-series with a recent-vs-prior-half clicks delta
- **CTR-vs-position curve**: queries with weak CTR for their average rank (usually a title / meta-description fix)
- **Sitemap health**: error and warning counts per registered sitemap
- **Core Web Vitals**: CrUX origin snapshot for LCP / INP / CLS / FCP / TTFB classified against Google's official good / needs-improvement / poor bands; optional 25-week history
- **URL inspection**: stubbed in the audit driver because it is quota-heavy. Run `/gsc inspect <site> <url>` for a deep dive.

## Default Parameters

- Date range: 28 days (`--days N` to override)
- Form factor: `ALL_FORM_FACTORS` (`--form-factor PHONE` or `--form-factor DESKTOP` to split)
- Format: markdown (`--format html` / `--format pdf` for the other renderings)
- Output: `./gsc-audit-<site>-<YYYYMMDD>.md` unless `--output` is supplied

## Output: markdown by default

Plain markdown, no emoji. Sections:

1. **Header** — site, generation timestamp, confidence label
2. **Site Context** — permission level, sitemap inventory, homepage probe, inferred framework / platform
3. **Executive Summary** — one bullet per agent
4. **Action Plan** — findings grouped by severity (Critical / High / Medium / Low). Each finding shows source agent and any CWV benchmark verdict, e.g.

   > **lcp_p75_ms above the poor threshold** _(source: gsc-core-web-vitals)_ (value 4350, good ≤ 2500, needs improvement ≤ 4000, verdict poor)

5. **Per-Agent Output** — each agent's summary + raw JSON in a collapsed `<details>` block

## Confidence Inheritance

The driver does not have a single sampling number to anchor confidence
on the way GA4 does, so by default it reports `medium`. The signal it
uses to drop to `low`: if any High-severity finding came from the
search-analytics agent (typically meaning the request itself failed),
confidence drops.

## Error Handling

| Scenario | Action |
|----------|--------|
| Auth fails | Report and surface the gcloud command via `gsc_auth.py --adc` |
| Property not in user's GSC list | Hard-fail with a clear message; ask for the right property |
| CrUX returns no_data | Note "insufficient Chrome traffic at this origin" — common for small or new sites |
| Sitemap fetch fails | Continue; flag the missing inventory as Medium |
| 4xx on the homepage probe | Continue; framework / platform fields stay null |
