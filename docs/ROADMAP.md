# Roadmap

Reviewed 2026-09-30 against `master` at `5251dd6` (v0.2.2). The owner
authorized this feature pass; the normal maintenance policy still applies
after it. Scripts remain the interface and source of truth. No release,
remote write, bulk URL inspection, paid dependency, or new service is planned.

Evidence below distinguishes code inspection, mocked reproduction, upstream
documentation, and unverified live behavior. Baseline file/line references
refer to `5251dd6`, so they remain useful after fixes move the code.
Effort is approximate developer time including tests and documentation.

## Current disposition — 2026-10-01

Continued from `051b59a` on `roadmap-work` at the owner's request to cover the
remaining roadmap. All Now work remains complete. The bounded Next changes
below are implemented. A proposal or unresolved verification item is not
counted as implemented. The original instruction to leave large/project-shape
changes as proposals still governs the contextual rule engine and Later work.
No new service, paid dependency, bulk inspection or write bypass was added.

| Roadmap item | Disposition and implementation evidence | Remaining limitation |
| --- | --- | --- |
| Search windows and hourly data | Implemented: `d7920c5`, `385f278`; `scripts/gsc_data.py:162,179`. Explicit PT windows, hour/partial metadata, adjacent aggregate comparisons. | Aggregate queries cannot establish daily coverage; use time-series coverage for recent windows. GSC top-row limits remain. |
| Open PageRank migration | Implemented: `26ca953`, `612956a`; `scripts/gsc_backlinks.py:59`. New host, POST/Bearer, separately configured OPR key, host scores and quota diagnostics. | Current [migration docs][opr-docs] explicitly retire old DomCop keys. This resolves the earlier key-compatibility question at the documentation level; live new-key access remains untested. |
| Context-aware rich results | Reviewed; retained as a substantial proposal. See the design below and current [product snippets][product], [merchant listings][merchant], [reviews][reviews], [jobs][jobs] and [breadcrumbs][breadcrumbs]. | Current verdicts stay limited/unchecked. A flat field list cannot implement profile, parent and graph rules reliably. |
| Read transport and quota diagnostics | Implemented: `da27fa7`; `scripts/gsc_utils.py:207,224`. Explicit socket timeout, one bounded eligible-read retry, status/reason/retry-hint output. | No write/inspection retry or quota ledger. Existing Google client already had a default timeout; this makes policy explicit, not a previously proven infinite-timeout fix. |
| Cache privacy and consistency | Reviewed and bounded improvements implemented: prior cache commits plus `2d5876a`, `c532dc6`. Tranco replacement/reload and display-copy redaction. See privacy contract below. | Raw cache contents, historical cleanup and cross-process in-flight coordination are not redesigned or claimed anonymous. |
| Sampling and trend validity | Implemented: `27d070d`, `d3c1504`; `scripts/gsc_audit.py:183`, `scripts/gsc_structured_data.py:234`. Equal calendar windows, missing-day disclosure, bounded XML discovery, stable samples. | Discovery remains relative to the supplied property path; host-root discovery is not silently substituted. Samples are non-exhaustive. |
| PSI units and authentication | Reviewed; quota header loss fixed in `4eb3c21` using credential `apply()`. `scripts/gsc_psi.py:35`, `scripts/gsc_crux.py:41`; [google-auth contract][auth-headers]. | Current [PSI reference][psi-reference] did not establish CLS scaling. Unit behavior unchanged. Project enablement, permissions and OAuth scope compatibility need credentialed operator verification. |
| More CrUX diagnostics | Implemented: `44f5d44`; `scripts/gsc_crux.py:162`. Optional complete metric objects for snapshot/history, including distributions and missing periods. | Metric availability varies; diagnostic values have no invented CWV thresholds. [CrUX contract][crux-api]. |
| Reports and instructions | Implemented: `a72e24e`, `dc2f4ba`, `3ff157d`; `scripts/gsc_report.py:210`. Context/benchmark/source parity, availability-based confidence, invalid-metric handling. Runtime files and affected agents/skills updated together. | Confidence is a convention, not statistical certainty. PDF delegation is mocked; native PDF layout was not visually verified. |
| Read-only MCP facade | Proposal retained, with acceptance criteria below. | New distribution/auth lifecycle; excluded by the original project-shape limit. |
| Bounded export and local history | Proposal retained. Explicit one-page offsets and aggregate comparisons are available now. | Persistence, retention and pagination completeness require a separate design. |
| Property-specific CTR reference | Proposal retained. | Requires statistical validation, cohort choices and minimum sample policy; no invented universal replacement curve. |
| Cross-product analysis | Proposal retained. | GA4 scopes, joins and attribution change the toolkit's scope. |

