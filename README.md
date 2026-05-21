# google-search-console-agent

[![tests](https://github.com/arcbaslow/google-search-console-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/arcbaslow/google-search-console-agent/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![version](https://img.shields.io/badge/version-0.2.0-blue.svg)](CHANGELOG.md)

A multi-agent toolkit for Google Search Console. Talks to the GSC
Search Analytics, Sites, Sitemaps, and URL Inspection APIs, plus the
two adjacent APIs that the GSC UI itself relies on: Chrome UX Report
(field Core Web Vitals) and PageSpeed Insights (per-URL Lighthouse).

Designed to work with three runtimes side by side:

- **Claude Code** — full skill and subagent integration via `skills/` and `agents/`
- **OpenAI Codex** — driven by `AGENTS.md` and the universal Python CLI
- **Gemini CLI** — driven by `GEMINI.md` and the universal Python CLI

The Python adapters under `scripts/` are the source of truth and work
the same on all three. No user-registered OAuth client. No service
account. Auth is gcloud Application Default Credentials.

## What it does

- **Search analytics**: top queries, top pages, device and country
  splits, search-appearance breakdowns, 90-day time-series with a
  recent-vs-prior-half clicks delta.
- **CTR vs position curve**: per-query observed CTR compared to a
  bundled 2024 composite curve so you know which good-ranking queries
  are under-clicked (almost always a title / meta-description fix).
- **URL Inspection**: indexing state, last crawl, mobile usability,
  rich results, canonical resolution — one URL at a time, on demand.
- **Core Web Vitals**: origin-level snapshots and 25-week history via
  CrUX, classified against Google's official good / needs-improvement
  / poor thresholds.
- **PageSpeed Insights**: per-URL Lighthouse pass — performance, SEO,
  accessibility, best-practices, lab + field metrics, full audit blob.
- **Sitemaps**: list, get, submit, delete. With error / warning counts
  surfaced as audit findings.
- **Domain authority**: Tranco top-1M + Open PageRank for the property
  and any supplied competitors. No paid API.
- **Page experience**: Mozilla HTTP Observatory + SSL Labs + local
  security-headers probe. Grades HTTPS quality and header hygiene —
  both ranking signals that GSC's API does not expose.
- **Structured data**: sitemap-wide JSON-LD validation against Google's
  rich-results required-field rules. Local parser, no quota cost,
  complements URL Inspection.
- **Full audit**: one command that orchestrates context → search
  analytics → CTR curve → sitemap health → CWV → structured data in
  parallel and renders a benchmarked markdown report. Add
  `--with-backlinks` and `--with-page-experience` for the slower
  external-service checks.

## Requirements

- Python 3.10 or newer
- Google Cloud SDK (`gcloud`) for the default auth path, or a Cloud
  OAuth Desktop client for the fallback path
- Verified ownership of the Search Console property you want to audit
- WeasyPrint runtime libraries are only needed if you want PDF reports
  (markdown is the default and needs nothing extra):
  - Debian/Ubuntu: `apt install libpango-1.0-0 libpangoft2-1.0-0`
  - macOS: `brew install pango`
  - Windows: install the GTK 3 runtime — see WeasyPrint's
    [Windows installation notes](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows).

## Install

From inside the project directory.

### Recommended: `uv`

```
uv venv
uv pip install -r scripts/requirements.txt
uv run python scripts/gsc_auth.py --check
```

[`uv`](https://github.com/astral-sh/uv) is a single-binary Python installer
and runner. One install of `uv` replaces the venv + pip dance and is
faster on cold-start.

### Plain venv (works everywhere)

```
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install -r scripts/requirements.txt
```

## Authenticate

The default path is gcloud Application Default Credentials. You do not
need to register your own OAuth client.

```
python scripts/gsc_auth.py --adc            # prints the gcloud command
python scripts/gsc_auth.py --adc --write    # same, scoped for sitemap CRUD
```

Run the printed command, then verify:

```
python scripts/gsc_auth.py --check
python scripts/gsc_auth.py --sites
```

Set a quota project once (any Cloud project you have access to with the
Search Console API enabled):

```
python scripts/gsc_auth.py --quota-project <project-id>
```

Fallback for environments without gcloud (CI, locked-down workstations):

```
python scripts/gsc_auth.py --oauth --client-secret-file <path>
```

Credentials are resolved in this order: `GOOGLE_APPLICATION_CREDENTIALS`,
gcloud ADC, legacy OAuth file at `~/.claude/gsc-credentials.json`.

The same ADC token works against PageSpeed Insights and the Chrome UX
Report API — no separate API keys.

## Use it

### Claude Code

After authentication, slash commands work directly:

```
/gsc audit example.com
/gsc queries example.com --days 28
/gsc cwv example.com
/gsc pagespeed https://example.com/products/something
```

The full list lives in `skills/gsc/SKILL.md`.

### Codex

Codex reads `AGENTS.md` at the project root. The fastest path is the
one-command driver:

```
python scripts/gsc_audit.py --site example.com --output audit.md
```

### Gemini CLI

Gemini CLI reads `GEMINI.md`. Same Python CLI, same flags.

### Plain Python

Every feature is exposed as a Python CLI under `scripts/`. The runtimes
above are conveniences — anything they can do, you can do manually.

## Commands

Read:

```
/gsc audit <site>                full audit, agents in parallel, markdown by default
/gsc queries <site>              top queries
/gsc pages <site>                top pages
/gsc devices <site>              device split
/gsc countries <site>            country split
/gsc trends <site>               90-day time-series
/gsc ctr <site>                  CTR-vs-position curve check
/gsc inspect <site> <url>        URL Inspection (one URL at a time)
/gsc cwv <site>                  Core Web Vitals via CrUX
/gsc pagespeed <url>             per-URL Lighthouse pass
/gsc sitemaps <site>             list sitemaps with error / warning counts
/gsc backlinks <domain>          domain authority via Tranco + Open PageRank (free)
/gsc page-experience <host>      Mozilla Observatory + SSL Labs + local header probe
/gsc structured-data <site>      sitemap-wide JSON-LD validation
/gsc benchmarks                  inspect CWV thresholds and the CTR-by-position curve
```

Write (need `webmasters` scope, not `.readonly`):

```
/gsc submit-sitemap <site> <feedpath>
/gsc delete-sitemap <site> <feedpath>
/gsc add-site <site>
/gsc delete-site <site>
```

Auth:

```
/gsc auth
/gsc sites
```

## Property formats

GSC accepts both domain properties and URL-prefix properties. The
scripts accept either form, plus a bare domain:

- `example.com`            → normalised to `sc-domain:example.com`
- `sc-domain:example.com`  → used as-is (domain property)
- `https://example.com/`   → used as-is (URL-prefix property)

## How it works

`scripts/gsc_auth.py` resolves credentials. `gsc_data.py` wraps Search
Analytics `query`. `gsc_admin.py` wraps Sites, Sitemaps, and URL
Inspection (read + write). `gsc_psi.py` calls PageSpeed Insights for
per-URL Lighthouse. `gsc_crux.py` calls the Chrome UX Report for
origin-level / URL-level field CWV. `gsc_benchmarks.py` ships the
official Google CWV thresholds and a position-CTR curve.
`gsc_audit.py` is the one-command orchestrator; `gsc_report.py` renders
markdown, HTML, and PDF.

Agents under `agents/` are markdown specialist subagent definitions
Claude reads and dispatches. Skills under `skills/` provide the
`/gsc ...` routing surface for Claude Code. Codex and Gemini CLI use
the runtime-specific instruction files (`AGENTS.md`, `GEMINI.md`) plus
the same Python adapters.

## Project structure

```
google-search-console-agent/
  .claude-plugin/        plugin manifest and marketplace config
  agents/                specialist agent definitions
  docs/                  setup guide
  examples/              sample-audit.md showing the audit output shape
  hooks/                 placeholder for pre/post-tool guards
  scripts/               Python adapters and tests (the universal CLI)
  skills/
    gsc/                 top-level router skill
    gsc-audit/           one-command orchestrator
    gsc-search-analytics/   queries / pages / devices / countries / trends
    gsc-ctr-curve/       CTR vs position diagnostic
    gsc-url-inspect/     per-URL inspection
    gsc-core-web-vitals/ origin-level CrUX
    gsc-pagespeed/       per-URL Lighthouse / PSI
    gsc-sitemaps/        sitemap CRUD
  AGENTS.md              Codex instructions
  GEMINI.md              Gemini CLI instructions
  CLAUDE.md              Claude Code instructions
```

## Benchmarks

`scripts/gsc_benchmarks.py` ships two reference tables:

1. **Core Web Vitals thresholds** — Google's official good /
   needs-improvement / poor bands for LCP, INP, CLS, FCP, TTFB.
2. **CTR by SERP position** — a 2024 composite curve (FirstPageSage,
   Backlinko, Sistrix) for positions 1-20.

Findings that include a `metric` / `metric_value` pair are auto-enriched
with verdicts inline in the markdown report.

## Confidence labels

GSC doesn't expose a sampling signal the way GA4 does, so the audit
defaults to a `medium` confidence label. It drops to `low` only when
the search analytics fetch itself failed.

## Sample output

See [`examples/sample-audit.md`](examples/sample-audit.md) for a
hand-crafted audit showing the markdown report shape.

## Status

v0.2.0 — backlinks (Tranco + Open PageRank), page-experience
(Observatory + SSL Labs + local headers), and structured-data
(sitemap-wide JSON-LD validation) added. All read-side surfaces are
unit-tested with mocks. Sitemap CRUD wired and tested but not yet
covered by integration tests against a live property.

## License

MIT. See `pyproject.toml`.

## Acknowledgements

Built on top of the Google Search Console API (Search Analytics,
Sites, Sitemaps, URL Inspection), the PageSpeed Insights API, and the
Chrome UX Report API.
