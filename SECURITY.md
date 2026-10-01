# Security policy

## Reporting a vulnerability

Open a private security advisory on the repo:
https://github.com/arcbaslow/google-search-console-agent/security/advisories/new

Please do not file public issues for security problems.

## What's in scope

- Credential handling in `scripts/gsc_auth.py` and any path that touches
  `~/.claude/gsc-credentials.json` or gcloud ADC files
- PII handling in `scripts/gsc_utils.py` (the `scrub_pii` denylist +
  regex pass) — relevant because search-query data can contain
  user-entered PII
- Any code path that sends user data to a third-party endpoint
  (Mozilla Observatory, SSL Labs, Open PageRank, Tranco — all
  documented in their respective adapters)
- Any command that performs a write (sitemap submit/delete, site
  add/delete) without an explicit confirmation prompt
- Dependency-chain vulnerabilities in the Google client libraries
  pinned in `scripts/requirements.txt`

## What's out of scope

- Misuse of the toolkit against a property you do not own
- Bugs in the upstream Google / Mozilla / SSL Labs / Open PageRank
  APIs themselves — report those to the respective vendors
- Issues that require an attacker with shell access to the user's
  machine (they already own `~/.claude/`)

## Where credentials live on disk

- gcloud ADC (default path):
  `~/.config/gcloud/application_default_credentials.json`
- Legacy OAuth (fallback path):
  `~/.claude/gsc-credentials.json` (file mode `0600` on POSIX)
- Service account / external account:
  `GOOGLE_APPLICATION_CREDENTIALS` env var
- Open PageRank API key:
  `OPENPAGERANK_V1_API_KEY` env var or explicit `--api-key` — never persisted on disk

Google credentials are used by the Google adapters. The optional Open
PageRank key is intentionally sent to its configured API endpoint; it is
not a Google credential. Do not include tokens or keys in reports.

Search Analytics applies the best-effort `scrub_pii` filter before caching.
The shared cache writer does not scrub payloads itself. URL Inspection,
PSI (including raw diagnostics), CrUX and admin responses can contain URLs
or other identifying data. The regex/denylist filter is not comprehensive
anonymization. Mixed literal and percent-encoded email/phone identifiers are
redacted together; Search Analytics cache hits are rechecked and repaired on
access. This does not sweep old cache files or cover arbitrary encodings.
Treat caches under `~/.claude/gsc-cache/` and raw reports as private data.
See docs/ROADMAP.md for the pending cache privacy and consistency work.

## Disclosure timeline

I aim to acknowledge security reports within 7 days and ship a fix or
mitigation within 30 days. For high-severity issues affecting active
users, both windows shrink.

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
