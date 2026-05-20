# AGENTS.md

Instructions for agentic coding tools (Codex, Aider, Continue, etc.)
working with `google-search-console-agent`. The Claude Code runtime
uses `CLAUDE.md`; Gemini CLI uses `GEMINI.md`; this file covers
everything else.

## What this project is

A multi-agent toolkit for Google Search Console plus the two adjacent
performance APIs (PageSpeed Insights and Chrome UX Report). The
interface is a set of Python scripts under `scripts/`. Skills and
subagents in `skills/` and `agents/` are Claude Code-specific sugar;
the Python scripts are the source of truth and work the same
everywhere.

## Authentication (do this first)

The user authenticates once via gcloud Application Default
Credentials. You should never ask the user to register their own
Cloud OAuth client unless they explicitly cannot install gcloud.

```
python scripts/gsc_auth.py --check          # verify creds resolve
python scripts/gsc_auth.py --adc            # print the gcloud command if not authed
python scripts/gsc_auth.py --adc --write    # same, with webmasters write scope
python scripts/gsc_auth.py --sites          # list accessible properties
```

If `--check` fails, print the output of `--adc` (or `--adc --write` for
sitemap CRUD) and tell the user to run that gcloud command. Write
features (sitemap submit/delete, site add/delete) need the
`webmasters` scope without the `.readonly` suffix.

The same ADC token works against PageSpeed Insights and the Chrome UX
Report API — no separate API keys.

## Universal CLI

Every feature is a Python CLI. Same flags across runtimes.

### Site / overview

| Command | Purpose |
|---------|---------|
| `python scripts/gsc_auth.py --sites` | List accessible Search Console properties |
| `python scripts/gsc_admin.py --site X --get-site --json` | Get one site |
| `python scripts/gsc_admin.py --site X --list-sitemaps --json` | List sitemaps + error/warning counts |

### Search analytics

| Command | Purpose |
|---------|---------|
| `python scripts/gsc_data.py --site X --queries --days 28 --rows 100 --json` | Top queries |
| `python scripts/gsc_data.py --site X --pages --days 28 --rows 100 --json` | Top pages |
| `python scripts/gsc_data.py --site X --devices --days 28 --json` | Device split |
| `python scripts/gsc_data.py --site X --countries --days 28 --rows 25 --json` | Country split |
| `python scripts/gsc_data.py --site X --timeseries --days 90 --json` | Daily time-series |
| `python scripts/gsc_data.py --site X --appearance --days 28 --json` | Search-appearance breakdown |
| `python scripts/gsc_data.py --site X --report --dimensions query,page --days 28 --rows 500 --json` | Custom multi-dim report |
| `python scripts/gsc_data.py --site X --queries --filter "query CONTAINS 'pricing'" --json` | Filtered query |

### URL inspection

| Command | Purpose |
|---------|---------|
| `python scripts/gsc_admin.py --site X --url https://X/foo --inspect --json` | One URL: indexing state, last crawl, rich results, canonical, mobile usability |

URL inspection is quota-heavy (2,000/day, 600/min per property). Use
sparingly; do not bulk-iterate.

### Core Web Vitals

| Command | Purpose |
|---------|---------|
| `python scripts/gsc_crux.py --origin https://X --json` | Origin-level CrUX snapshot |
| `python scripts/gsc_crux.py --origin https://X --form-factor PHONE --json` | Phone-only |
| `python scripts/gsc_crux.py --origin https://X --history --json` | 25-week weekly history |
| `python scripts/gsc_crux.py --url https://X/foo --json` | Single-URL field data |
| `python scripts/gsc_psi.py --url https://X/foo --strategy mobile --json` | Per-URL Lighthouse (lab + field + scores) |

### Sitemaps (writes need `--write` ADC scope)

| Command | Purpose |
|---------|---------|
| `python scripts/gsc_admin.py --site X --list-sitemaps --json` | List |
| `python scripts/gsc_admin.py --site X --feedpath URL --get-sitemap --json` | Get one |
| `python scripts/gsc_admin.py --site X --feedpath URL --submit-sitemap --json` | Submit |
| `python scripts/gsc_admin.py --site X --feedpath URL --delete-sitemap --json` | Delete |

### Benchmarks

| Command | Purpose |
|---------|---------|
| `python scripts/gsc_benchmarks.py --list` | Available metrics |
| `python scripts/gsc_benchmarks.py --compare lcp_p75_ms 3200` | CWV verdict |
| `python scripts/gsc_benchmarks.py --ctr-curve` | Position-CTR curve |
| `python scripts/gsc_benchmarks.py --compare ctr_position 3.1 --observed 0.048 --impressions 8200` | CTR vs curve |

### Reports

| Command | Purpose |
|---------|---------|
| `python scripts/gsc_audit.py --site X --output audit.md` | One-command full audit, markdown |
| `python scripts/gsc_audit.py --site X --format html --output audit.html` | HTML version |
| `python scripts/gsc_audit.py --site X --format pdf --output audit.pdf` | PDF via WeasyPrint |
| `python scripts/gsc_report.py --site X --inputs a.json,b.json --format md --output audit.md` | Render from pre-collected agent outputs |

## Confirmation before writes

For every write (sitemap submit / delete, site add / delete), print
the resolved feedpath / site URL first, then ask the user `y/N`
before executing. Do not chain writes without confirmation.

## When the user asks for analysis

Default workflow:

1. Run `gsc_auth.py --check` first; if it fails, surface the `--adc`
   command and stop.
2. If they didn't specify which property, run `gsc_auth.py --sites`
   and ask which one to use.
3. For broad audits ("audit my SEO", "give me an overview"), use the
   one-command driver: `python scripts/gsc_audit.py --site X --output
   audit.md`. It already orchestrates everything in parallel.
4. For targeted questions, call the relevant script directly.
5. Always pass `--json` and parse the structured output.
6. Finish with a prioritized action plan: Critical > High > Medium >
   Low.

### Benchmark-aware findings

When emitting a finding with a Core Web Vital, include `metric` and
`metric_value`:

```json
{"severity": "High", "title": "LCP in poor band",
 "detail": "...", "metric": "lcp_p75_ms", "metric_value": 4350}
```

The reporter calls `gsc_benchmarks.compare_cwv()` and appends a band +
verdict phrase to the finding line.

## Style

- No marketing copy in output or commits.
- No `feat:` / `fix:` / `chore:` Conventional Commits prefixes.
- No `Co-Authored-By:` trailers, no `Generated with...` footers.
- Plain imperative commit messages, sentence-case acceptable.
- Funnel-style cross-references where useful: link `gsc-pagespeed` to
  `gsc-core-web-vitals` for users who want both per-URL and origin-
  level data; link `gsc-ctr-curve` to `gsc-search-analytics` for users
  digging into a specific query.
