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

PSI and CrUX adapters currently send a bearer token from the same credential
resolver. They have no API-key flag. Project enablement, quota attribution
and scope compatibility were not verified live; see the authentication
review in docs/ROADMAP.md before assuming a GSC login covers both services.

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
| `python scripts/gsc_admin.py --site X --url https://X/foo --inspect --json` | One URL: indexing state, last crawl, rich results, canonical |

URL inspection is quota-heavy (2,000/day, 600/min per property). Use
sparingly; do not bulk-iterate.

### Core Web Vitals

| Command | Purpose |
|---------|---------|
| `python scripts/gsc_crux.py --origin https://X --json` | Origin-level CrUX snapshot |
| `python scripts/gsc_crux.py --origin https://X --form-factor PHONE --json` | Phone-only |
| `python scripts/gsc_crux.py --origin https://X --history --json` | 25 weekly overlapping 28-day periods by default |
| `python scripts/gsc_crux.py --url https://X/foo --json` | Single-URL field data |
| `python scripts/gsc_psi.py --url https://X/foo --strategy mobile --json` | Per-URL Lighthouse (lab + field + scores) |

### Sitemaps (writes need `--write` ADC scope)

| Command | Purpose |
|---------|---------|
| `python scripts/gsc_admin.py --site X --list-sitemaps --json` | List |
| `python scripts/gsc_admin.py --site X --feedpath URL --get-sitemap --json` | Get one |
| `python scripts/gsc_admin.py --site X --feedpath URL --submit-sitemap --json` | Submit |
| `python scripts/gsc_admin.py --site X --feedpath URL --delete-sitemap --json` | Delete |

### Backlinks / domain authority

| Command | Purpose |
|---------|---------|
| `python scripts/gsc_backlinks.py --domain example.com --json` | Single domain — Tranco rank + Open PageRank (needs `OPENPAGERANK_V1_API_KEY`) |
| `python scripts/gsc_backlinks.py --compare site.com,comp1.com,comp2.com --json` | Competitor comparison |
| `python scripts/gsc_backlinks.py --tranco example.com --json` | Tranco-only lookup (no key) |

Open PageRank requires a newly issued key in `OPENPAGERANK_V1_API_KEY`; legacy keys are no longer supported by upstream. See the migration instructions below.

### Page experience / security

| Command | Purpose |
|---------|---------|
| `python scripts/gsc_page_experience.py --host example.com --json` | Everything — Observatory + SSL Labs + local headers |
| `python scripts/gsc_page_experience.py --host example.com --headers --json` | Local-only fast probe |
| `python scripts/gsc_page_experience.py --host example.com --observatory --json` | Mozilla Observatory only |
| `python scripts/gsc_page_experience.py --host example.com --ssl --json` | SSL Labs only |

No API keys are used for these probes. SSL Labs polls within a 120-second scheduling budget; upstream latency and overload can prevent a completed result.

### Structured data (JSON-LD)

| Command | Purpose |
|---------|---------|
| `python scripts/gsc_structured_data.py --url https://X/foo --json` | Single-URL deep dive |
| `python scripts/gsc_structured_data.py --site example.com --sample 25 --json` | Sitemap-wide audit (25 URLs sampled) |

Fetches remote HTML and parses JSON-LD locally. Returns `pass`, `partial`, `fail`, `untyped`, `invalid`, `unchecked` or `unsupported`, plus missing-field and fetch-coverage rollups. These are limited field checks, not rich-result eligibility decisions.

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
| `python scripts/gsc_audit.py --site X --with-backlinks --competitors a.com,b.com --output audit.md` | Same plus competitor comparison |
| `python scripts/gsc_audit.py --site X --with-page-experience --output audit.md` | Same plus Observatory + SSL Labs (slow; SSL Labs polls) |
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

## Direct write confirmation

All four `gsc_admin.py` write functions print the resolved property and,
for sitemaps, the absolute feedpath to stderr, then ask `Apply? [y/N]`.
Only `y` proceeds. Refusal, EOF or interruption returns `status: cancelled`
without resolving credentials or calling the API. There is no bypass flag.
Keep stdout available for JSON. Show the user the adapter prompt; never
pipe an automatic answer or chain writes.

## Observatory contract

Page-experience checks use Mozilla Observatory v2 `/scan`: one POST returns
the result, with no GET polling. Errors or incomplete results are reported
explicitly. Security-header grades do not establish a ranking effect.

## External security checks

SSL Labs shows terms and remote-assessment notices on stderr, including its
`info` messages before assessment. Only assess authorized hosts; commercial
use needs Qualys permission. Polling uses a 120-second scheduling budget and
remaining-budget socket timeouts; a slow trickle response can exceed that
wall time. Incomplete scans return `error: timeout`. Overload errors include
retry hints and are not retried automatically. `--no-cache` also works in
combined mode, starting a fresh SSL scan once. Other source results survive
an individual source failure.

