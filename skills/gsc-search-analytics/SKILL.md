---
name: gsc-search-analytics
description: "Top GSC search analytics dimensions: queries, pages, devices, countries, search appearance, time-series. Returns clicks / impressions / CTR / position over a configurable window. Use when user says 'top queries', 'top pages', 'organic traffic', 'why are clicks dropping'."
user-invokable: true
argument-hint: "<site> [queries|pages|devices|countries|trends|appearance] [--days N] [--rows N] [--filter 'query CONTAINS pricing'] [--search-type web|image|video|news|discover|googleNews]"
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
`--data-state all` includes the most recent partial data — useful for
real-time monitoring but the last 1-2 days will jump around as the rest
of the data arrives.

## Date ranges

Default windows end three days back so all included dates are complete.
Override with `--days N` on any command.

## After analysis

Offer:

- "Want the CTR-vs-position curve check on these queries? Use `/gsc ctr <site>`."
- "Want to inspect a specific page? Use `/gsc inspect <site> <url>`."
- "Want to combine this with Core Web Vitals? Use `/gsc audit <site>`."