Validation: baseline 296 tests, final 359 tests; Ruff, version consistency,
build, Twine and whitespace checks passed. See [verification](VERIFICATION.md)
for commits and limits. The original planning tables and research below are
preserved as historical evidence; this disposition supersedes their pending
statuses where a change is implemented.

### Concrete proposals not built

These are proposed acceptance criteria, not shipped capabilities. Original
rough efforts and risks remain in the Next/Later tables.

- **Contextual schema engine (4-7 days):** introduce named profiles such as
  product snippet and merchant listing. Rule output should include the profile,
  rule identifier, JSON path, source URL/review date and unchecked conditions.
  Resolve local `@id` graph references with cycle/depth bounds; never fetch a
  remote context/reference. Evaluate alternatives, all applicable list members,
  parent types and remote-job conditions. Use synthetic positive/negative
  fixtures for each documented alternative, mixed-type nodes, dangling IDs and
  cycles. Keep editorial/content eligibility and Google's display decision
  explicitly unchecked. Do not promote a presence check to eligibility.
- **MCP facade (about one week):** optional dependency and read-only stdio tools
  that call the Python adapters directly. Initially exclude site/sitemap writes
  and URL Inspection. Define process-local auth/cache lifecycle, structured
  errors and per-call limits. Acceptance requires protocol tests, parity with
  adapter output, no credentials in responses and no background crawling.
  Existing comparator evidence: [AminForou][mcp], [AkashRajpurohit][mcp-compare].
- **Export/history (about one week):** separately opt-in local storage with
  explicit property, dates, row/request caps, stop reason, schema version,
  aggregation type and collection timestamp. Distinguish an exhausted page
  sequence from a complete GSC dataset. Design retention/deletion before storing
  raw queries; never derive weighted CTR/position from averages without their
  denominators. Test caps, empty pages, failures and resumable provenance.
  Evidence: [query limits][query], [Python toolkit][python-toolkit],
  [better-search-console][better-mcp].
- **Property CTR reference (about one week):** user-selected cohorts by device,
  country, brand and search type; sufficient impressions/queries, uncertainty
  intervals and held-out validation. Preserve aggregation and privacy caveats.
  Return insufficient evidence rather than a curve for sparse cohorts. Validate
  on synthetic data before optional user-owned datasets. Publisher differences
  remain documented in [FPS][fps], [Backlinko][backlinko] and [Sistrix][sistrix].
- **GSC/GA4 joins (two or more weeks):** separate read-only integration proposal
  specifying scopes, canonical/landing-page mapping, timezone reconciliation,
  attribution and consent-related missingness. Never equate Search Console
  clicks with GA4 sessions. Test mappings and coverage before causal claims.
  Comparator: [Google SEO MCP][cross-product].

### Privacy and cache contract

Exact request inputs and hashed cache identity remain distinct from display
copies. Search Analytics continues its existing pre-cache scrub. PSI raw
Lighthouse data, inspection and other raw payloads stay private source data;
rewriting them universally would lose diagnostic fidelity and can change URL
identity. `--redact` is a separate, best-effort report operation after retrieval,
not a cache scrub, de-identification guarantee or safe-to-publish assertion.
No existing user cache or credential file was inspected during this review.

Historical cleanup remains a proposal (roughly 1-2 days): a manifest/dry-run of
known cache entries, explicit deletion scope, no symlink traversal, no credential
paths and mocked temporary-directory tests before any destructive command.
Cross-process ordering remains a proposal (roughly 2-3 days): choose a lock or
generation scheme, then test a read racing with successful invalidation. Atomic
replacement prevents partial files but does not establish that ordering.
Neither change is necessary to use the current bounded adapters safely within
their documented cache contract.

### Verification still unavailable

No live Google API request, third-party scan or authenticated OPR request was
made. Remaining unknowns are actual quota balances, account scopes/permissions,
new OPR key acceptance, live SSL Labs v3 behavior, PSI field CLS units, the
original CTR composite derivation and Tranco commercial redistribution rights.
The Ubuntu/Python 3.10-3.13 CI matrix and native PDF layout were not run locally.
These are open verification items, not completed tasks or inferred failures.

[merchant]: https://developers.google.com/search/docs/appearance/structured-data/merchant-listing
[auth-headers]: https://google-auth.readthedocs.io/en/latest/reference/google.auth.credentials.html#google.auth.credentials.Credentials.apply
[google-http]: https://googleapis.github.io/google-api-python-client/docs/epy/googleapiclient.http-module.html

