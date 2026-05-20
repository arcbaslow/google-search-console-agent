---
name: gsc-ctr-curve
description: "Compare per-query observed CTR to the position-based CTR curve. Surfaces queries with weak click-through for their average rank — almost always a title or meta-description fix. Triggers: 'low ctr', 'why is ctr low', 'title tag', 'meta description optimization'."
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
is a 2024 composite (FirstPageSage, Backlinko, Sistrix) and treats
positions 1-20.

A query that ranks well but clicks-through poorly is usually a title
tag / meta-description problem (or a SERP feature like an AI overview
eating the click). The skill highlights the worst offenders so the
user knows exactly which pages to rewrite.

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
| `above_curve` | Observed CTR ≥ 120% of expected — title / SERP feature is winning attention |
| `on_curve` | Observed CTR within ±15% of expected — no action needed |
| `below_curve` | Observed CTR 65-85% of expected — moderate title / meta fix |
| `below_curve_critical` | Observed CTR ≤ 65% of expected — high-leverage rewrite candidate |
| `low_volume` | Below 50 impressions — small-sample noise; skipped from action plan |

## Caveats

The curve assumes a "normal" SERP. AI overviews, featured snippets,
image packs, and site links all distort it. If a query's observed CTR
is dramatically below curve at position 1, check the SERP itself
before assuming the title is at fault.
