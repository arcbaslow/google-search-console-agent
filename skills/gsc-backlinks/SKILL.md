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

- **Open PageRank** (Domcop) — free signup at
  [openpagerank.com](https://www.domcop.com/openpagerank/). 1,000
  requests / day, 100 domains / request. Stored in environment as
  `OPENPAGERANK_API_KEY`.
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
# Free signup; takes ~1 minute
open https://www.domcop.com/openpagerank/

# Add the key to your shell init
export OPENPAGERANK_API_KEY="opr_xxxxxxxxxxxxxxxxxxxx"

python scripts/gsc_backlinks.py --domain example.com --json
```

Tranco works without any key — first run downloads the top-1M CSV
once (about 25 MB compressed), then lookups are instant.

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
