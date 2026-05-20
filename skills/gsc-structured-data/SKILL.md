---
name: gsc-structured-data
description: "Site-wide structured-data audit. Parses JSON-LD from a sample of sitemap URLs locally and validates required fields per Schema.org type (Product, Article, FAQPage, HowTo, Recipe, Event, BreadcrumbList, Organization, JobPosting, …). Complements gsc-url-inspect, which is quota-heavy and one URL at a time."
user-invokable: true
argument-hint: "<url> | <site> [--sample N]"
license: MIT
metadata:
  author: arcbaslow
  version: "0.2.0"
  category: gsc
---

# GSC: Structured Data

GSC's URL Inspection API exposes rich-results status per URL, but it
caps at 2,000 calls per day and one URL per request. This skill samples
N URLs from the sitemap, parses every JSON-LD block locally, and
validates required + recommended fields per schema type. No API quota.

## Direct commands

| Intent | Command |
|--------|---------|
| Single URL | `python scripts/gsc_structured_data.py --url https://example.com/products/foo --json` |
| Sitemap sample | `python scripts/gsc_structured_data.py --site example.com --sample 25 --json` |
| Sitemap sample (bigger) | `python scripts/gsc_structured_data.py --site example.com --sample 100 --json` |

## What's checked

For each JSON-LD block found, the validator looks up the `@type`
against the bundled required- and recommended-field tables and reports:

- **pass** — required fields all present
- **partial** — required ok, recommended fields missing (still
  eligible for rich results but weaker)
- **fail** — required field(s) missing (rich-results not eligible)
- **untyped** — block has no `@type`
- **invalid** — JSON couldn't be parsed

The sitemap-sample mode also rolls up a top-10 "most-commonly-missing
required field" list across the sample — that tells you what one
template fix would lift the whole site.

## Supported schema types

Required-field validation covers:

- `Product`, `Article`, `NewsArticle`, `BlogPosting`
- `FAQPage`, `Question`
- `HowTo`
- `Recipe`
- `Event`
- `BreadcrumbList`
- `Organization`, `LocalBusiness`
- `VideoObject`
- `Course`
- `JobPosting`
- `Review`, `AggregateRating`

Other types are surfaced under `types_found` but not validated.

## When to call

- After a template change — did the new product template drop a
  required field?
- Before submitting a sitemap — clean rich-results coverage at launch
  prevents Google from learning to ignore your markup
- Periodically alongside `/gsc inspect <url>` for spot-checks

## Caveats

- This is a static-HTML analyser. JSON-LD that is rendered client-side
  by JavaScript will not be visible to the parser. (Most modern SSR
  frameworks emit JSON-LD in the HTML; client-only SPAs are the
  exception.)
- The required-field tables match Google's rich-results docs as of
  the version pinned in `gsc_structured_data.REQUIRED_FIELDS`. Update
  when Google adds new rich-result types.

## After analysis

Offer:

- "Want a per-URL deep dive on a specific page? Use `/gsc inspect
  <site> <url>`."
- "Want to wire this into the full audit? It already is — pass
  `--structured-data-sample 50` to `/gsc audit` for a bigger sample."