## Partial audit results

The audit retains successful workers when another raises, recording a
source-specific error and finding in stable output order. Page-experience
errors are visible as unavailable sources rather than a clean empty result.
Each source failure appears once in the action plan.
A failed search worker, failed search subrequest or incomplete trend coverage
lowers confidence to `low`. SEO finding severity does not set confidence.
URL Inspection remains omitted.

Sitemap error and warning counts are compared numerically, including Google API string values such as `"0"`; a zero count does not produce a finding.

For URL-prefix properties, the audit derives CrUX origins from scheme and authority only. Domain-rank comparisons use the exact hostname, not the property path or a suffix match. Search Console requests keep the original property.

## CrUX request semantics

`ALL_FORM_FACTORS` is a local CLI alias: the adapter omits `formFactor` on
the wire. History defaults to 25 weekly periods; `--periods` accepts 1-40.
Each period is an overlapping 28-day aggregate. Missing p75 values are JSON
null, not zero or NaN. FCP and TTFB are diagnostics, not Core Web Vitals.

## Structured-data verdict scope

JSON-LD verdicts are limited top-level field checks, not Google eligibility
results. `unchecked` marks unknown types and incomplete contextual rules;
`unsupported` marks retired FAQPage/HowTo rich results. Article variants and
Organization have no universal required fields. Rollups count invalid JSON
and report fetch failures separately from successfully analyzed pages. Do not
infer missing markup from failed fetches or recommend retired rich results.
See `skills/gsc-structured-data/SKILL.md` for the full verdict vocabulary.

## Benchmark interpretation

The position-CTR table is a legacy heuristic with unverified composite
provenance. Comparisons disclose `benchmark_basis`; position 20 uses the
table's 0.5% value. Do not promise recoverable clicks or infer a title defect
from the curve alone. LCP, INP and CLS are Core Web Vitals; `--list` separates
FCP and TTFB into `diagnostic_metrics`. Threshold values are unchanged.

## Domain request limits

`gsc_backlinks.py --api-key` applies to both `--domain` and `--compare`,
without changing the environment. Open PageRank requests above 100 domains
return `too_many_domains` before sending; the adapter never silently drops
domains or automatically batches requests. Tranco can still provide rows.

## Independent domain sources

A Tranco failure returns `tranco_band: unavailable` and `tranco_error`,
not `outside_top_1m`. Open PageRank results remain available, and Tranco
results remain available if Open PageRank fails. The audit checks both
sources even without competitors, reports unavailable sources, and matches
the primary domain exactly when comparing ranks.

Open PageRank uses the current POST bulk API with a separately configured
new OPR key; legacy environment keys are never transferred to its new host.
See `docs/ROADMAP.md` for endpoint and terms evidence. Tranco data
has upstream attribution and license conditions; downloaded lists are not
covered by this repository's MIT license.

## Raw PageSpeed diagnostics

`gsc_psi.py --url https://example.com --raw --json` includes the full PSI
response under `raw`, with audits at `raw.lighthouseResult.audits`. Default
output remains compact. The flag changes output only: the existing cache
already stores the complete response. Review raw URL/page content before
sharing it. Missing CrUX field data does not imply a passing field result.

## Explicit Search Analytics pages

Use `gsc_data.py --site example.com --queries --rows 100 --start-row 100`
for one request starting at the zero-based offset. `--start-row` defaults to
0 and applies to every query mode. The adapter validates nonnegative integer
offsets and row limits of 1-25,000 before authentication. `--rows` controls
queries, pages, countries and custom reports; devices, appearance and time
series retain their existing wrapper limits.

There is no automatic pagination. Search Console returns top rows and does
not guarantee an exhaustive export; offsets alone do not change that.
This flag never calls URL Inspection.

## Search Analytics redaction

The display/cache scrubber redacts mixed literal and percent-encoded email
and phone-like identifiers even when a redaction marker is already present.
Cache hits are rechecked and repaired on access without a new API call;
unchanged entries keep their existing lifetime. This does not sweep old
cache files or anonymize raw PSI, inspection or other adapter payloads.
Keep request targets separate from redacted display values.

## JSON cache consistency

Shared JSON cache writes serialize to a temporary file in the cache directory
and atomically replace the entry after closing it. A failed serialization or
replacement leaves the previous entry intact. Missing, expired, invalid-JSON
and invalid-UTF-8 entries are cache misses; permission and write failures
remain errors. The 15-minute TTL is unchanged. This applies to the shared
JSON cache, not the separate Tranco CSV cache.