## Baseline

- Clean checkout on `master`; created `roadmap-work` from `5251dd6`.
- Installed `.[dev]` in `.venv` per CONTRIBUTING.md. Windows, Python
  3.12.14; Ruff 0.16.9; pytest 9.1.1. Initial sandboxed package download
  failed; the approved dependency installation succeeded.
- `ruff check scripts/`: passed. `pytest scripts/ -q`: 129 passed.
  Baseline used an external pytest hook replacing only the `fake_creds`
  fixture with an in-memory object, avoiding its temporary credential file.
  Production code and assertions were unchanged.
- Coverage diagnostic: PSI 0%, CrUX 17% (imports, no direct adapter tests),
  admin 44%, auth 38%, audit 66%. Coverage percentage alone is not a target.
- `.github/workflows/tests.yml` requires lint and mocked tests on Python
  3.10, 3.11, 3.12 and 3.13 on Ubuntu. Only 3.12 is available locally.
  `release.yml` additionally checks the version, builds sdist/wheel and runs
  `twine check`; run those locally without publishing. Version stays 0.2.2.
- No authentication command or live Google query was run. Credentials and
  `.secrets/` were not inspected. Research used public documentation.

## Now

Completed on `roadmap-work`. The table preserves the original scoped plan
and baseline evidence. Fixes have mocked regression tests; the two read-only
features followed the planned fixes. A final review also removed duplicate
header-failure findings introduced by the combined-source error reporting.

| Item | What and SEO value | Evidence | Effort | Risk |
| --- | --- | --- | --- | --- |
| N1. Enforce offline tests | Keep synthetic auth in memory and block unmocked sockets/ADC resolution. Makes the verification promise enforceable. | `scripts/conftest.py:24` creates a credential-shaped file; no global network guard exists. | 1 hour | Low; tests must explicitly mock auth. |
| N2. Confirm every write | Print resolved property and sitemap URL, ask `y/N` inside each write adapter, cancel on refusal/EOF. Protects the property when called directly or through an agent. | `scripts/gsc_admin.py:50-61,84-97`; README admits direct writes skip prompts; SECURITY.md explicitly includes this failure. | 2 hours | Intentional break for unattended writes; no bypass flag. |
| N3. Repair security-service calls | Use Observatory v2's synchronous POST result, bound SSL polling by remaining monotonic budget, expose incomplete/error results, preserve other sources, and forward `--no-cache` in combined mode. Include SSL Labs terms and server notices. | `scripts/gsc_page_experience.py:39,123-177,182-241,264`; [Mozilla contract][observatory], [SSL v3][ssl-api], [SSL terms][ssl-terms]. | 1 day | External services may change; no live scans in tests. |
| N4. Preserve useful audit results | Catch worker failures at collection, show source errors instead of a successful empty summary, parse sitemap string counts, and derive a real origin/host from URL-prefix properties. SEO reports should survive one unavailable source and avoid false sitemap errors. | `scripts/gsc_audit.py:51-55,140-152,418-427,542-577`; [sitemap resource][sitemaps] declares string counts. | 1 day | Additive failure data; report confidence remains a convention. |
| N5. Correct CrUX requests and missing data | Omit `formFactor` for the CLI's `ALL_FORM_FACTORS` alias; normalize missing history values to JSON null; validate existing `--periods` against 1-40, retaining default 25. Add direct request/cache/error tests. | `scripts/gsc_crux.py:90,121,179-182,194`; [CrUX API][crux-api], [history API][crux-history]. | 3 hours | Existing cached results should not mask corrected requests. |
| N6. Correct structured-data claims | Stop failing Article/Organization for recommended fields; correct Recipe/Course requirements; label retired and unchecked types without passing them. Count invalid blocks and fetch failures honestly. Keep validation explicitly limited to implemented checks. | `scripts/gsc_structured_data.py:35-64,141-171,250-279`; [Article][article], [Organization][organization], [Recipe][recipe], [Course][course], [retirements][search-updates], [HowTo][howto]. | 1 day | Verdict changes; complex contextual validation stays in Next. |
| N7. Label CTR evidence accurately | Fix position 20's mismatch with its table entry; keep numeric curve as a legacy heuristic with unverified composite provenance; remove guaranteed-extra-click/title-fix claims. CWV numbers need no change. | `scripts/gsc_benchmarks.py:9-12,43-67,112-125`; [FPS][fps], [Backlinko][backlinko], [Sistrix][sistrix], [Web Vitals][vitals]. | 2 hours | Existing numeric comparisons stay compatible except the boundary. |
| N8. Preserve domain-source results | Honor `--api-key` in comparison mode, reject silent truncation beyond 100 domains, and keep Open PageRank results when Tranco fails. Distinguish unavailable rank from outside-list rank. | `scripts/gsc_backlinks.py:71,172-218,249-257`; [OPR reference][opr-docs]. | 3 hours | Keep legacy API pending migration review below; do not silently transfer keys. |
| N9. Expose existing read data | Add PSI `--raw` so the documented Lighthouse diagnostics are actually accessible, and Search Analytics `--start-row` for one explicit page at a time. Include direct PSI HTTP/cache/error tests. | `scripts/gsc_psi.py:155-157` drops raw despite skill/agent promises; `gsc_data.py:70,98,165-189` supports offsets only in Python; [query reference][query], [PSI reference][psi-reference]. | 3 hours | Opt-in larger output; no automatic loops or inspection calls. |

