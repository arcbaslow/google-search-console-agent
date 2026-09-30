"""
Structured-data adapter.

Parses JSON-LD blocks from a page (or a sample of pages from the
sitemap) and checks a limited set of top-level fields. This is not a
replacement for Google's Rich Results Test: nested, contextual and content
eligibility requirements are not fully evaluated. No URL Inspection quota
is used.

GSC's URL Inspection API exposes rich-results status one URL at a time
(quota-heavy). This adapter complements it by giving you a sitemap-wide
audit of JSON-LD presence and supported field checks. A passing local
check never guarantees eligibility or appearance in Google Search.

CLI:
  python scripts/gsc_structured_data.py --url https://example.com/products/foo --json
  python scripts/gsc_structured_data.py --site sc-domain:example.com --sample 25 --json
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import urllib.error
import urllib.request
from typing import Any

FETCH_TIMEOUT_S = 15
USER_AGENT = "google-search-console-agent/0.2 (+structured-data)"

# Limited top-level requirements, reviewed against Google docs on 2026-09-30.
# This is not a complete eligibility model; see CONTEXTUAL_TYPES and docs/ROADMAP.md.
REQUIRED_FIELDS: dict[str, list[str]] = {
    "Product": ["name"],
    "Article": [],
    "NewsArticle": [],
    "BlogPosting": [],
    "Recipe": ["name", "image"],
    "Event": ["name", "startDate", "location"],
    "BreadcrumbList": ["itemListElement"],
    "Organization": [],
    "LocalBusiness": ["name", "address"],
    "VideoObject": ["name", "thumbnailUrl", "uploadDate"],
    "Course": ["name", "description"],
    "JobPosting": ["title", "description", "hiringOrganization", "datePosted"],
    "Review": ["author", "reviewRating"],
    "AggregateRating": ["ratingValue"],
}

# Recommended fields for manual review, not eligibility guarantees.
RECOMMENDED_FIELDS: dict[str, list[str]] = {
    "Product": ["description", "brand", "offers", "aggregateRating", "review"],
    "Article": ["headline", "image", "datePublished", "author", "dateModified"],
    "NewsArticle": ["headline", "image", "datePublished", "author", "dateModified"],
    "BlogPosting": ["headline", "image", "datePublished", "author", "dateModified"],
    "Recipe": ["recipeIngredient", "recipeInstructions", "nutrition", "totalTime", "recipeYield"],
    "Organization": ["name", "url", "logo"],
    "Course": ["provider"],
    "Event": ["endDate", "offers"],
    "JobPosting": ["baseSalary", "employmentType", "validThrough"],
}


# These types have retired Google rich results, not retired Schema.org syntax.
RETIRED_TYPES = {"FAQPage", "HowTo"}
# Top-level presence alone cannot establish a useful complete verdict here.
CONTEXTUAL_TYPES = {"Product", "JobPosting", "Review", "AggregateRating", "BreadcrumbList", "Course"}


def _fetch_html(url: str) -> str | None:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml",
    })
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
            return resp.read(1_500_000).decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, ConnectionError):
        return None


def extract_jsonld(html: str) -> list[dict[str, Any]]:
    """Pull every parseable JSON-LD block out of an HTML page."""
    blocks: list[dict[str, Any]] = []
    for m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.I | re.S,
    ):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            blocks.append({"_error": "invalid_json", "_raw": raw[:200]})
            continue
        if isinstance(parsed, list):
            for x in parsed:
                if isinstance(x, dict):
                    blocks.append(x)
        elif isinstance(parsed, dict):
            graph = parsed.get("@graph")
            if isinstance(graph, list):
                for x in graph:
                    if isinstance(x, dict):
                        blocks.append(x)
            else:
                blocks.append(parsed)
    return blocks


def _types_of(block: dict[str, Any]) -> list[str]:
    t = block.get("@type")
    if isinstance(t, str):
        return [t]
    if isinstance(t, list):
        return [x for x in t if isinstance(x, str)]
    return []


def _has_field(block: dict[str, Any], field: str) -> bool:
    """Treat empty strings, empty lists, and None as missing."""
    if "." in field:
        head, _, rest = field.partition(".")
        sub = block.get(head)
        if isinstance(sub, dict):
            return _has_field(sub, rest)
        if isinstance(sub, list) and sub and isinstance(sub[0], dict):
            return _has_field(sub[0], rest)
        return False
    v = block.get(field)
    if v is None:
        return False
    if isinstance(v, str) and not v.strip():
        return False
    if isinstance(v, (list, dict)) and not v:
        return False
    return True


def validate_block(block: dict[str, Any]) -> dict[str, Any]:
    """Validate one JSON-LD block. Returns {types, missing_required,
    missing_recommended, verdict}."""
    if "_error" in block:
        return {"types": [], "verdict": "invalid", "error": block["_error"]}
    types = _types_of(block)
    missing_required: list[str] = []
    missing_recommended: list[str] = []
    for t in types:
        for f in REQUIRED_FIELDS.get(t, []):
            if not _has_field(block, f):
                missing_required.append(f"{t}.{f}")
        for f in RECOMMENDED_FIELDS.get(t, []):
            if not _has_field(block, f):
                missing_recommended.append(f"{t}.{f}")
    unchecked = [t for t in types if t not in REQUIRED_FIELDS and t not in RETIRED_TYPES]
    retired = [t for t in types if t in RETIRED_TYPES]
    if types and len(retired) == len(types):
        verdict = "unsupported"
    elif missing_required:
        verdict = "fail"
    elif unchecked or retired or any(t in CONTEXTUAL_TYPES for t in types):
        verdict = "unchecked"
    elif missing_recommended:
        verdict = "partial"
    elif types:
        verdict = "pass"
    else:
        verdict = "untyped"
    return {
        "types": types,
        "verdict": verdict,
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
        "validation_scope": "top_level_presence_only",
        "unchecked_types": unchecked + [t for t in types if t in CONTEXTUAL_TYPES],
        "retired_types": retired,
    }


def analyze_url(url: str) -> dict[str, Any]:
    """Fetch + extract + validate. Returns a structured per-block report."""
    html = _fetch_html(url)
    if html is None:
        return {"url": url, "error": "fetch_failed"}
    blocks = extract_jsonld(html)
    validations = [validate_block(b) for b in blocks]
    summary = {
        "url": url,
        "block_count": len(blocks),
        "types_found": sorted({t for v in validations for t in v.get("types", [])}),
        "verdicts": _count_verdicts(validations),
        "blocks": validations,
    }
    return summary


def _count_verdicts(validations: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in validations:
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
    return counts


# ---------- Sitemap-wide sample ----------

def _fetch_sitemap_urls(site_url: str, limit: int) -> list[str]:
    """Pull a sample of URLs from the site's sitemap.xml. The function
    follows sitemap-index files once. Returns at most `limit` URLs."""
    from gsc_utils import normalize_site_url

    site_url = normalize_site_url(site_url)
    if site_url.startswith("sc-domain:"):
        origin = "https://" + site_url[len("sc-domain:"):].rstrip("/")
    else:
        origin = site_url.rstrip("/")
    candidates = [origin + "/sitemap.xml", origin + "/sitemap_index.xml"]
    urls: list[str] = []
    for sm in candidates:
        text = _fetch_text(sm)
        if not text:
            continue
        if "<sitemapindex" in text.lower():
            inner = re.findall(r"<loc>\s*(.*?)\s*</loc>", text, re.I | re.S)
            for child in inner[:5]:  # follow at most 5 child sitemaps
                child_text = _fetch_text(child.strip())
                if child_text:
                    urls.extend(re.findall(r"<loc>\s*(.*?)\s*</loc>", child_text, re.I | re.S))
        else:
            urls.extend(re.findall(r"<loc>\s*(.*?)\s*</loc>", text, re.I | re.S))
        if urls:
            break
    if not urls:
        return []
    random.shuffle(urls)
    return urls[:limit]


def _fetch_text(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
            return resp.read(2_000_000).decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, ConnectionError):
        return None


def analyze_sitemap_sample(site_url: str, sample_size: int = 20) -> dict[str, Any]:
    urls = _fetch_sitemap_urls(site_url, sample_size)
    if not urls:
        return {"site_url": site_url, "error": "no_sitemap_urls"}
    per_url = [analyze_url(u) for u in urls]
    rollup = _rollup(per_url)
    return {
        "site_url": site_url,
        "sample_size": len(urls),
        "rollup": rollup,
        "per_url": per_url,
    }


def _rollup(per_url: list[dict[str, Any]]) -> dict[str, Any]:
    fetch_failures = sum(1 for x in per_url if x.get("error"))
    has_any = sum(1 for x in per_url if x.get("block_count", 0) > 0)
    verdict_counts = dict.fromkeys(
        ("pass", "partial", "fail", "untyped", "invalid", "unchecked", "unsupported"), 0)
    type_counts: dict[str, int] = {}
    missing_required_top: dict[str, int] = {}
    for entry in per_url:
        for t in entry.get("types_found") or []:
            type_counts[t] = type_counts.get(t, 0) + 1
        for b in entry.get("blocks") or []:
            v = b.get("verdict")
            if v in verdict_counts:
                verdict_counts[v] += 1
            for missing in b.get("missing_required") or []:
                missing_required_top[missing] = missing_required_top.get(missing, 0) + 1
    return {
        "urls_analyzed": len(per_url) - fetch_failures,
        "urls_attempted": len(per_url),
        "urls_with_jsonld": has_any,
        "fetch_failures": fetch_failures,
        "block_verdicts": verdict_counts,
        "type_counts": dict(sorted(type_counts.items(), key=lambda kv: -kv[1])),
        "top_missing_required": dict(sorted(missing_required_top.items(),
                                            key=lambda kv: -kv[1])[:10]),
    }


# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(description="Structured-data adapter (JSON-LD)")
    parser.add_argument("--url", help="Single-URL analysis")
    parser.add_argument("--site", help="Sample URLs from this site's sitemap")
    parser.add_argument("--sample", type=int, default=20,
                        help="Sample size for --site (default 20)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        if args.url:
            out = analyze_url(args.url)
        elif args.site:
            out = analyze_sitemap_sample(args.site, sample_size=args.sample)
        else:
            parser.print_help()
            return 1
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
