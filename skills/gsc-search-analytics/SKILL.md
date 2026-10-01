---
name: gsc-search-analytics
description: "Top GSC search analytics dimensions: queries, pages, devices, countries, search appearance, time-series. Returns clicks / impressions / CTR / position over a configurable window. Use when user says 'top queries', 'top pages', 'organic traffic', 'why are clicks dropping'."
user-invokable: true
argument-hint: "<site> [queries|pages|devices|countries|trends|appearance] [--days N] [--rows N] [--start-row N] [--filter 'query CONTAINS pricing'] [--search-type web|image|video|news|discover|googleNews]"
license: MIT
metadata:
  author: arcbaslow
  version: "0.1.0"
  category: gsc
---

# GSC: Search Analytics

Backed by `searchanalytics.query`. All commands accept a domain
(`example.com`), a domain property (`sc-domain:example.com`), or a
URL-prefix property (`https://example.com/`).

## Direct commands

| Intent | Command |
|--------|---------|
| Top queries | `python scripts/gsc_data.py --site X --queries --days 28 --rows 100 --json` |
| Top pages | `python scripts/gsc_data.py --site X --pages --days 28 --rows 100 --json` |
| Device split | `python scripts/gsc_data.py --site X --devices --days 28 --json` |
| Country split | `python scripts/gsc_data.py --site X --countries --days 28 --rows 25 --json` |
| Search appearance (e.g. AMP, video result) | `python scripts/gsc_data.py --site X --appearance --days 28 --json` |
| 90-day time series | `python scripts/gsc_data.py --site X --timeseries --days 90 --json` |
| Custom multi-dim report | `python scripts/gsc_data.py --site X --report --dimensions query,page --days 28 --rows 500 --json` |

## Filters

Pass `--filter "<dim> <op> <value>"`. Supported operators: `=`, `!=`,
`CONTAINS`, `NOT_CONTAINS`, `INCLUDING_REGEX`, `EXCLUDING_REGEX`.
Example:

```
python scripts/gsc_data.py --site X --queries --filter "query CONTAINS 'pricing'" --days 28
```

## Search types

`--search-type` accepts `web`, `image`, `video`, `news`, `discover`,
`googleNews`. Default is `web`.

## Data state

`--data-state final` (default) is fully aggregated; data lag is ~2 days.
`--data-state all` permits partial data within the requested window.
The adapter still ends that window three days back; it does not currently
expose today's or hourly data. Explicit dates/hourly support is proposed
in the roadmap.

## Date ranges

Default windows end three days back so all included dates are complete.
Override with `--days N` on any command.

## After analysis

Offer:

- "Want the CTR-vs-position curve check on these queries? Use `/gsc ctr <site>`."
- "Want to inspect a specific page? Use `/gsc inspect <site> <url>`."
- "Want to combine this with Core Web Vitals? Use `/gsc audit <site>`."

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

## Calendar trend comparisons

Audit click trends compare equal trailing calendar periods of at least seven
days each. An odd window excludes its earliest day. Output includes period
boundaries and missing-day counts. Missing or partial dates suppress the
percentage and decline finding; absent rows are not silently treated as zero.
A zero-click baseline has no percentage change. These are descriptive
comparisons, not causal diagnoses or seasonality adjustments.

## Search data confidence

Confidence is an availability convention: `medium` normally, `low` after a
search worker/subrequest failure or incomplete calendar-trend coverage.
A High SEO finding alone does not lower confidence. Search errors are also
listed by source under `data.source_errors`. This label does not estimate
sampling, statistical certainty or the quality of other sources.

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