## Next

| Item | What and SEO value | Evidence | Effort | Risk / reason not built now |
| --- | --- | --- | --- | --- |
| Search windows and hourly data | Explicit PT dates, `hour` + `hourly_all`, incomplete-data metadata, and paired equal-length comparisons. Useful for launches and traffic changes. | [April 2025 announcement][hourly], [query reference][query]; `gsc_data.py:37-39,85` rejects hour and always ends three days back, even with `all`. [AminForou MCP][mcp] and [Python toolkit][python-toolkit] offer flexible reporting. | 2-4 days | Date/timezone, freshness and partial-data semantics need design together; adding just an enum is misleading. |
| Migrate Open PageRank | Adopt current POST bulk API with Bearer auth, domain budgets and new output fields; explicit instructions to obtain a new OPR key. | [Current docs][opr-docs], [free plan][opr], [terms][opr-terms]. Code uses `openpagerank.com/api/v1.0/getPageRank`, `API-OPR` and the old response shape. | 1-2 days | Endpoint/auth/data-model migration. Old endpoint availability and old-key compatibility were not verified. Do not infer shutdown from a documentation redirect or forward keys to a new host. |
| Context-aware rich results | Product snippet versus merchant-listing profiles; alternative offers/review/rating rules; nested review parents, breadcrumb list items, remote-job conditions, valid field values and graph references. | [Product snippets][product], [reviews][reviews], [jobs][jobs], [breadcrumbs][breadcrumbs]; `gsc_structured_data.py:121-171` only checks presence and the first nested list member. | 4-7 days | Requires a rule model, not a growing flat mandatory-field list. N6 must explicitly disclose this remaining limitation. |
| Read transport and quota diagnostics | Explicit Google-client timeout, distinguish rate exhaustion from access denial, honor retry hints for eligible read requests, preserve source status and budget information. | `gsc_admin.py:23-25,111`, `gsc_data.py:63-65,108`, PSI/CrUX urllib wrappers; [GSC quotas][gsc-limits], [SSL guidance][ssl-api]. | 2-3 days | No blanket retry of writes or quota-heavy inspection. No persistent quota ledger: other clients share the quota. |
| Cache privacy and consistency review (partly complete) | Completed: mixed encoded redaction, atomic JSON writes, malformed-entry recovery, empty-list hits and post-write inventory invalidation. Remaining: raw audit/cache privacy and exact-target versus redacted-display contracts. | `gsc_utils.py:61-78,102-114`: cache_set itself does not scrub; only search query callers scrub; mixed literal/encoded redactions can leave encoded PII. `gsc_admin.py:29-41,67-76` misses cached empty lists and never invalidates after writes. | 2-3 days | Exact URL/cache identity and redacted display data need distinct contracts. Confirmed code gaps; real cached data deliberately not inspected. |
| Sampling and trend validity | Parse sitemap XML namespaces/entities with bounded traversal, preserve prefix semantics, report fetch coverage, handle odd date windows and omitted no-data dates. | `gsc_structured_data.py:191-227`; `gsc_audit.py:207-221`; [query reference][query] omits dates with no data. | 2-3 days | Replacing the parser and defining comparable date windows need a separate patch. No broader crawl or URL-inspection loop. |
| PSI field units and authentication | Verify CLS scaling with a current primary-source payload/contract; audit ADC quota-project headers and scope compatibility for PSI/CrUX. | `gsc_psi.py:117-120`, `_bearer_token` in both adapters sends only bearer auth; [PSI reference][psi-reference], [CrUX auth/quotas][crux-api]. | 1 day | Suspected CLS unit bug, not proved by current official reference. Third-party examples alone are insufficient. Authenticated verification excluded; leave behavior unchanged pending evidence. |
| More diagnostic CrUX metrics | Preserve histograms, LCP image subparts/resource types and RTT; label them separately from CWV pass/fail. | [CrUX releases][crux-releases], [API][crux-api]; `gsc_crux.py:136-165` drops everything except five p75 values. | 2 days | Output design and metric availability tests required. |
| Report and instruction consistency | Bring HTML/PDF to Markdown context/benchmark parity; separate data availability from SEO severity; review remaining auth behavior and confidence semantics. | `gsc_report.py:90-147,204-223`; HTML omits overview/benchmarks. `gsc_audit.py:573-575` reduces confidence for any High search finding, including real traffic decline. [Inspection reference][inspection]. | 2 days | Confidence meaning and presentation are product choices; preserve current semantics apart from explicit worker failures. |

