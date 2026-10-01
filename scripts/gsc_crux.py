"""
Chrome UX Report wrapper.

CrUX exposes real-user field measurements aggregated over the last 28
days for any origin or URL Google has enough Chrome traffic data for.
Two endpoints:

  queryRecord         — snapshot of LCP, INP, CLS, FCP, TTFB at p75
  queryHistoryRecord  — 25 weekly periods by default, up to 40

For origin-level audits CrUX is the right call because it covers the
whole site, not a single URL. For per-page deep dives use `gsc_psi.py`.

CLI:
  python scripts/gsc_crux.py --origin https://example.com --json
  python scripts/gsc_crux.py --url https://example.com/products --json
  python scripts/gsc_crux.py --origin https://example.com --history --json
  python scripts/gsc_crux.py --origin https://example.com --form-factor PHONE --json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.error
import urllib.request
from typing import Any

from gsc_auth import get_credentials
from gsc_utils import ApiReadError, cache_get, cache_set, http_error_details

CRUX_QUERY_URL = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"
CRUX_HISTORY_URL = "https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord"
FORM_FACTORS = ("PHONE", "DESKTOP", "TABLET", "ALL_FORM_FACTORS")

FETCH_TIMEOUT_SECONDS = 30


def _bearer_token() -> str:
    creds = get_credentials(write=False)
    if not getattr(creds, "token", None) or getattr(creds, "expired", False):
        from google.auth.transport.requests import Request
        creds.refresh(Request())
    token = getattr(creds, "token", None)
    if not token:
        raise RuntimeError("Could not obtain access token from credentials")
    return token


def _post(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {_bearer_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        if e.code == 404:
            # CrUX returns 404 when the URL has insufficient data — that's not
            # an error in the usual sense, just "no data".
            return {"_status": "no_data", "_http_code": 404, "_message": body_text[:300]}
        raise ApiReadError(http_error_details("CrUX", e.code, body_text, e.headers)) from None


def query_record(origin: str | None = None, url: str | None = None,
                 form_factor: str = "ALL_FORM_FACTORS",
                 use_cache: bool = True, diagnostics: bool = False) -> dict[str, Any]:
    """Snapshot of the last-28-day CrUX record for `origin` OR `url` (one or
    the other, not both)."""
    if (origin and url) or (not origin and not url):
        raise ValueError("pass exactly one of origin / url")
    if form_factor not in FORM_FACTORS:
        raise ValueError(f"form_factor must be one of {FORM_FACTORS}")

    cache_args = ("crux_record_v3", origin, url, form_factor, diagnostics)
    if use_cache:
        cached = cache_get(*cache_args)
        if cached:
            return cached

    body: dict[str, Any] = {}
    if form_factor != "ALL_FORM_FACTORS":
        body["formFactor"] = form_factor
    if origin:
        body["origin"] = origin
    else:
        body["url"] = url

    resp = _post(CRUX_QUERY_URL, body)
    out = _flatten_record(resp, origin or url, form_factor, diagnostics=diagnostics)
    if use_cache:
        cache_set(out, *cache_args)
    return out


def query_history(origin: str | None = None, url: str | None = None,
                  form_factor: str = "ALL_FORM_FACTORS",
                  collection_period_count: int = 25,
                  use_cache: bool = True, diagnostics: bool = False) -> dict[str, Any]:
    """Week-by-week CrUX history (up to 40 weeks). Returns the same shape as
    query_record but each metric is a list of weekly p75 values + categories."""
    if (origin and url) or (not origin and not url):
        raise ValueError("pass exactly one of origin / url")
    if form_factor not in FORM_FACTORS:
        raise ValueError(f"form_factor must be one of {FORM_FACTORS}")

    if type(collection_period_count) is not int or not 1 <= collection_period_count <= 40:
        raise ValueError("collection_period_count must be an integer between 1 and 40")
    cache_args = ("crux_history_v3", origin, url, form_factor, collection_period_count, diagnostics)
    if use_cache:
        cached = cache_get(*cache_args)
        if cached:
            return cached

    body: dict[str, Any] = {
        "collectionPeriodCount": collection_period_count,
    }
    if form_factor != "ALL_FORM_FACTORS":
        body["formFactor"] = form_factor
    if origin:
        body["origin"] = origin
    else:
        body["url"] = url

    resp = _post(CRUX_HISTORY_URL, body)
    out = _flatten_history(resp, origin or url, form_factor, diagnostics=diagnostics)
    if use_cache:
        cache_set(out, *cache_args)
    return out


_METRIC_KEYS = (
    ("largest_contentful_paint", "lcp_p75_ms"),
    ("interaction_to_next_paint", "inp_p75_ms"),
    ("cumulative_layout_shift", "cls_p75"),
    ("first_contentful_paint", "fcp_p75_ms"),
    ("experimental_time_to_first_byte", "ttfb_p75_ms"),
)


def _p75(value):
    """CrUX missing periods may contain null or the string NaN."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _flatten_record(resp, target, form_factor, diagnostics=False):
    if resp.get("_status") == "no_data":
        return {"target": target, "form_factor": form_factor, "status": "no_data"}
    rec = resp.get("record") or {}
    metrics = rec.get("metrics") or {}
    flat = {"target": target, "form_factor": form_factor,
            "collection_period": rec.get("collectionPeriod"), "status": "ok"}
    for raw_key, friendly in _METRIC_KEYS:
        m = metrics.get(raw_key)
        if not m:
            continue
        pct = m.get("percentiles") or {}
        flat[friendly] = _p75(pct.get("p75"))
    if diagnostics:
        flat["diagnostics"] = {"metrics": _clean_missing(metrics),
                               "interpretation": "Distributions and diagnostic metrics; no additional CWV verdicts."}
    return flat