## Inventory cache after writes

Empty site and sitemap lists are valid cache hits. After a successful site
add/delete, the adapter invalidates the site list and that property's sitemap
list. A successful sitemap submit/delete invalidates only that property's
sitemap list. Cancelled or failed API calls leave cached entries unchanged;
unrelated properties and URL Inspection caches are preserved.

All writes still show resolved targets and require `y/N`. If local cache
invalidation fails after the API succeeds, the success status is preserved
with `cache_warning`; surface it and do not repeat the remote write. Cache
invalidation does not guarantee upstream read-after-write consistency or
serialize independent processes that already have a read in flight.

## Calendar trend comparisons

Audit click trends compare equal trailing calendar periods of at least seven
days each. An odd window excludes its earliest day. Output includes period
boundaries and missing-day counts. Missing or partial dates suppress the
percentage and decline finding; absent rows are not silently treated as zero.
A zero-click baseline has no percentage change. These are descriptive
comparisons, not causal diagnoses or seasonality adjustments.

## Report formats

HTML and PDF include site context, source summaries, benchmark annotations,
source labels and per-agent data, matching the Markdown sections. The audit
passes its overview to all renderers. HTML escapes supplied values and uses
local fonts; PDF rendering needs no font download. Reports contain source
payloads and should be treated as private, regardless of format.

## Sitemap sample bounds

Structured-data sitemap sampling uses XML namespaces and entity decoding,
deduplicates URLs and orders them by SHA-256 for repeatable samples. `--sample`
accepts 1-100. Discovery tries two sitemap names relative to the supplied
property path and follows at most five child files total, one level deep.
DTD/custom entities are rejected. Only URLs within the supplied property are
sampled. `sampling` reports discovered/excluded counts, requests and errors;
it is explicitly non-exhaustive. Fetch coverage remains in `rollup`.

## Explicit dates and fresh search data

`gsc_data.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD` uses inclusive
Search Console PT dates and overrides `--days`. Without explicit dates the
existing three-day lag remains; `--data-state all` alone does not remove it.
Hourly custom reports require `--dimensions hour --data-state hourly_all`
and both dates. Google limits hourly availability; incomplete-data metadata
is retained verbatim under `metadata`, with `date_timezone` identifying PT.
Missing dates are not zero-filled. Offsets still fetch only one page.

`--compare-previous` is a standalone mode requiring both dates. It makes two
aggregate queries for adjacent equal periods, returning click/impression
percentage changes, CTR percentage-point change and position difference.
It never sums top rows. Zero baselines give null percentages; non-final data
suppresses differences. Freshness and seasonality still need interpretation.

## Open PageRank key migration

The adapter now calls `https://openpagerank.keywordseverywhere.com/v1/domains/bulk`
with Bearer authentication. Obtain a new `opr_live_` key from the upstream
[dashboard and docs](https://openpagerank.keywordseverywhere.com/docs), then set
`OPENPAGERANK_V1_API_KEY` or pass `--api-key`. `OPENPAGERANK_API_KEY` is ignored;
old DomCop keys are retired. No key is automatically forwarded to the new host.

One request accepts up to 100 entries and disables monthly history. Output
preserves score, domain/host rank scope, release date and quota headers. Missing
domains have null scores; the old integer score remains null. Host results are
matched exactly, with the documented `www` alias. Quota errors retain retry
hints without automatic retries. Scores remain proprietary service output,
not a vendored backlink index. Live authentication has not been tested.

## CrUX diagnostic detail

`gsc_crux.py --diagnostics` preserves all returned metric objects under
`diagnostics.metrics`, for snapshots and history. This includes available
histograms, fractions, LCP image subparts/resource types and round-trip time.
It uses the same single API request; absent metrics stay absent and missing
values become null. History distributions remain aligned to collection
periods. These diagnostics do not add Core Web Vitals or pass/fail thresholds.
Default compact output is unchanged.

## Read transport and quotas

GSC services use separate 60-second socket-timeout transports. Search Analytics
and site/sitemap reads may retry once for transient HTTP 500/502/503/504 or rate
limits, waiting one second by default. A valid Retry-After is honored only if
it fits five seconds; longer/invalid hints return immediately for manual action.
Access denial and explicit daily quota exhaustion are not retried. JSON errors
include HTTP status, category, reasons and the retry hint without raw bodies.
PSI and CrUX expose the same diagnostics but do not automatically retry.

Writes and URL Inspection never use the read retry policy. Authentication
401 replay is disabled on the Google transport; refresh happens before sending
when needed. These socket timeouts are not total wall-time guarantees. Quotas
are shared with other clients; the toolkit does not estimate remaining GSC quota.
