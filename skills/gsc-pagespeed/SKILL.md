---
name: gsc-pagespeed
description: "PageSpeed Insights / Lighthouse pass for a single URL. Returns lab and field CWV plus Lighthouse SEO, accessibility, best-practices, and performance scores. The right tool for per-page deep-dives. For origin-level field data use gsc-core-web-vitals."
user-invokable: true
argument-hint: "<url> [--strategy mobile|desktop] [--categories performance,seo,accessibility,best-practices] [--locale en] [--raw]"
license: MIT
metadata:
  author: arcbaslow
  version: "0.1.0"
  category: gsc
---

# GSC: PageSpeed Insights

PSI runs Lighthouse against a URL in real time and returns:

- **Lighthouse category scores** (0-1): performance, SEO, accessibility, best-practices
- **Lab metrics**: LCP, CLS, TBT, FCP, Speed Index — measured under PSI's emulated conditions
- **Field metrics**: same CWV as CrUX, if there's enough data for the URL
- **The full PSI response** (under `raw` only with `--raw`; Lighthouse is at `raw.lighthouseResult`) with every individual audit, opportunity, and diagnostic

Authentication: the ADC bearer token works directly. No PSI API key is
required.

## Direct commands

| Intent | Command |
|--------|---------|
| Mobile pass | `python scripts/gsc_psi.py --url https://X/foo --strategy mobile --json` |
| Desktop pass | `python scripts/gsc_psi.py --url https://X/foo --strategy desktop --json` |
| Performance + SEO only | `python scripts/gsc_psi.py --url https://X/foo --categories performance,seo --json` |

## Scoring bands

| Lighthouse category score | Verdict |
|---------------------------|---------|
| ≥ 0.90 | good |
| 0.50 - 0.89 | needs_improvement |
| < 0.50 | poor |

## When to call

- A specific page is slow and you want the audit waterfall
- You want pre-deploy lab metrics for a new template
- CrUX says the origin passes but a specific URL feels slow
- You need accessibility / SEO scores per page (Lighthouse exposes these; CrUX does not)

## Caveats

- Lab vs field: PSI lab is emulated on Moto G Power at slow 4G —
  conservative compared with most real users on broadband. Field data
  in the same response (when present) is the better representation.
- Speed Index and TBT are lab-only metrics; they are useful as
  pre-deploy regression signals but do not map to CWV thresholds.
- Each PSI call is a fresh Lighthouse run and takes 15-45 seconds.
  Cache to disk for repeat invocations.

## After analysis

Offer:

- "Want this URL's indexing state? Use `/gsc inspect <site> <url>`."
- "Want origin-level CWV instead? Use `/gsc cwv <site>`."

## Raw PageSpeed diagnostics

`gsc_psi.py --url https://example.com --raw --json` includes the full PSI
response under `raw`, with audits at `raw.lighthouseResult.audits`. Default
output remains compact. The flag changes output only: the existing cache
already stores the complete response. Review raw URL/page content before
sharing it. Missing CrUX field data does not imply a passing field result.
