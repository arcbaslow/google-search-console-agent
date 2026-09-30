---
name: gsc-backlinks
description: "Domain authority and competitor comparison via two free data sources: Open PageRank (PR-style 0-10 score, free API key) and Tranco top-1M (no key). Surfaces how strong a domain is vs the competitors you care about. For literal backlink lists see the Common Crawl roadmap note in the README."
user-invokable: true
argument-hint: "<domain> [--competitors a.com,b.com,c.com] [--tranco-only]"
license: MIT
metadata:
  author: arcbaslow
  version: "0.2.0"
  category: gsc
---

# GSC: Backlinks / Domain Authority

GSC's own UI does not expose link graph data via API. This skill fills
the hole with two free sources that, combined, answer the question
audits keep asking: "how authoritative is this site vs the competitors
we care about?"

- **Open PageRank** — optional legacy GET integration using
  `OPENPAGERANK_API_KEY`, at most 100 domains/request. Current
  [upstream documentation](https://openpagerank.keywordseverywhere.com/docs)
  describes a different API. Legacy availability and new-key compatibility
  are unverified; do not send new keys to the legacy host without review.
- **Tranco top-1M** — no key, no signup. Downloaded once and cached
  locally; refreshed weekly. Tells you whether the domain is in the
  global top 1k / 10k / 100k / 1M, which is a coarse but honest
  popularity signal.

## Direct commands

| Intent | Command |
|--------|---------|
| Single domain | `python scripts/gsc_backlinks.py --domain example.com --json` |
| Competitor compare | `python scripts/gsc_backlinks.py --compare example.com,competitor1.com,competitor2.com --json` |
| Tranco-only (no key) | `python scripts/gsc_backlinks.py --tranco example.com --json` |

## When to call

- Quarterly competitor benchmarking
- Outreach prioritisation — focus link-building energy on sites whose
  authority is similar to or higher than yours
- Before launching a campaign, snapshot the rank so you can measure
  movement six months later

## Setup

```
# Only use a compatible legacy key; current API migration is pending
export OPENPAGERANK_API_KEY="opr_xxxxxxxxxxxxxxxxxxxx"

python scripts/gsc_backlinks.py --domain example.com --json
```

Tranco works without any key — first run downloads the top-1M CSV
once, then lookups use the local cache. Download failures are reported separately.

## Caveats

- Open PageRank is one heuristic. It correlates with authority but
  doesn't equal it. Use as a directional metric, not as a single
  source of truth.
- Tranco is composite popularity, not authority. A heavily-trafficked
  site with no links still ranks well in Tranco; a niche-authority
  site with strong links may not appear in the top 1M at all.
- For the actual link graph, Common Crawl WAT files have the data
  (free, S3 bucket) but require cloud-scale processing. Roadmap.

## After analysis

Offer:

- "Want to add this to the full audit? Use `/gsc audit <site>
  --with-backlinks --competitors a.com,b.com`."

For URL-prefix properties, the audit derives CrUX origins from scheme and authority only. Domain-rank comparisons use the exact hostname, not the property path or a suffix match. Search Console requests keep the original property.

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

This branch retains the legacy Open PageRank endpoint. Current docs describe
new authentication and response fields; migration requires a separate review.
See [the roadmap](../../docs/ROADMAP.md) for endpoint and terms evidence. Tranco data
has upstream attribution and license conditions; downloaded lists are not
covered by this repository's MIT license.
