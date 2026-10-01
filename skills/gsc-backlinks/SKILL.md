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

- **Open PageRank** — current POST bulk API, at most 100 entries/request.
  Set `OPENPAGERANK_V1_API_KEY` to a new `opr_live_` key. Old DomCop keys
  are retired; see the migration instructions below. Quota headers and
  host/domain score scope are retained.

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
# Obtain a new OPR key from the current dashboard
export OPENPAGERANK_V1_API_KEY="opr_live_xxxxxxxxxxxxxxxxxxxx"

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

Open PageRank uses the current POST API and a newly issued OPR key.
Legacy environment keys are never transferred to the new host.
See [the roadmap](../../docs/ROADMAP.md) for endpoint and terms evidence. Tranco data
has upstream attribution and license conditions; downloaded lists are not
covered by this repository's MIT license.

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

## Tranco cache consistency

Tranco downloads are size-bounded (50 MB archive, 100 MB CSV), checked for
valid nonempty rank rows, and atomically replace the previous CSV. Failed
replacement preserves the old file. The in-memory index reloads when the
CSV's timestamp or size changes; a corrupt or empty list is unavailable,
not evidence that a domain ranks outside the list. Weekly refresh is unchanged.
Independent processes are not locked together and may download concurrently.
