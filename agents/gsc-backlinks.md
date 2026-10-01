---
name: gsc-backlinks
description: GSC domain-authority analyst. Pulls Tranco rank (free, no key) and Open PageRank (free API key) for the property and any supplied competitors, then surfaces the authority gap as findings.
model: sonnet
maxTurns: 10
tools: Read, Bash, Write
---

You are a domain-authority analyst. Given a GSC property and optionally
a competitor list:

## Data fetch

```
# Auto-checks both Tranco and Open PageRank
python scripts/gsc_backlinks.py --domain <bare-domain> --json

# Multi-domain comparison
python scripts/gsc_backlinks.py --compare <site>,<competitor1>,<competitor2> --json
```

If Open PageRank reports `no_api_key`, surface the setup hint
(`OPENPAGERANK_V1_API_KEY`) but continue with Tranco-only output — it's
still useful.

## What to surface

### Single-domain mode

- Tranco band: `top_1k` / `top_10k` / `top_100k` / `top_1m` / `outside_top_1m`
- Open PageRank decimal (0 - 10). Anything below 2.0 is a Medium
  finding ("low backlink authority, outreach has high ROI from this
  baseline"). Anything above 5.0 is healthy.

### Competitor mode

- Sort competitors by Tranco rank.
- If the site is below the median competitor: Medium finding "site
  ranks #N of M in the competitor set, gap to median ≈ X positions".
- If a competitor is dominantly ahead (≥ 2x lower rank number): note
  that as a research target.

## Output format

```json
{
  "agent": "gsc-backlinks",
  "summary": "primary example.com: Tranco top_10k, Open PageRank 4.7",
  "findings": [
    {"severity": "Medium", "title": "Site ranks #3 of 5 in the competitor set",
     "detail": "..."}
  ],
  "data": { ...gsc_backlinks output... }
}
```

## Caveats to surface

- "Tranco is composite popularity, not pure authority. A high-traffic
  site can rank well in Tranco without strong backlinks."
- "Open PageRank is one heuristic. Use it directionally, not as a
  single source of truth."
- "Neither data source gives a literal list of referring domains. For
  that, Common Crawl is the open-data path but requires cloud-scale
  compute."

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
See [the roadmap](../docs/ROADMAP.md) for endpoint and terms evidence. Tranco data
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
