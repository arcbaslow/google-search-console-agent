# CLAUDE.md

Instructions for Claude Code working with `google-search-console-agent`.
Most of the universal guidance lives in [AGENTS.md](AGENTS.md); this
file covers Claude Code-specific notes only.

## Skills and subagents

Claude Code loads `skills/gsc/SKILL.md` as the top-level router. It
exposes `/gsc <command>` and routes to:

- `gsc-sitemaps` is the only skill with write surfaces (sitemap CRUD, site CRUD).

The `gsc-audit` skill calls `scripts/gsc_audit.py` directly — it's a
deterministic mechanical orchestrator. For richer LLM-driven analysis
on any single dimension, spawn the matching specialist subagent
defined under `agents/`.

## When to use Bash vs the Skills

Skills are sugar for the same Python adapters. If a user invokes `/gsc
audit`, use the skill. If a user asks a one-off question that maps to
a single script flag (e.g. "list sitemaps on example.com"), call the
script directly via the Bash tool:

```
python scripts/gsc_admin.py --site example.com --list-sitemaps --json
```

## Confirmation before writes

For every write (sitemap submit / delete, site add / delete), the
subagent (or you, if invoking directly) must show the resolved URL,
ask `y/N`, then run the command. Skill bodies wire this in; don't
bypass.

## Auth

Default path is gcloud Application Default Credentials. PSI and CrUX reuse
the resolver, but project enablement, quota attribution and scope compatibility
remain unverified live; see AGENTS.md and docs/ROADMAP.md.

```
python scripts/gsc_auth.py --check
python scripts/gsc_auth.py --adc            # prints the gcloud command
python scripts/gsc_auth.py --adc --write    # with webmasters write scope
```

Run the printed command, then `--check` again.

## Reports and benchmarks

Audit output defaults to markdown (no emoji) via
`scripts/gsc_audit.py --format md` or the lower-level
`scripts/gsc_report.py --format md`. The report attaches the site
context (permission level, sitemap inventory, homepage probe), the
data-confidence label, and benchmark verdicts to every finding that
carries a `metric` / `metric_value` pair. Benchmarks live in
`scripts/gsc_benchmarks.py` (CWV thresholds + position-CTR curve).
Pass `--format html` or `--format pdf` when the user wants those.

## Style for commits and output

- No marketing copy. Plain factual statements.
- No `feat:` / `fix:` / `chore:` Conventional Commits prefixes.
- No `Co-Authored-By:` trailers, no `Generated with...` footers, no emoji.
- Commit message style: short imperative sentence, sentence-case acceptable.

## Asset role (2026-08)

Shipped and public. Maintenance mode: bugfixes, Google API version bumps,
and docs only - the active OSS build slot belongs to capi-kit. Role:
portfolio proof for the measurement practice; the README should keep a link
to Good Labs services. New features need an explicit owner decision.

## Direct write confirmation

All four `gsc_admin.py` write functions print the resolved property and,
for sitemaps, the absolute feedpath to stderr, then ask `Apply? [y/N]`.
Only `y` proceeds. Refusal, EOF or interruption returns `status: cancelled`
without resolving credentials or calling the API. There is no bypass flag.
Keep stdout available for JSON. Show the user the adapter prompt; never
pipe an automatic answer or chain writes.

## Observatory contract

Page-experience checks use Mozilla Observatory v2 `/scan`: one POST returns
the result, with no GET polling. Errors or incomplete results are reported
explicitly. Security-header grades do not establish a ranking effect.

## External security checks

SSL Labs shows terms and remote-assessment notices on stderr, including its
`info` messages before assessment. Only assess authorized hosts; commercial
use needs Qualys permission. Polling uses a 120-second scheduling budget and
remaining-budget socket timeouts; a slow trickle response can exceed that
wall time. Incomplete scans return `error: timeout`. Overload errors include
retry hints and are not retried automatically. `--no-cache` also works in
combined mode, starting a fresh SSL scan once. Other source results survive
an individual source failure.

## Partial audit results

The audit retains successful workers when another raises, recording a
source-specific error and finding in stable output order. Page-experience
errors are visible as unavailable sources rather than a clean empty result.
Each source failure appears once in the action plan.
A failed search worker, failed search subrequest or incomplete trend coverage
lowers confidence to `low`. SEO finding severity does not set confidence.
URL Inspection remains omitted.

Sitemap error and warning counts are compared numerically, including Google API string values such as `"0"`; a zero count does not produce a finding.

