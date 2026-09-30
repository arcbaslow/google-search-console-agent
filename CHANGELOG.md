# Changelog

## Unreleased

- Write shared JSON cache entries atomically, preserve the previous entry on write failure, and treat malformed JSON or invalid UTF-8 entries as cache misses.

- Redact mixed literal and percent-encoded identifiers in Search Analytics output, and repair affected cached results on access without another API request.

- Avoid counting a failed header probe twice in the combined page-experience action plan.

- Align inspection guidance with the current response fields and deprecations, and document actual authentication and cache-privacy limits.

- Add Search Analytics `--start-row` for a single explicit result page, with local offset and row-limit validation. No automatic pagination or URL Inspection calls are added.

- Add PSI `--raw` to expose complete Lighthouse diagnostics while keeping default CLI output compact. Add direct mocked request, cache, error and authentication tests.

- Preserve independent Tranco/Open PageRank results on source failure, distinguish unavailable ranks from outside-list ranks, and check both sources in single-domain audits with exact competitor-domain matching. Document the pending Open PageRank migration.

- Honor the Open PageRank key override in comparison mode without mutating the environment, and reject requests over 100 domains instead of silently truncating them.

- Fix the position-20 CTR lookup and disclose the curve's unverified heuristic basis. Separate FCP/TTFB diagnostics from Core Web Vitals in the metric list and remove unsupported CTR outcome claims.

- Correct structured-data field requirements, mark retired and unchecked types, count invalid JSON, and separate failed fetches from markup coverage. Local verdicts no longer claim Google rich-result eligibility.

- Correct all-form-factor CrUX requests, accept 1-40 history periods and emit JSON null for missing p75 values; add direct mocked adapter coverage.

- Derive valid CrUX origins and exact domain-rank targets from URL-prefix properties.

- Compare sitemap string counts numerically so `"0"` errors no longer produces a false High finding.

- Retain successful audit sections when a worker fails and show unavailable security sources in the action plan.

- Bound SSL Labs polling, display required remote-service notices, preserve source errors and honor `--no-cache` in combined page-experience reports.

- Use Mozilla Observatory v2 `/scan` and its POST response; report invalid, incomplete and failed scans explicitly.

- Require resolved-target confirmation inside every sitemap and site write adapter; refusal or EOF cancels before authentication or API access.

## [0.2.2] - 2026-09-08

### Added

- Distinct SVG banner and project icon, linked CI/release badges, and a screenshot of real output generated from synthetic fixtures.
- Reproducible offline examples, release notes, maintainer release instructions and a verification record.

### Changed

- Reorganized README around installation, first run, example output, supported capabilities and the actual CI checks.
- Corrected installation and capability claims, with explicit distinctions between agent workflows, direct CLI operations and optional integrations.

## 0.2.1 - 2026-08-14

- `scrub_pii` returned any all-digit string unmodified before the phone pass
  ran, so phone numbers, card numbers and national IDs reached the on-disk
  cache verbatim.
- `PHONE_RE` matched on length rather than digit count, so `2026-08-14`
  redacted to `[phone-redacted]` - every value in the GSC `date` dimension,
  meaning a cached time series came back with its dates destroyed. Redaction
  now requires nine real digits.
- Dots added to the phone separator class, and values are also checked
  percent-decoded since GSC returns page dimensions encoded.
- Ruff lint selection pinned. A re-run of CI reported 55 findings with no code
  change after ruff's implicit defaults widened, and lint runs before tests.
- The adapter modules are actually packaged now; `py-modules = []` meant a
  built wheel contained no importable code.
- Release workflow, Dependabot, and a version-consistency test.

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
