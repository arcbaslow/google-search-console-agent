---
name: gsc-url-inspect
description: "Per-URL inspection via GSC's URL Inspection API. Indexing state, last crawl, rich results coverage, page fetch state, canonical resolution. Quota-heavy — one URL per call. Use when user says 'is this URL indexed', 'why isn't this page indexed', 'rich results status'."
user-invokable: true
argument-hint: "<site> <url> [--lang en-US]"
license: MIT
metadata:
  author: arcbaslow
  version: "0.1.0"
  category: gsc
---

# GSC: URL Inspection

`urlInspection.index.inspect` returns Google's indexed-version analysis.
It does not perform the UI's live-URL test. The response includes:

- **Coverage** — `coverageState` text and separate indexing/fetch/robots states
- **Crawl** — last crawl time, page fetch state, robots.txt state
- **Indexability** — verdict (`PASS`, `FAIL`, `NEUTRAL`)
- **Canonical** — user-declared vs Google-selected canonical
- **Rich results** — result-level verdict, detected types and item issues
- **AMP** — declared and indexed AMP URL state (legacy)

## Direct command

```
python scripts/gsc_admin.py --site X --url https://X/foo --inspect --json
python scripts/gsc_admin.py --site X --url https://X/foo --lang en-US --inspect --json
```

The URL must belong to the property you pass (matching the property
prefix or domain).

## Quota note

URL Inspection counts heavily against the GSC API quota — 2,000
inspections per day, 600 per minute per property. The audit driver
deliberately omits URL inspection. Use this skill for targeted
diagnostics, not bulk scans.

## When to call

- A specific URL isn't ranking and you want to know why
- A new page launched and you need to confirm Google has crawled it
- Rich results disappeared and you want the per-item verdicts

## After analysis

Offer:

- "Want a Lighthouse pass for the same URL? Use `/gsc pagespeed <url>`."
- "Want the origin-level CWV trend? Use `/gsc cwv <site>`."

## Inspection reference limits

`mobileUsabilityResult` is deprecated; do not promise current mobile-usability
issues. See the [response reference](https://developers.google.com/webmaster-tools/v1/urlInspection.index/UrlInspectionResult).
The [inspect method](https://developers.google.com/webmaster-tools/v1/urlInspection.index/inspect)
reports the indexed version, not a live-URL test. Missing fields remain unknown.

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