## Later

| Item | What and SEO value | Evidence | Effort | Risk / decision |
| --- | --- | --- | --- | --- |
| Read-only MCP facade | Let more agent clients discover existing adapters without maintaining shell instructions. | [AminForou MCP][mcp], [AkashRajpurohit MCP][mcp-compare]; this repo exposes scripts and Claude-specific skills. | 1 week | Changes distribution/auth lifecycle. Proposal only; scripts must stay authoritative. |
| Bounded export and local history | Optional pagination/export with explicit caps, weighted aggregate comparisons and provenance. Useful for repeatable SEO reporting beyond top rows. | [query limits][query], [Python toolkit][python-toolkit], [better-search-console][better-mcp]. | 1 week | Storage/privacy and export completeness; GSC does not guarantee every row even with pagination. |
| Property-specific CTR reference | Compare similar device/country/brand/query cohorts using the user's own data, with uncertainty and a minimum sample. | Published [FPS][fps], [Backlinko][backlinko], [Sistrix][sistrix] estimates differ; `gsc_benchmarks.py` has one universal table. | 1 week | A statistical feature needs validation and sufficient data; no new universal curve invented here. |
| Cross-product analysis | Join GSC with GA4 only through a separately designed read-only integration. | [Google SEO MCP project][cross-product] documents GSC/GA4 diagnostics. | 2+ weeks | New scopes, joins, attribution caveats and project shape. Not part of this toolkit pass. |

### Considered and rejected

- Bulk URL inspection, even competitors' ten-URL batches: rejected by owner
  constraint and [property quota][gsc-limits]. Keep one explicit URL per call.
- Indexing API writes, automatic sitemap changes or `--yes`: outside the
  allowed write surfaces or confirmation policy. No new writes.
- Paid backlink APIs, proprietary data snapshots and a Common Crawl link
  warehouse: paid data is excluded; WAT processing is beyond a small local
  adapter. Domain popularity must not be sold as a backlink inventory.
- Replacing the legacy CTR curve with the latest publisher's table: studies
  have incompatible samples and SERP definitions. Use provenance and caveats
  now, cohort-based calibration later.
- Automatic short-interval retries against overloaded SSL Labs: its
  [guidance][ssl-api] recommends delays much longer than a CLI's budget.
  Return an actionable error and retry hint rather than wait 15-30 minutes.
