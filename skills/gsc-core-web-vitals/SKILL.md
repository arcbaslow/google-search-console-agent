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
- Snapshot is a rolling 28-day window; history is 25 weeks at weekly
  resolution.
- Per-URL data is only available for URLs with enough sampled visits.
  Use `gsc-pagespeed` if you need per-URL synthetic Lighthouse data
  for a low-traffic page.

## After analysis

Offer:

- "Want the per-URL Lighthouse pass on the worst page? Use `/gsc pagespeed <url>`."
- "Want the full audit including search analytics? Use `/gsc audit <site>`."
