# GSC Audit — sc-domain:riverbedoutfitters.example

_Generated 2026-05-21 20:45_  
_Data confidence: **medium**_  

## Site Context

- Search Console property: `sc-domain:riverbedoutfitters.example`
- Permission level: siteOwner
- Sitemaps registered: 3
- Most recent sitemap submission: 2026-04-12T14:22:08Z
- Homepage title: Riverbed Outfitters
- Homepage HTTP status: 200
- Inferred framework: nextjs
- Inferred platform: shopify

## Executive Summary

- **gsc-overview**: site overview for sc-domain:riverbedoutfitters.example
- **gsc-search-analytics**: 94 queries, 38 pages scanned
- **gsc-ctr-curve**: 7 queries below CTR curve, 3 critical
- **gsc-core-web-vitals**: CrUX ALL_FORM_FACTORS: lcp_p75_ms=4350, inp_p75_ms=320, cls_p75=0.08
- **gsc-structured-data**: 20 URLs sampled, JSON-LD coverage 95.0%, verdicts {pass: 12, partial: 6, fail: 1, untyped: 0}
- **gsc-backlinks**: primary riverbedoutfitters.example: Tranco top_100k, Open PageRank 4.2
- **gsc-page-experience**: headers needs_improvement; observatory B; ssl-labs A
- **gsc-url-inspect**: stub - run /gsc inspect <site> <url> (or the Claude Code skill) for per-URL deep-dives

## Action Plan

### High

- **Organic clicks down 27% in the second half of the window** _(source: gsc-search-analytics)_
  - First half: 142,300 clicks; second half: 103,800 clicks (-27.1%).
- **Query acme rain jacket clicks-through below expected curve** _(source: gsc-ctr-curve)_
  - Position 1.6, observed CTR 9.4%, expected ~25.0% (impressions: 18,400). Usually a title / meta-description fix.
- **lcp_p75_ms above the poor threshold** _(source: gsc-core-web-vitals)_ (value 4350, good ≤ 2500, needs improvement ≤ 4000, verdict poor)
  - Observed p75 4350 (good <= 2500, needs improvement <= 4000). Preload hero image, defer non-critical scripts, audit third-party tags.
- **1 JSON-LD block(s) missing required fields** _(source: gsc-structured-data)_
  - Top missing fields across the sample: {Product.image: 1, Article.datePublished: 1}. Fix these to restore rich-results eligibility.

### Medium

- **Sitemap /sitemap-blog.xml reports 4 warnings** _(source: gsc-overview)_
  - Warnings are typically duplicate URLs or non-indexable entries. Worth a review.
- **inp_p75_ms above the needs-improvement threshold** _(source: gsc-core-web-vitals)_ (value 320, good ≤ 200, needs improvement ≤ 500, verdict needs_improvement)
  - Observed p75 320 (good <= 200, needs improvement <= 500). Break up long JS tasks on click handlers.
- **6 JSON-LD block(s) missing recommended fields** _(source: gsc-structured-data)_
  - Schemas validate but lack recommended fields that improve rich-results eligibility (Product.aggregateRating across 5 product pages, Article.dateModified on 1 blog post).
- **Site ranks #3 of 5 in the competitor set (Tranco)** _(source: gsc-backlinks)_
  - Tranco rank is a composite popularity signal, not pure authority. Combined with Open PageRank it sketches the gap that needs closing.
- **Security-header coverage 50.0% (needs improvement)** _(source: gsc-page-experience)_
  - Missing: content-security-policy, x-frame-options, permissions-policy
- **Mozilla Observatory grade B** _(source: gsc-page-experience)_
  - Score 75. Headroom for CSP / Referrer-Policy hardening.

## Per-Agent Output

### gsc-overview

site overview for sc-domain:riverbedoutfitters.example

<details>
<summary>raw output</summary>

```json
{}
```

</details>

### gsc-search-analytics

94 queries, 38 pages scanned

<details>
<summary>raw output</summary>

```json
{
  "top_queries": [
    {
      "query": "acme rain jacket",
      "clicks": 4820,
      "impressions": 41200,
      "ctr": 0.117,
      "position": 3.4
    }
  ]
}
```

</details>

### gsc-ctr-curve

7 queries below CTR curve, 3 critical

<details>
<summary>raw output</summary>

```json
{
  "below_curve_count": 7,
  "above_curve_count": 4
}
```

</details>

### gsc-core-web-vitals

CrUX ALL_FORM_FACTORS: lcp_p75_ms=4350, inp_p75_ms=320, cls_p75=0.08

<details>
<summary>raw output</summary>

```json
{
  "origin": "https://riverbedoutfitters.example"
}
```

</details>

### gsc-structured-data

20 URLs sampled, JSON-LD coverage 95.0%, verdicts {pass: 12, partial: 6, fail: 1, untyped: 0}

<details>
<summary>raw output</summary>

```json
{
  "rollup": {
    "urls_analyzed": 20,
    "urls_with_jsonld": 19,
    "block_verdicts": {
      "pass": 12,
      "partial": 6,
      "fail": 1,
      "untyped": 0
    },
    "type_counts": {
      "Product": 14,
      "BreadcrumbList": 12,
      "Article": 3,
      "Organization": 1
    }
  }
}
```

</details>

### gsc-backlinks

primary riverbedoutfitters.example: Tranco top_100k, Open PageRank 4.2

<details>
<summary>raw output</summary>

```json
{
  "primary": "riverbedoutfitters.example",
  "rows": [
    {
      "domain": "riverbedoutfitters.example",
      "tranco_rank": 78420,
      "tranco_band": "top_100k",
      "open_pagerank_decimal": 4.2
    },
    {
      "domain": "rei.com",
      "tranco_rank": 4210,
      "tranco_band": "top_10k",
      "open_pagerank_decimal": 6.8
    },
    {
      "domain": "patagonia.com",
      "tranco_rank": 8930,
      "tranco_band": "top_10k",
      "open_pagerank_decimal": 6.4
    },
    {
      "domain": "backcountry.com",
      "tranco_rank": 21500,
      "tranco_band": "top_100k",
      "open_pagerank_decimal": 5.7
    },
    {
      "domain": "moosejaw.com",
      "tranco_rank": 105200,
      "tranco_band": "top_1m",
      "open_pagerank_decimal": 4.5
    }
  ]
}
```

</details>

### gsc-page-experience

headers needs_improvement; observatory B; ssl-labs A

<details>
<summary>raw output</summary>

```json
{
  "host": "riverbedoutfitters.example",
  "headers": {
    "grade": "needs_improvement",
    "coverage_pct": 50.0,
    "headers_missing": [
      "content-security-policy",
      "x-frame-options",
      "permissions-policy"
    ]
  },
  "observatory": {
    "grade": "B",
    "score": 75
  },
  "ssl_labs": {
    "grade": "A",
    "endpoints_tested": 2
  }
}
```

</details>

### gsc-url-inspect

stub - run /gsc inspect <site> <url> (or the Claude Code skill) for per-URL deep-dives

<details>
<summary>raw output</summary>

```json
{}
```

</details>

---

_Generated by google-search-console-agent._