- Treating missing JSON-LD, unknown types or a security-header grade as proof
  of ranking loss: [Google's page-experience guidance][page-experience] and
  the limited local parser do not support that conclusion.

## Upstream review — initial 2026-09-30 evidence

Current implementation and the 2026-10-01 OPR migration clarification are
recorded above. This section preserves the initial comparison.

### Google APIs

- Search Console discovery `searchconsole/v1` remains appropriate. The
  Search Analytics REST path retains `webmasters/v3`. Existing six search
  types and six dimensions match the [reference][query]; `hour` and
  `hourly_all` are missing locally. No documented AI Overview/AI Mode
  dimension was found in that reference. `type` correctly replaces the
  deprecated `searchType` parameter.
- [GSC quotas][gsc-limits]: Search Analytics 1,200 QPM per site/user,
  40,000 QPM and 30 million QPD per project, plus 10-minute/daily load
  limits. URL Inspection 2,000 QPD/600 QPM per property and 10 million
  QPD/15,000 QPM per project. Other resources: 20 QPS/200 QPM per user,
  100 million QPD per project. Inspection is cached for 15 minutes, has
  no retry/bulk loop, and the audit deliberately uses a stub. There is no
  global quota accounting. Mobile usability is [deprecated][inspection].
- PSI v5 and four requested Lighthouse categories remain current. The
  latest entry retrieved in [PSI release notes][psi-releases] is Lighthouse
  13 (2025-10-20); PWA was removed in Lighthouse 12 and is not requested
  here. `INTERACTION_TO_NEXT_PAINT` is the correct non-experimental name.
  Google [plans to remove embedded CrUX data][psi-start], with no date in
  that page. Missing field data already yields an empty metric set locally.
  The local 60-second timeout is shorter than PSI's documented 120-second
  service maximum; this is a policy choice to revisit, not proof of a bug.
  A current universal numerical PSI quota could not be established from
  official public docs; check the actual quota project's console.
- CrUX v1 endpoints and the five metric names requested locally match the
  [reference][crux-api]. Aggregate form factor is represented by omission.
  [History][crux-history] accepts 1-40 weekly periods, default 25, each
  covering an overlapping 28-day window. Both APIs have a 150 QPM/project
  limit; history and snapshot quotas are separate. New LCP subparts,
  resource types and RTT are not exposed locally. The latest retrieved
  [release][crux-releases] is August 2026, published September 8, 2026;
  the retired CrUX Dashboard is separate from these APIs.

### External services and terms

| Source | Endpoint / contract | Use conditions and verification limits |
| --- | --- | --- |
| Tranco | The [site][tranco] still advertises `https://tranco-list.eu/top-1m.csv.zip`; daily list, locally refreshed weekly. Alexa is no longer an input. | Public download documented. Provider attributions include CC BY, CC BY-SA and Cloudflare CC BY-NC; do not describe this as unrestricted commercial data or relicense downloaded lists as MIT. Commercial redistribution permission is unresolved. No list was downloaded or vendored. |
| Open PageRank | Old documentation redirects to [new docs][opr-docs]: POST `https://openpagerank.keywordseverywhere.com/v1/domains/bulk`, Bearer OPR key, up to 100 domains. Code still calls legacy GET. | [Free plan][opr]: 30,000 domains/month; docs show 60 requests/minute and budget headers. [Terms][opr-terms] allow service use within plan limits; scores are proprietary and informational. New authenticated API and old endpoint compatibility not tested. |
| Mozilla Observatory | [Official FAQ][observatory] documents POST `https://observatory-api.mdn.mozilla.net/api/v2/scan`, not `/analyze`; response is synchronous, scan cooldown 60 seconds. Old service retired October 2024. | [Upstream][observatory-code] explicitly offers API integration. [Mozilla terms][mozilla-terms] apply; scan histories are public. No blanket commercial SLA inferred and no scan triggered. |
| SSL Labs | [v3 reference][ssl-api] still documents `https://api.ssllabs.com/api/v3/analyze`; no evidence this URL is retired. v4 is a separate migration, not necessary merely because it exists. | [Terms][ssl-terms] permit noncommercial OSS integration subject to notices and owner authorization; commercial/public-site use requires permission. Baseline code omitted the info-call messages required by those terms; N3 adds them. No assessment triggered; live v3 availability could not be verified with the web tool. |

### Benchmarks and structured data

- [Core Web Vitals][vitals]: LCP 2,500/4,000 ms, INP 200/500 ms,
  CLS 0.10/0.25 remain current. [FCP][fcp] 1,800/3,000 ms and
  [TTFB][ttfb] 800/1,800 ms are useful diagnostics, not Core Web Vitals.
- The bundled position-1 value is 39.5%. [Backlinko][backlinko] publishes
  27.6%; [Sistrix][sistrix] documents major SERP-layout variation; the
  current [FPS][fps] page distinguishes AI and non-AI layouts. No weighting,
  reproducible source snapshot or derivation supports the claimed 2024
  composite, especially positions 11-20. Keep it labeled as a heuristic.
- Article/NewsArticle/BlogPosting and Organization have no required
  properties in their linked Google docs. Recipe requires name/image;
  ingredients/instructions are recommended. Course list remains supported
  (name/description required, provider recommended); retired Course Info is
  a different feature. HowTo and FAQPage must not pass as supported rich
  results. Question belongs in a QAPage/parent context, not a universal rule.
- Event's name/startDate/location, LocalBusiness's name/address and
  VideoObject's name/thumbnailUrl/uploadDate match the top-level minimums
  in [Event][event], [LocalBusiness][local-business] and [Video][video].
  Breadcrumb requires nested list items, not merely a nonempty list.
  Review needs nested rating/author/item context; AggregateRating permits
  ratingCount OR reviewCount. JobPosting's location rule has remote-job
  exceptions. Product requires a profile-specific set, including alternatives.
  These limitations require explicit reporting until the contextual rules ship.
- [Search updates][search-updates] include FAQ retirement (May 2026) and
  VideoObject creator/interactionStatistic additions (September 24, 2026).
  The [2025 retirement notice][retired-2025] includes Course Info,
  ClaimReview, Estimated Salary, Learning Video, Special Announcement and
  Vehicle Listing. Most were never in the local table; do not confuse them
  with general Course or VideoObject support.

### Instruction drift and open questions

AGENTS.md is the shared guide; CLAUDE.md and GEMINI.md deliberately refer
to it rather than duplicate it. Keep all three and update them together
when CLI behavior changes. Confirmed drift: README's prompt warning;
PSI skill/agent promised raw CLI data which was dropped; SETUP calls `/gsc
audit` LLM-driven despite the skill invoking the deterministic script;
the router omits site CRUD from its routing table; the overview agent says
HEAD while the script uses GET; audit docs say a missing property hard-fails
but code continues with a Critical finding. `hooks/hooks.json` is empty,
so hooks do not enforce any safety promise. These docs were corrected with the matching changes. Inspection guidance
also now distinguishes response fields, marks mobile usability deprecated,
and avoids claiming the API performs live-URL tests; see the
[inspect method][inspect-method]. SECURITY.md now describes actual cache
scrubbing limits instead of promising universal anonymization. Per-skill version metadata is historical, not the package
version; no version bump in this pass.

Open questions left unchanged: should missing-property audits stop or retain
public checks; should prefix properties sample `/sitemap.xml` under their path or the host
root; should security checks run for commercially operated client audits
under separately obtained SSL Labs permission? No assumption of permission
for a particular downstream deployment is made.

[query]: https://developers.google.com/webmaster-tools/v1/searchanalytics/query
[hourly]: https://developers.google.com/search/blog/2025/04/san-hourly-data
[gsc-limits]: https://developers.google.com/webmaster-tools/limits
[sitemaps]: https://developers.google.com/webmaster-tools/v1/sitemaps
[inspection]: https://developers.google.com/webmaster-tools/v1/urlInspection.index/UrlInspectionResult
[psi-reference]: https://developers.google.com/speed/docs/insights/rest/v5/pagespeedapi/runpagespeed
[psi-releases]: https://developers.google.com/speed/docs/insights/release_notes
[psi-start]: https://developers.google.com/speed/docs/insights/v5/get-started
[crux-api]: https://developer.chrome.com/docs/crux/api
[crux-history]: https://developer.chrome.com/docs/crux/history-api
[crux-releases]: https://developer.chrome.com/docs/crux/release-notes
[tranco]: https://tranco-list.eu/
[opr]: https://openpagerank.keywordseverywhere.com/
[opr-docs]: https://openpagerank.keywordseverywhere.com/docs
[opr-terms]: https://openpagerank.keywordseverywhere.com/terms
[observatory]: https://developer.mozilla.org/en-US/observatory/docs/faq
[observatory-code]: https://github.com/mdn/mdn-http-observatory#json-api
[mozilla-terms]: https://www.mozilla.org/en-US/about/legal/terms/mozilla/
[ssl-api]: https://github.com/ssllabs/ssllabs-scan/blob/master/ssllabs-api-docs-v3.md
[ssl-terms]: https://www.ssllabs.com/downloads/Qualys_SSL_Labs_Terms_of_Use.pdf
[vitals]: https://web.dev/articles/vitals
[fcp]: https://web.dev/articles/fcp
[ttfb]: https://web.dev/articles/ttfb
[fps]: https://firstpagesage.com/reports/google-click-through-rates-ctrs-by-ranking-position/
[backlinko]: https://backlinko.com/google-ctr-stats
[sistrix]: https://www.sistrix.com/blog/why-almost-everything-you-knew-about-google-ctr-is-no-longer-valid/
[article]: https://developers.google.com/search/docs/appearance/structured-data/article
[organization]: https://developers.google.com/search/docs/appearance/structured-data/organization
[recipe]: https://developers.google.com/search/docs/appearance/structured-data/recipe
[course]: https://developers.google.com/search/docs/appearance/structured-data/course
[product]: https://developers.google.com/search/docs/appearance/structured-data/product-snippet
[reviews]: https://developers.google.com/search/docs/appearance/structured-data/review-snippet
[jobs]: https://developers.google.com/search/docs/appearance/structured-data/job-posting
[breadcrumbs]: https://developers.google.com/search/docs/appearance/structured-data/breadcrumb
[event]: https://developers.google.com/search/docs/appearance/structured-data/event
[local-business]: https://developers.google.com/search/docs/appearance/structured-data/local-business
[video]: https://developers.google.com/search/docs/appearance/structured-data/video
[search-updates]: https://developers.google.com/search/updates
[howto]: https://developers.google.com/search/blog/2023/08/howto-faq-changes
[retired-2025]: https://developers.google.com/search/blog/2025/06/simplifying-search-results
[page-experience]: https://developers.google.com/search/docs/appearance/page-experience
[mcp]: https://github.com/AminForou/mcp-gsc
[mcp-compare]: https://github.com/AkashRajpurohit/gsc-mcp
[python-toolkit]: https://github.com/joshcarty/google-searchconsole
[better-mcp]: https://github.com/houtini-ai/better-search-console
[cross-product]: https://github.com/mario-hernandez/google-seo-mcp-claude-code

[inspect-method]: https://developers.google.com/webmaster-tools/v1/urlInspection.index/inspect

## Initial pass completion record

All Now items were implemented in the initial pass. No Next or Later
project-shape proposals were built in that pass. The implementation commits are listed in [verification](VERIFICATION.md).

| Item | Implementation commits |
| --- | --- |
| N1 | `852406b` |
| N2 | `b13e7fc` |
| N3 | `07dba00`, `39b9952` |
| N4 | `7da3a6d`, `9d18d4a`, `653597c`, review correction `cbda76c` |
| N5 | `e1196c6` |
| N6 | `310bc05` |
| N7 | `0b88860` |
| N8 | `1330183`, `bf60e33` |
| N9 | `240cb2a`, `cd2132b` |
| Remaining documentation drift | `7707936` |

Initial pass final checks: Ruff passed; 265 mocked tests passed; version consistency,
sdist/wheel build and `twine check` passed. All commits were preceded by these
checks. This is a Windows/Python 3.12 result, not an Ubuntu matrix result.
Version remains 0.2.2. No push, PR, tag or publication was performed.

Remaining verification limits: legacy Open PageRank availability and key
compatibility; live v3 SSL Labs availability and assessment behavior; actual
project quota balances and Google auth scope/quota attribution; PSI CLS field
units; original CTR composite provenance; and commercial redistribution of
Tranco inputs. Published terms were reviewed, but permission for any particular
commercial deployment was not established. External scans and authenticated
queries were not exercised, and credentials were not accessed.

## Follow-up implementation — cache work

The owner's follow-up authorizes continued roadmap work on `roadmap-work`.
Start with the confirmed cache bugs before additional features; the starting
suite passes 265 mocked tests. All original write, quota, credential and
local-commit constraints continue to apply.

- Mixed literal/encoded redaction: implemented, including repair of accessed
  Search Analytics cache hits without an API call. Regression tests reproduced
  four mixed-string leaks and the cached-result leak before the fix.
- Atomic JSON cache writes and malformed-entry recovery: implemented with
  interrupted-write and replacement-failure regression tests. Permission
  failures remain errors; the separate Tranco CSV cache is not covered.
- Empty-list hits and targeted inventory invalidation after confirmed
  successful writes: implemented. Cancelled/failed calls retain caches;
  invalidation errors return a warning without repeating a successful write.
  Cross-process reads already in flight remain outside this cache contract.
- Broad raw-payload privacy and exact-target/display-data separation remain
  design work. No universal anonymization or historical cache purge is claimed.

Cache follow-up commits:

| Commit | Completed task |
| --- | --- |
| `7639a4b` | Redact mixed identifiers and repair accessed Search Analytics cache entries |
| `08bc3fc` | Replace JSON cache entries atomically and recover malformed reads |
| `c724f1f` | Reuse empty inventories and invalidate related caches after confirmed successful writes |

Validation: 265 tests at the start, 296 at completion; Ruff, version
consistency, sdist/wheel build, Twine and whitespace checks passed before
each commit on Windows/Python 3.12. Tests reproduced the defects before fixes.
No credentials, existing user cache data, live APIs or remote writes were used.
The full CI platform matrix remains unverified locally.

This completes the bounded cache bugfix batch. Raw-payload privacy, historical
cache cleanup, Tranco CSV write consistency and coordination with concurrent
in-flight reads remain open. Other Next and Later tasks retain their stated
scope and risks; no new project-shape feature was introduced.