For URL-prefix properties, the audit derives CrUX origins from scheme and authority only. Domain-rank comparisons use the exact hostname, not the property path or a suffix match. Search Console requests keep the original property.

## CrUX request semantics

`ALL_FORM_FACTORS` is a local CLI alias: the adapter omits `formFactor` on
the wire. History defaults to 25 weekly periods; `--periods` accepts 1-40.
Each period is an overlapping 28-day aggregate. Missing p75 values are JSON
null, not zero or NaN. FCP and TTFB are diagnostics, not Core Web Vitals.

## Structured-data verdict scope

JSON-LD verdicts are limited top-level field checks, not Google eligibility
results. `unchecked` marks unknown types and incomplete contextual rules;
`unsupported` marks retired FAQPage/HowTo rich results. Article variants and
Organization have no universal required fields. Rollups count invalid JSON
and report fetch failures separately from successfully analyzed pages. Do not
infer missing markup from failed fetches or recommend retired rich results.
See `skills/gsc-structured-data/SKILL.md` for the full verdict vocabulary.

## Benchmark interpretation

The position-CTR table is a legacy heuristic with unverified composite
provenance. Comparisons disclose `benchmark_basis`; position 20 uses the
table's 0.5% value. Do not promise recoverable clicks or infer a title defect
from the curve alone. LCP, INP and CLS are Core Web Vitals; `--list` separates
FCP and TTFB into `diagnostic_metrics`. Threshold values are unchanged.

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

Open PageRank uses the current POST bulk API with a separately configured
new OPR key; legacy environment keys are never transferred to its new host.
See `docs/ROADMAP.md` for endpoint and terms evidence. Tranco data
has upstream attribution and license conditions; downloaded lists are not
covered by this repository's MIT license.

## Raw PageSpeed diagnostics

`gsc_psi.py --url https://example.com --raw --json` includes the full PSI
response under `raw`, with audits at `raw.lighthouseResult.audits`. Default
output remains compact. The flag changes output only: the existing cache
already stores the complete response. Review raw URL/page content before
sharing it. Missing CrUX field data does not imply a passing field result.

## Explicit Search Analytics pages

Use `gsc_data.py --site example.com --queries --rows 100 --start-row 100`
for one request starting at the zero-based offset. `--start-row` defaults to
0 and applies to every query mode. The adapter validates nonnegative integer
offsets and row limits of 1-25,000 before authentication. `--rows` controls
queries, pages, countries and custom reports; devices, appearance and time
series retain their existing wrapper limits.

There is no automatic pagination. Search Console returns top rows and does
not guarantee an exhaustive export; offsets alone do not change that.
This flag never calls URL Inspection.

## Search Analytics redaction

The display/cache scrubber redacts mixed literal and percent-encoded email
and phone-like identifiers even when a redaction marker is already present.
Cache hits are rechecked and repaired on access without a new API call;
unchanged entries keep their existing lifetime. This does not sweep old
cache files or anonymize raw PSI, inspection or other adapter payloads.
Keep request targets separate from redacted display values.

## JSON cache consistency

Shared JSON cache writes serialize to a temporary file in the cache directory
and atomically replace the entry after closing it. A failed serialization or
replacement leaves the previous entry intact. Missing, expired, invalid-JSON
and invalid-UTF-8 entries are cache misses; permission and write failures
remain errors. The 15-minute TTL is unchanged. This applies to the shared
JSON cache, not the separate Tranco CSV cache.

## Inventory cache after writes

Empty site and sitemap lists are valid cache hits. After a successful site
add/delete, the adapter invalidates the site list and that property's sitemap
list. A successful sitemap submit/delete invalidates only that property's
sitemap list. Cancelled or failed API calls leave cached entries unchanged;
unrelated properties and URL Inspection caches are preserved.

All writes still show resolved targets and require `y/N`. If local cache
invalidation fails after the API succeeds, the success status is preserved
with `cache_warning`; surface it and do not repeat the remote write. Cache
invalidation does not guarantee upstream read-after-write consistency or
serialize independent processes that already have a read in flight.

## Calendar trend comparisons

Audit click trends compare equal trailing calendar periods of at least seven
days each. An odd window excludes its earliest day. Output includes period
boundaries and missing-day counts. Missing or partial dates suppress the
percentage and decline finding; absent rows are not silently treated as zero.
A zero-click baseline has no percentage change. These are descriptive
comparisons, not causal diagnoses or seasonality adjustments.

