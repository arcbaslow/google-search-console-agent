---
name: gsc-core-web-vitals
description: "Origin-level Core Web Vitals from the Chrome UX Report (CrUX) API. LCP, INP, CLS, FCP, TTFB at p75 over the last 28 days, classified against Google's official good / needs-improvement / poor thresholds. Optional 25-week weekly history. For per-URL deep dives use gsc-pagespeed."
user-invokable: true
argument-hint: "<site> [--form-factor PHONE|DESKTOP|TABLET|ALL_FORM_FACTORS] [--history] [--url <single-url>]"
license: MIT
metadata:
  author: arcbaslow
  version: "0.1.0"
  category: gsc
---

# GSC: Core Web Vitals

CrUX is the source of the public field data Google uses in Search
Console's own Core Web Vitals report. Origin-level data covers the
whole site if you have enough Chrome traffic; URL-level data is
available only for a subset of high-traffic pages.

## Direct commands

| Intent | Command |
|--------|---------|
| Origin snapshot | `python scripts/gsc_crux.py --origin https://X --json` |
| Phone-only | `python scripts/gsc_crux.py --origin https://X --form-factor PHONE --json` |
| Desktop-only | `python scripts/gsc_crux.py --origin https://X --form-factor DESKTOP --json` |
| 25-week history | `python scripts/gsc_crux.py --origin https://X --history --json` |
| Single URL | `python scripts/gsc_crux.py --url https://X/foo --json` |

## Thresholds (Google's official)

| Metric | Good ≤ | Needs Improvement ≤ | Poor > |
|--------|--------|---------------------|--------|
| LCP (p75 ms) | 2500 | 4000 | 4000 |
| INP (p75 ms) | 200  | 500  | 500  |
| CLS (p75)    | 0.10 | 0.25 | 0.25 |
| FCP (p75 ms) | 1800 | 3000 | 3000 |
| TTFB (p75 ms)| 800  | 1800 | 1800 |

## Verdict mapping

- All three of LCP, INP, CLS in "good" = passes Core Web Vitals
- Any of them in "needs improvement" or worse = does not pass
- INP replaced FID as a Core Web Vital in March 2024

## When to call

- Right before a launch: confirm the current site passes
- After a deployment: did we regress?
- Quarterly review: pull the 25-week history and look at trends

## Limits

- CrUX needs a meaningful volume of Chrome traffic. Small or new
  origins return `no_data` — the skill reports that gracefully.
- Snapshot is a rolling 28-day window; history defaults to 25 periods (up to 40) at weekly
  resolution.
- Per-URL data is only available for URLs with enough sampled visits.
  Use `gsc-pagespeed` if you need per-URL synthetic Lighthouse data
  for a low-traffic page.

## After analysis

Offer:

- "Want the per-URL Lighthouse pass on the worst page? Use `/gsc pagespeed <url>`."
- "Want the full audit including search analytics? Use `/gsc audit <site>`."

For URL-prefix properties, the audit derives CrUX origins from scheme and authority only. Domain-rank comparisons use the exact hostname, not the property path or a suffix match. Search Console requests keep the original property.

Use `--history --periods 40` for the maximum history; default remains 25.
Periods are overlapping 28-day aggregates sampled weekly. `ALL_FORM_FACTORS`
omits the wire filter. Missing p75 values are null, not zeros. Only LCP,
INP and CLS determine the Core Web Vitals pass; FCP/TTFB are diagnostics.

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

## PSI and CrUX quota attribution

PSI and CrUX apply the credential object's authentication headers, including
`x-goog-user-project` when a quota project is configured. Token refresh stays
in memory. This repairs omitted quota attribution; it does not enable APIs,
grant project permissions or prove OAuth scope compatibility. Live scope and
project verification remains an operator task. PSI field CLS scaling remains
unmodified pending an authoritative unit contract.

## Invalid benchmark values

CWV comparisons reject negative, nonnumeric, boolean and nonfinite values with
`invalid_metric_value`. Invalid values receive no band or verdict. Reports
retain the finding and continue benchmarking valid findings from other sources.
