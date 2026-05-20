---
name: gsc
description: "Multi-agent toolkit for Google Search Console. Read side: search analytics (queries / pages / devices / countries / time-series), CTR-vs-position curve checks, sitemap inventory and error counts, URL inspection (indexing state, last crawl, mobile usability, rich results), origin-level Core Web Vitals via CrUX, per-URL PageSpeed Insights / Lighthouse. Write side: submit and delete sitemaps. Triggers on: gsc, search console, organic search, ctr, indexing, sitemap, core web vitals, lcp, inp, cls, lighthouse, pagespeed."
user-invokable: true
argument-hint: "[command] [site-or-url] [options]"
license: MIT
metadata:
  author: arcbaslow
  version: "0.1.0"
  category: gsc
---

# GSC: Multi-Agent Toolkit

**Invocation:** `/gsc $1 $2` where `$1` is the command and `$2` is the
Search Console property (a domain like `example.com`, a domain
property like `sc-domain:example.com`, or a URL prefix like
`https://example.com/`).

**Scripts:** Located at the plugin root `scripts/` directory.

A toolkit for everything you would normally pull from Search Console
plus the two adjacent APIs (PageSpeed Insights and Chrome UX Report).
All data flows through Google's own ADC auth — no user-registered
OAuth client and no service account required.

## Quick Reference

Read commands:

| Command | What it does |
|---------|-------------|
| `/gsc audit <site>` | Full audit with parallel agent delegation, benchmarks, markdown output by default |
| `/gsc queries <site>` | Top queries by clicks/impressions/CTR/position |
| `/gsc pages <site>` | Top landing pages |
| `/gsc devices <site>` | Mobile / desktop / tablet split |
| `/gsc countries <site>` | Country breakdown |
| `/gsc trends <site>` | Time-series over the last 90 days |
| `/gsc ctr <site>` | CTR-vs-position curve check for top queries |
| `/gsc inspect <site> <url>` | URL Inspection (indexing state, last crawl, rich results) |
| `/gsc cwv <site>` | Core Web Vitals via CrUX (origin-level) |
| `/gsc pagespeed <url>` | PageSpeed Insights (per-URL Lighthouse) |
| `/gsc sitemaps <site>` | List sitemaps and their error / warning counts |
| `/gsc benchmarks` | Inspect bundled CWV thresholds and the CTR-by-position curve |

Write commands (need the `webmasters` scope, not `.readonly`):

| Command | What it does |
|---------|-------------|
| `/gsc submit-sitemap <site> <feedpath>` | Submit a sitemap |
| `/gsc delete-sitemap <site> <feedpath>` | Delete a sitemap |
| `/gsc add-site <site>` | Add a property |
| `/gsc delete-site <site>` | Remove a property |

Auth:

| Command | What it does |
|---------|-------------|
| `/gsc auth` | Print the gcloud command to authenticate (or run OAuth fallback) |
| `/gsc sites` | List accessible Search Console properties |

## Command Routing

| Input | Route to |
|-------|----------|
| `audit <site>` | gsc-audit skill |
| `queries <site>` / `pages <site>` / `devices <site>` / `countries <site>` / `trends <site>` | gsc-search-analytics skill |
| `ctr <site>` | gsc-ctr-curve skill |
| `inspect <site> <url>` | gsc-url-inspect skill |
| `cwv <site>` | gsc-core-web-vitals skill |
| `pagespeed <url>` | gsc-pagespeed skill |
| `sitemaps <site>` / `submit-sitemap` / `delete-sitemap` | gsc-sitemaps skill |
| `benchmarks ...` | Run `python scripts/gsc_benchmarks.py` |
| `auth` | Run `python scripts/gsc_auth.py --adc` (or `--oauth` as fallback) |
| `sites` | Run `python scripts/gsc_auth.py --sites` |

## Natural Language Routing

- "Why am I losing traffic?" -> gsc-search-analytics (time-series + queries/pages)
- "Which queries should we improve titles on?" -> gsc-ctr-curve
- "Is this URL indexed?" -> gsc-url-inspect
- "How's our Core Web Vitals?" -> gsc-core-web-vitals
- "Audit this PDP for performance" -> gsc-pagespeed
- "Are my sitemaps healthy?" -> gsc-sitemaps
- "Full health check" -> gsc-audit
- "Compare against the industry" -> gsc-benchmarks (or part of gsc-audit)

## Authentication

Before any analysis command, verify auth:

```
python scripts/gsc_auth.py --check
```

If auth fails, prefer Google's own ADC path — install gcloud and run:

```
python scripts/gsc_auth.py --adc          # prints the gcloud command
python scripts/gsc_auth.py --adc --write  # same, but include webmasters write
```

Run the printed command, then `--check` again. For sitemap CRUD and
site CRUD the scope must include `webmasters` (without the .readonly
suffix).

Fallback (no gcloud available, e.g. CI):

```
python scripts/gsc_auth.py --oauth --client-secret-file <path>
```

Credentials sources, tried in order:
1. `GOOGLE_APPLICATION_CREDENTIALS` env var (service account / external account)
2. gcloud user ADC at `~/.config/gcloud/application_default_credentials.json`
3. Legacy OAuth at `~/.claude/gsc-credentials.json`

## Property formats

GSC accepts both domain properties and URL-prefix properties. The
scripts accept either form, plus a bare domain:

- `example.com`           → normalised to `sc-domain:example.com`
- `sc-domain:example.com` → used as-is (domain property)
- `https://example.com/`  → used as-is (URL-prefix property)

## Date ranges

GSC search analytics has a roughly 2-day reporting lag, so the helper
defaults to a window that ends three days back to ensure all dates in
the window are complete.

- Search analytics (queries, pages, devices, countries): 28 days default
- Time-series: 90 days default
- CrUX: aggregates the last 28 days (or weekly history up to 25 weeks)

Override the window via `--days N` on any command.

## Benchmarks

`scripts/gsc_benchmarks.py` exposes:

- Google's official Core Web Vitals thresholds (LCP, INP, CLS, FCP, TTFB)
- Average organic CTR by SERP position (positions 1-20)

Findings that include a `metric` / `metric_value` pair are auto-enriched
with verdicts by the markdown reporter — `good`, `needs_improvement`,
or `poor` for CWV; `on_curve`, `above_curve`, `below_curve`, or
`below_curve_critical` for CTR.

## Markdown output

Audit runs default to plain markdown (no emoji). The report includes
the site context (permission level, sitemap count, homepage probe),
the data-confidence label, benchmark verdicts inline with findings,
and a collapsed raw-JSON appendix per agent. Pass `--format html` or
`--format pdf` for the other renderings.

## After Analysis

After any analysis command, offer:

- "Want the full audit? Use `/gsc audit <site>`"
- "Want per-URL CWV instead of origin-level? Use `/gsc pagespeed <url>`"
