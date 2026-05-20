"""
PageSpeed Insights wrapper.

PSI returns a Lighthouse audit for a single URL plus the field-measured
Core Web Vitals (LCP, INP, CLS, FCP, TTFB) if CrUX has enough data for
that URL. It is the right tool for per-page deep inspection; for
origin-level CWV history use `gsc_crux.py` instead.

Authentication: the GA-ADC bearer token works directly. No API key is
required.

CLI:
  python scripts/gsc_psi.py --url https://example.com --strategy mobile --json
  python scripts/gsc_psi.py --url https://example.com --strategy desktop --categories performance,seo,accessibility,best-practices --json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from gsc_auth import get_credentials
from gsc_utils import cache_get, cache_set

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
DEFAULT_CATEGORIES = ("performance", "seo", "accessibility", "best-practices")
FETCH_TIMEOUT_SECONDS = 60


def _bearer_token() -> str:
    creds = get_credentials(write=False)
    # google-auth Credentials may need a refresh before .token is populated
    if not getattr(creds, "token", None) or getattr(creds, "expired", False):
        from google.auth.transport.requests import Request
        creds.refresh(Request())
    token = getattr(creds, "token", None)
    if not token:
        raise RuntimeError("Could not obtain access token from credentials")
    return token


def run_psi(url: str, strategy: str = "mobile",
            categories: tuple[str, ...] = DEFAULT_CATEGORIES,
            locale: str = "en", use_cache: bool = True) -> dict[str, Any]:
    """Run PageSpeed Insights against `url`. Returns a flattened summary plus
    the full Lighthouse result under `raw`."""
    if strategy not in ("mobile", "desktop"):
        raise ValueError("strategy must be 'mobile' or 'desktop'")
    cache_args = ("psi", url, strategy, tuple(sorted(categories)), locale)
    if use_cache:
        cached = cache_get(*cache_args)
        if cached:
            return cached

    qs = [
        ("url", url),
        ("strategy", strategy),
        ("locale", locale),
    ]
    for c in categories:
        qs.append(("category", c))
    full = f"{PSI_ENDPOINT}?{urllib.parse.urlencode(qs)}"

    req = urllib.request.Request(full, headers={
        "Authorization": f"Bearer {_bearer_token()}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"PSI HTTP {e.code}: {body[:600]}") from None

    summary = _flatten_psi(payload, strategy)
    out = {**summary, "raw": payload}
    if use_cache:
        cache_set(out, *cache_args)
    return out


def _flatten_psi(payload, strategy):
    out = {
        "url": payload.get("id"),
        "strategy": strategy,
        "fetch_time": payload.get("analysisUTCTimestamp"),
    }
    lh = payload.get("lighthouseResult") or {}
    categories = lh.get("categories") or {}
    for cat in ("performance", "seo", "accessibility", "best-practices"):
        score = (categories.get(cat) or {}).get("score")
        out[f"lh_{cat.replace('-', '_')}_score"] = score

    # Lighthouse lab metrics
    audits = lh.get("audits") or {}
    out["lab"] = {
        "lcp_s": _num(audits.get("largest-contentful-paint", {}).get("numericValue"), 1000),
        "cls": _num(audits.get("cumulative-layout-shift", {}).get("numericValue"), 1),
        "tbt_ms": _num(audits.get("total-blocking-time", {}).get("numericValue"), 1),
        "fcp_s": _num(audits.get("first-contentful-paint", {}).get("numericValue"), 1000),
        "si_s": _num(audits.get("speed-index", {}).get("numericValue"), 1000),
    }

    # Field metrics (CrUX origin/page, if available)
    loading = payload.get("loadingExperience") or {}
    metrics = loading.get("metrics") or {}
    out["field"] = {}
    for psi_key, friendly in (
        ("LARGEST_CONTENTFUL_PAINT_MS", "lcp_p75_ms"),
        ("CUMULATIVE_LAYOUT_SHIFT_SCORE", "cls_p75"),
        ("INTERACTION_TO_NEXT_PAINT", "inp_p75_ms"),
        ("FIRST_CONTENTFUL_PAINT_MS", "fcp_p75_ms"),
        ("EXPERIMENTAL_TIME_TO_FIRST_BYTE", "ttfb_p75_ms"),
    ):
        m = metrics.get(psi_key)
        if m:
            out["field"][friendly] = m.get("percentile")
            out["field"][friendly + "_category"] = m.get("category")
    out["field"]["overall_category"] = loading.get("overall_category")
    return out


def _num(v, divisor):
    if v is None:
        return None
    try:
        return round(float(v) / divisor, 3)
    except (TypeError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser(description="PageSpeed Insights wrapper")
    parser.add_argument("--url", required=True, help="Full URL (with scheme)")
    parser.add_argument("--strategy", default="mobile", choices=("mobile", "desktop"))
    parser.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES),
                        help="Comma-separated Lighthouse categories")
    parser.add_argument("--locale", default="en")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cats = tuple(c.strip() for c in args.categories.split(",") if c.strip())
    try:
        out = run_psi(args.url, strategy=args.strategy, categories=cats,
                      locale=args.locale, use_cache=not args.no_cache)
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}), file=sys.stderr)
        return 1
    # Keep stdout compact unless the user really wants the raw Lighthouse blob
    out_compact = {k: v for k, v in out.items() if k != "raw"}
    print(json.dumps(out_compact, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
