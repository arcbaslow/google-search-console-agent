---
name: gsc-page-experience
description: "Security and TLS posture of a site. Mozilla Observatory grade (A+ to F based on security headers + cookie / CSP rules), SSL Labs grade (A+ to F TLS configuration), and a local header probe (HSTS, CSP, X-Content-Type, X-Frame-Options, Referrer-Policy, Permissions-Policy). Page experience signals affect ranking and they are not surfaced by GSC's API."
user-invokable: true
argument-hint: "<host> [--headers|--observatory|--ssl]"
license: MIT
metadata:
  author: arcbaslow
  version: "0.2.0"
  category: gsc
---

# GSC: Page Experience

Three free signals — none needing an API key.

- **Local header probe** — single HTTPS HEAD against the homepage.
  Grades presence of HSTS, CSP, X-Content-Type-Options, X-Frame-
  Options, Referrer-Policy, Permissions-Policy. Fast.
- **Mozilla HTTP Observatory** — broader header / cookie / CSP rule
  set, returns a letter grade. Asynchronous: polls up to ~30 s.
- **SSL Labs** — full TLS audit: protocol versions, cipher suites,
  certificate chain, known-vulnerability checks. Asynchronous: polls
  up to ~120 s. Uses cached results when available.

## Direct commands

| Intent | Command |
|--------|---------|
| Everything | `python scripts/gsc_page_experience.py --host example.com --json` |
| Headers only (fast) | `python scripts/gsc_page_experience.py --host example.com --headers --json` |
| Observatory only | `python scripts/gsc_page_experience.py --host example.com --observatory --json` |
| SSL Labs only | `python scripts/gsc_page_experience.py --host example.com --ssl --json` |

## What's checked

- **TLS quality**: protocol versions enabled (TLS 1.0 / 1.1 should be
  disabled), cipher suites, certificate chain completeness, OCSP
  stapling, known-vulnerability exposure (Heartbleed, POODLE, etc.).
- **Header hygiene**: HSTS (`max-age` ≥ 31536000 with `includeSubDomains`
  is the de facto safe baseline), CSP (any policy beats none), X-
  Content-Type-Options: nosniff, X-Frame-Options or `frame-ancestors`
  in CSP, Referrer-Policy, Permissions-Policy.

## When to flag what

| Signal | Severity if poor |
|--------|------------------|
| SSL Labs grade T / M / F (untrusted, mismatched, fail) | Critical |
| SSL Labs grade D / E | High |
| SSL Labs grade B / C | Medium |
| Observatory grade D / E / F | High |
| Observatory grade B / C | Medium |
| Local header coverage < 50% | High |
| Local header coverage 50-85% | Medium |

## When to call

- Before any SEO push — Google has confirmed HTTPS quality and core
  security signals influence ranking even when CWV is fine.
- After a migration — TLS configs drift on platform changes.
- After a CDN swap — header policies often reset to provider defaults.

## Caveats

- SSL Labs scans take 60-120 s on fresh hosts. Cached results return
  instantly; we use them when available.
- Mozilla Observatory's API has rebranded (mdn-observatory). If the
  default URL stops working, the script reports a clean HTTP error
  rather than blowing up.
- Local header probe uses HEAD; some hosts disallow HEAD and the
  script falls back to a small GET.

## After analysis

Offer:

- "Want to wire this into the full audit? Use `/gsc audit <site>
  --with-page-experience`."
