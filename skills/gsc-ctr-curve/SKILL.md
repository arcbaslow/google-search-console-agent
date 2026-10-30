---
name: gsc-ctr-curve
description: "Compare per-query observed CTR to the position-based CTR curve. Surfaces queries with weak click-through for their average rank - a candidate for intent and SERP review. Triggers: 'low ctr', 'why is ctr low', 'title tag', 'meta description optimization'."
user-invokable: true
argument-hint: "<site> [--days N] [--max-queries N]"
license: MIT
metadata:
  author: arcbaslow
  version: "0.1.0"
  category: gsc
---

# GSC: CTR vs Position Curve

For each query in the top set, compare observed CTR to the
position-CTR curve baked into `scripts/gsc_benchmarks.py`. The curve
is a legacy heuristic for positions 1-20 with unverified composite
provenance. Published studies differ; see [the roadmap](../../docs/ROADMAP.md).
It is not a current population estimate or a forecast of extra clicks.

Review intent, brand/device mix and SERP features before proposing a title
or description change. `benchmark_basis` discloses the heuristic in results.

## Process

1. Pull top queries (default 30) with their position and CTR
2. For each, look up the expected CTR for that position
3. Classify each query as `above_curve`, `on_curve`, `below_curve`,
   `below_curve_critical`, or `low_volume` (fewer than 50 impressions)
4. Surface the top 5 critical / below-curve queries as findings

## Direct invocation

```
python scripts/gsc_benchmarks.py --ctr-curve
python scripts/gsc_benchmarks.py --compare ctr_position 4.2 --observed 0.012 --impressions 8200
```

The audit driver runs this check automatically as part of `/gsc audit`.
Run it standalone when you want only the CTR diagnosis.

## Verdict bands

| Verdict | Meaning |
|---------|---------|
| `above_curve` | Observed CTR ≥ 120% of the heuristic |
| `on_curve` | Observed CTR > 85% and < 120% of the heuristic |
| `below_curve` | Observed CTR > 65% and ≤ 85% of the heuristic - review candidate |
| `below_curve_critical` | Observed CTR ≤ 65% of the heuristic - review candidate |
| `low_volume` | Below 50 impressions - small-sample noise; skipped from action plan |

## Caveats

The curve assumes a "normal" SERP. AI overviews, featured snippets,
image packs, and site links all distort it. If a query's observed CTR
is dramatically below curve at position 1, check the SERP itself
before assuming the title is at fault.
