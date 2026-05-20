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

For every write (submit / delete), the agent must:

1. Print the resolved sitemap URL
2. Ask `apply? [y/N]`
3. On `y`: run the script
4. On `n`: skip

## What to flag in audits

- **Zero sitemaps registered** → High finding. Even small sites
  benefit; sitemaps are the cheapest discovery signal you can give
  Google.
- **Errors > 0** → High. Open the sitemap in the Search Console UI
  for the failing URLs.
- **Warnings > 0** → Medium. Usually duplicates or non-indexable
  entries — worth a review but rarely urgent.
- **`lastSubmitted` older than 90 days for a dynamic site** → Medium.
  Resubmit so Google re-crawls.

## Caveats

The submit endpoint only takes the sitemap URL — it does not push
sitemap content. Make sure your CDN actually serves a 200 response
for the sitemap URL before submitting; the API does not validate it
for you.
