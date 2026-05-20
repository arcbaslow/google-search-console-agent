# Changelog

## 0.2.0

- Add `gsc_backlinks.py` — domain-authority adapter combining Open
  PageRank (optional free API key) and Tranco top-1M (no key,
  weekly-refreshed local cache). Surfaces how authoritative a domain
  is vs competitors. Common Crawl noted as a future direction for the
  literal link graph.
- Add `gsc_page_experience.py` — Mozilla HTTP Observatory + SSL Labs +
  a local security-headers probe. Grades HSTS, CSP, Referrer-Policy,
  Permissions-Policy, X-Content-Type, X-Frame-Options, plus full TLS
  configuration. All sources free, no API keys.
- Add `gsc_structured_data.py` — local JSON-LD parser and Schema.org
  required-field validator. Site-wide rich-results audit (sitemap
  sample mode) and per-URL deep dive. Complements `gsc-url-inspect`
  which is quota-heavy and one URL at a time.
- Wire the three new agents into the audit driver. `structured-data`
  is always-on; `backlinks` (Open PageRank polling + Tranco lookup)
  and `page-experience` (Observatory + SSL Labs polling) are opt-in
  via `--with-backlinks` / `--competitors` and `--with-page-experience`.
- New skills: `gsc-backlinks`, `gsc-page-experience`,
  `gsc-structured-data`. New agents: matching `agents/gsc-*.md`.
- 47 new tests across the three new modules.

## 0.1.0

- Initial scaffold and v0.1 feature set.
- Auth via gcloud Application Default Credentials with OAuth installed-
  app fallback. No user-registered OAuth client required for the default
  path. Quota project setter included.
- Search Analytics adapter: top queries, top pages, devices, countries,
  search appearance, time-series, custom multi-dimension reports,
  filter parser.
- Sites + Sitemaps + URL Inspection adapter (`gsc_admin.py`). Sitemap
  CRUD plus site CRUD are write operations that require the
  `webmasters` scope.
- Chrome UX Report adapter (`gsc_crux.py`): origin-level snapshots and
  25-week weekly history for LCP, INP, CLS, FCP, TTFB. URL-level data
  for high-traffic pages.
- PageSpeed Insights adapter (`gsc_psi.py`): per-URL Lighthouse pass
  with category scores, lab metrics, field metrics (when CrUX has data
  for the URL).
- Benchmark engine (`gsc_benchmarks.py`): Google's official CWV
  thresholds + a 2024 composite organic CTR-by-position curve.
- One-command audit driver (`gsc_audit.py`) that orchestrates context
  → search analytics → CTR-curve → sitemap health → Core Web Vitals
  in parallel and renders the markdown report.
- Markdown audit renderer (`gsc_report.py`) plus HTML and PDF outputs.
  No emoji in the markdown output.
- Multi-runtime instruction files: `AGENTS.md` (Codex), `GEMINI.md`
  (Gemini CLI), `CLAUDE.md` (Claude Code).
- Top-level router skill (`skills/gsc/`) plus eight specialist skills:
  audit, search-analytics, ctr-curve, url-inspect, core-web-vitals,
  pagespeed, sitemaps, plus six matching subagent definitions.