## Report formats

HTML and PDF include site context, source summaries, benchmark annotations,
source labels and per-agent data, matching the Markdown sections. The audit
passes its overview to all renderers. HTML escapes supplied values and uses
local fonts; PDF rendering needs no font download. Reports contain source
payloads and should be treated as private, regardless of format.

## Sitemap sample bounds

Structured-data sitemap sampling uses XML namespaces and entity decoding,
deduplicates URLs and orders them by SHA-256 for repeatable samples. `--sample`
accepts 1-100. Discovery tries two sitemap names relative to the supplied
property path and follows at most five child files total, one level deep.
DTD/custom entities are rejected. Only URLs within the supplied property are
sampled. `sampling` reports discovered/excluded counts, requests and errors;
it is explicitly non-exhaustive. Fetch coverage remains in `rollup`.

## Explicit dates and fresh search data

`gsc_data.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD` uses inclusive
Search Console PT dates and overrides `--days`. Without explicit dates the
existing three-day lag remains; `--data-state all` alone does not remove it.
Hourly custom reports require `--dimensions hour --data-state hourly_all`
and both dates. Google limits hourly availability; incomplete-data metadata
is retained verbatim under `metadata`, with `date_timezone` identifying PT.
Missing dates are not zero-filled. Offsets still fetch only one page.

`--compare-previous` is a standalone mode requiring both dates. It makes two
aggregate queries for adjacent equal periods, returning click/impression
percentage changes, CTR percentage-point change and position difference.
It never sums top rows. Zero baselines give null percentages; non-final data
suppresses differences. Freshness and seasonality still need interpretation.

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

## CrUX diagnostic detail

`gsc_crux.py --diagnostics` preserves all returned metric objects under
`diagnostics.metrics`, for snapshots and history. This includes available
histograms, fractions, LCP image subparts/resource types and round-trip time.
It uses the same single API request; absent metrics stay absent and missing
values become null. History distributions remain aligned to collection
periods. These diagnostics do not add Core Web Vitals or pass/fail thresholds.
Default compact output is unchanged.

## Read transport and quotas

GSC services use separate 60-second socket-timeout transports. Search Analytics
and site/sitemap reads may retry once for transient HTTP 500/502/503/504 or rate
limits, waiting one second by default. A valid Retry-After is honored only if
it fits five seconds; longer/invalid hints return immediately for manual action.
Access denial and explicit daily quota exhaustion are not retried. JSON errors
include HTTP status, category, reasons and the retry hint without raw bodies.
PSI and CrUX expose the same diagnostics but do not automatically retry.

Writes and URL Inspection never use the read retry policy. Authentication
401 replay is disabled on the Google transport; refresh happens before sending
when needed. These socket timeouts are not total wall-time guarantees. Quotas
are shared with other clients; the toolkit does not estimate remaining GSC quota.

## PSI and CrUX quota attribution

PSI and CrUX apply the credential object's authentication headers, including
`x-goog-user-project` when a quota project is configured. Token refresh stays
in memory. This repairs omitted quota attribution; it does not enable APIs,
grant project permissions or prove OAuth scope compatibility. Live scope and
project verification remains an operator task. PSI field CLS scaling remains
unmodified pending an authoritative unit contract.

## Tranco cache consistency

Tranco downloads are size-bounded (50 MB archive, 100 MB CSV), checked for
valid nonempty rank rows, and atomically replace the previous CSV. Failed
replacement preserves the old file. The in-memory index reloads when the
CSV's timestamp or size changes; a corrupt or empty list is unavailable,
not evidence that a domain ranks outside the list. Weekly refresh is unchanged.
Independent processes are not locked together and may download concurrently.

## Report privacy boundary

`gsc_audit.py --redact` and `gsc_report.py --redact` apply best-effort email,
phone and denied-key redaction to a copy of report data, including context,
findings and raw sections, before rendering. Audit JSON is covered too.
Requests always use the exact original property/URL; display redaction never
changes a request target or cache identity. Default output remains unchanged.

This is not anonymization: names, arbitrary identifiers, unknown encodings and
sensitive page content can remain. Review reports before sharing. Existing and
new adapter caches retain their documented raw-data contracts; this flag does
not purge or rewrite them. PSI/CrUX/Search Analytics `--no-cache` can avoid
cache use for targeted calls. Historical cleanup remains a separate proposal.
