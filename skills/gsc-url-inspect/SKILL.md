---
name: gsc-url-inspect
description: "Per-URL inspection via GSC's URL Inspection API. Indexing state, last crawl, mobile usability, rich results coverage, page fetch state, canonical resolution. Quota-heavy — one URL per call. Use when user says 'is this URL indexed', 'why isn't this page indexed', 'rich results status'."
user-invokable: true
argument-hint: "<site> <url> [--lang en-US]"
license: MIT
metadata:
  author: arcbaslow
  version: "0.1.0"
  category: gsc
---

# GSC: URL Inspection

`urlInspection.index.inspect` is the API equivalent of pasting a URL
into Search Console's URL Inspection tool. It returns:

- **Coverage** — index state (e.g. `INDEXING_ALLOWED`,
  `BLOCKED_BY_ROBOTS_TXT`, `BLOCKED_BY_NOINDEX`)
- **Crawl** — last crawl time, page fetch state, robots.txt state
- **Indexability** — verdict (`PASS`, `FAIL`, `NEUTRAL`)
- **Canonical** — user-declared vs Google-selected canonical
- **Rich results** — declared structured-data types and their per-item verdicts
- **Mobile usability** — verdict + issues
- **AMP** — declared and indexed AMP URL state (legacy)

## Direct command

```
python scripts/gsc_admin.py --site X --url https://X/foo --inspect --json
python scripts/gsc_admin.py --site X --url https://X/foo --lang en-US --inspect --json
```

The URL must belong to the property you pass (matching the property
prefix or domain).

## Quota note

URL Inspection counts heavily against the GSC API quota — 2,000
inspections per day, 600 per minute per property. The audit driver
deliberately omits URL inspection. Use this skill for targeted
diagnostics, not bulk scans.

## When to call

- A specific URL isn't ranking and you want to know why
- A new page launched and you need to confirm Google has crawled it
- Rich results disappeared and you want the per-item verdicts
- Mobile usability dropped and you want the specific issue list

## After analysis

Offer:

- "Want a Lighthouse pass for the same URL? Use `/gsc pagespeed <url>`."
- "Want the origin-level CWV trend? Use `/gsc cwv <site>`."
