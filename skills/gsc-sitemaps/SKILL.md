---
name: gsc-sitemaps
description: "List, submit, or delete sitemaps on a Search Console property. List is read-only; submit and delete require the webmasters scope. Use when user says 'sitemap', 'submit a sitemap', 'sitemap errors'."
user-invokable: true
argument-hint: "<site> [list|submit <feedpath>|delete <feedpath>|get <feedpath>]"
license: MIT
metadata:
  author: arcbaslow
  version: "0.1.0"
  category: gsc
---

# GSC: Sitemaps

GSC tracks every registered sitemap's last submission time, last
download time, indexed-URL counts, and error / warning counts.

## Direct commands

| Intent | Command |
|--------|---------|
| List all sitemaps | `python scripts/gsc_admin.py --site X --list-sitemaps --json` |
| Get one sitemap | `python scripts/gsc_admin.py --site X --get-sitemap --feedpath https://X/sitemap.xml --json` |
| Submit a sitemap | `python scripts/gsc_admin.py --site X --submit-sitemap --feedpath https://X/sitemap.xml --json` |
| Delete a sitemap | `python scripts/gsc_admin.py --site X --delete-sitemap --feedpath https://X/sitemap.xml --json` |

## Confirmation flow

For sitemap submit/delete and site add/delete, invoke the adapter interactively.
It prints the resolved property and absolute sitemap URL to stderr and asks
`Apply? [y/N]` before auth or API access. Let the user answer; never supply an
automatic `y`. Refusal, EOF or interruption returns `status: cancelled`.
There is no bypass flag. Repeat this flow separately for every write.

Site commands use `--site X --add-site` or `--site X --delete-site`.

## What to flag in audits

- **Zero sitemaps registered** → High finding. Even small sites
  benefit; sitemaps are the cheapest discovery signal you can give
  Google.
- **Errors > 0** → High. Open the sitemap in the Search Console UI
  for the failing URLs.
- **Warnings > 0** → Medium. Usually duplicates or non-indexable
  entries - worth a review but rarely urgent.
- **`lastSubmitted` older than 90 days for a dynamic site** → Medium.
  Resubmit so Google re-crawls.

## Caveats

The submit endpoint only takes the sitemap URL - it does not push
sitemap content. Make sure your CDN actually serves a 200 response
for the sitemap URL before submitting; the API does not validate it
for you.

Sitemap error and warning counts are compared numerically, including Google API string values such as `"0"`; a zero count does not produce a finding.

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
