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
  `OPENPAGERANK_API_KEY` env var only — never persisted on disk

The toolkit never logs credentials to stdout, never sends them to a
third party, and never bakes them into report files. Cached API
responses under `~/.claude/gsc-cache/` are scrubbed of PII (emails,
phone numbers, ID-like keys) before being written.

## Disclosure timeline

I aim to acknowledge security reports within 7 days and ship a fix or
mitigation within 30 days. For high-severity issues affecting active
users, both windows shrink.
