## What this changes

<!-- One sentence on what changed and why. -->

## How to verify

<!--
ruff check scripts/
pytest scripts/ -q

Add manual smoke-test steps if relevant.
-->

## Checklist

- [ ] `ruff check scripts/` clean
- [ ] `pytest scripts/ -q` passes
- [ ] No new external API calls in tests
- [ ] No credentials, tokens, or PII in committed files
- [ ] CHANGELOG.md updated if this is user-visible
- [ ] Docs updated if the user-facing surface changed