def _flatten_history(resp, target, form_factor, diagnostics=False):
    if resp.get("_status") == "no_data":
        return {"target": target, "form_factor": form_factor, "status": "no_data"}
    rec = resp.get("record") or {}
    metrics = rec.get("metrics") or {}
    collection_periods = rec.get("collectionPeriods") or []
    flat = {"target": target, "form_factor": form_factor,
            "collection_periods": collection_periods, "status": "ok", "history": {}}
    for raw_key, friendly in _METRIC_KEYS:
        m = metrics.get(raw_key)
        if not m:
            continue
        timeseries = (m.get("percentilesTimeseries") or {}).get("p75s") or []
        flat["history"][friendly] = [_p75(v) for v in timeseries]
    if diagnostics:
        flat["diagnostics"] = {"metrics": _clean_missing(metrics),
                               "interpretation": "Distributions and diagnostic metrics; no additional CWV verdicts."}
    return flat


def _clean_missing(value):
    if isinstance(value, dict):
        return {k: _clean_missing(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_missing(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, str) and value.lower() in ("nan", "infinity", "-infinity"):
        return None
    return value


def main():
    parser = argparse.ArgumentParser(description="Chrome UX Report wrapper")
    parser.add_argument("--origin", help="Site origin (e.g. https://example.com)")
    parser.add_argument("--url", help="Single URL (mutually exclusive with --origin)")
    parser.add_argument("--form-factor", default="ALL_FORM_FACTORS", choices=FORM_FACTORS)
    parser.add_argument("--history", action="store_true", help="Pull weekly history instead of snapshot")
    parser.add_argument("--periods", type=int, default=25, help="History period count (1-40, default 25)")
    parser.add_argument("--diagnostics", action="store_true", help="Include all available metric distributions and subparts")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        if args.history:
            out = query_history(origin=args.origin, url=args.url, form_factor=args.form_factor,
                                collection_period_count=args.periods,
                                use_cache=not args.no_cache, diagnostics=args.diagnostics)
        else:
            out = query_record(origin=args.origin, url=args.url, form_factor=args.form_factor,
                               use_cache=not args.no_cache, diagnostics=args.diagnostics)
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__, **getattr(e, "details", {})}), file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
