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
A failed search worker lowers confidence to `low`; the existing convention
for other High search findings is unchanged. URL Inspection remains omitted.

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

This branch retains the legacy Open PageRank endpoint. Current docs describe
new authentication and response fields; migration requires a separate review.
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
