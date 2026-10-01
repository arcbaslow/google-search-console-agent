---
name: gsc-structured-data
description: Sample static HTML and report JSON-LD field checks, retired types and coverage limitations.
model: sonnet
maxTurns: 15
tools: Read, Bash, Write
---

# GSC: Structured Data

Fetch a bounded sitemap sample or a single page and check JSON-LD in its
static HTML. These checks use no Search Console API or URL Inspection quota.

```bash
python scripts/gsc_structured_data.py --url https://example.com/products/foo --json
python scripts/gsc_structured_data.py --site example.com --sample 25 --json
```

The audit driver includes this check by default. Use
`--structured-data-sample 50` to change its sample size.

## Read the result

| Verdict | Meaning |
|---------|---------|
| `pass` | Implemented top-level field checks passed |
| `partial` | Recommended fields are missing |
| `fail` | An implemented required field is missing |
| `unchecked` | Unknown type or contextual/nested rules need manual review |
| `unsupported` | Google has retired this rich-result type |
| `untyped` | No `@type` is present |
| `invalid` | JSON could not be parsed |

No verdict guarantees Google eligibility or appearance. `validation_scope`
is `top_level_presence_only`. Product, JobPosting, Review, AggregateRating,
BreadcrumbList and Course need contextual validation; passing their minimum
field checks returns `unchecked`. For example, Product offers/reviews and
remote-job location requirements cannot be reduced to one mandatory list.

Article, NewsArticle, BlogPosting and Organization have no universally
required fields in Google's current documentation. Recipe requires name and
image; ingredients and instructions are recommended. Course list remains
supported, but Course info has retired. FAQPage and HowTo return
`unsupported`; their Schema.org syntax can still be valid.

## Coverage and findings

Use `urls_with_jsonld / urls_analyzed` only for successfully fetched pages.
Report `urls_attempted` and `fetch_failures` separately. A failed fetch does
not establish missing markup. Rollups include invalid JSON, unchecked and
unsupported blocks. Use `top_missing_required` to locate template problems,
then confirm the relevant Google requirements before suggesting a fix.

Recommend required-field and invalid-JSON repairs first. Treat recommended
fields and unchecked types as review work. Do not recommend adding FAQ or
HowTo markup for Google rich results, or assert that missing optional ratings
or Article authorship makes all markup ineligible.

## Limits and references

The parser does not execute JavaScript or read microdata/RDFa. An empty
result establishes only that this fetch contained no recognized JSON-LD.
Nested fields, value formats, page context and Google's content policies
require further review. Use Google's Rich Results Test for that review;
URL Inspection is a separate, explicit single-URL action, never a batch loop.

- [Google structured-data gallery](https://developers.google.com/search/docs/appearance/structured-data/search-gallery)
- [Article](https://developers.google.com/search/docs/appearance/structured-data/article)
- [Recipe](https://developers.google.com/search/docs/appearance/structured-data/recipe)
- [Documentation updates and retirements](https://developers.google.com/search/updates)

## Sitemap sample bounds

Structured-data sitemap sampling uses XML namespaces and entity decoding,
deduplicates URLs and orders them by SHA-256 for repeatable samples. `--sample`
accepts 1-100. Discovery tries two sitemap names relative to the supplied
property path and follows at most five child files total, one level deep.
DTD/custom entities are rejected. Only URLs within the supplied property are
sampled. `sampling` reports discovered/excluded counts, requests and errors;
it is explicitly non-exhaustive. Fetch coverage remains in `rollup`.
