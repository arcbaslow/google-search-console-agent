"""
Chrome UX Report wrapper.

CrUX exposes real-user field measurements aggregated over the last 28
days for any origin or URL Google has enough Chrome traffic data for.
Two endpoints:

  queryRecord         — snapshot of LCP, INP, CLS, FCP, TTFB at p75
  queryHistoryRecord  — last 25 weeks of the same metrics, week-by-week

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
import sys
import urllib.error
import urllib.request
from typing import Any

from gsc_auth import get_credentials
from gsc_utils import cache_get, cache_set

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
        raise RuntimeError(f"CrUX HTTP {e.code}: {body_text[:500]}") from None


def query_record(origin: str | None = None, url: str | None = None,
                 form_factor: str = "ALL_FORM_FACTORS",
                 use_cache: bool = True) -> dict[str, Any]:
    """Snapshot of the last-28-day CrUX record for `origin` OR `url` (one or
    the other, not both)."""
    if (origin and url) or (not origin and not url):
        raise ValueError("pass exactly one of origin / url")
    if form_factor not in FORM_FACTORS:
        raise ValueError(f"form_factor must be one of {FORM_FACTORS}")

    cache_args = ("crux_record", origin, url, form_factor)
    if use_cache:
        cached = cache_get(*cache_args)
        if cached:
            return cached

    body: dict[str, Any] = {"formFactor": form_factor}
    if origin:
        body["origin"] = origin
    else:
        body["url"] = url

    resp = _post(CRUX_QUERY_URL, body)
    out = _flatten_record(resp, origin or url, form_factor)
    if use_cache:
        cache_set(out, *cache_args)
    return out


def query_history(origin: str | None = None, url: str | None = None,
                  form_factor: str = "ALL_FORM_FACTORS",
                  collection_period_count: int = 25,
                  use_cache: bool = True) -> dict[str, Any]:
    """Week-by-week CrUX history (up to 25 weeks). Returns the same shape as
    query_record but each metric is a list of weekly p75 values + categories."""
    if (origin and url) or (not origin and not url):
        raise ValueError("pass exactly one of origin / url")
    if form_factor not in FORM_FACTORS:
        raise ValueError(f"form_factor must be one of {FORM_FACTORS}")

    cache_args = ("crux_history", origin, url, form_factor, collection_period_count)
    if use_cache:
        cached = cache_get(*cache_args)
        if cached:
            return cached

    body: dict[str, Any] = {
        "formFactor": form_factor,
        "collectionPeriodCount": collection_period_count,
    }
    if origin:
        body["origin"] = origin
    else:
        body["url"] = url

    resp = _post(CRUX_HISTORY_URL, body)
    out = _flatten_history(resp, origin or url, form_factor)
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


def _flatten_record(resp, target, form_factor):
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
        p75 = pct.get("p75")
        if raw_key == "cumulative_layout_shift" and isinstance(p75, str):
            # CLS is returned as a string; coerce to float
            try:
                p75 = float(p75)
            except ValueError:
                pass
        flat[friendly] = p75
    return flat


def _flatten_history(resp, target, form_factor):
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
        if raw_key == "cumulative_layout_shift":
            timeseries = [float(v) if isinstance(v, str) else v for v in timeseries]
        flat["history"][friendly] = timeseries
    return flat


def main():
    parser = argparse.ArgumentParser(description="Chrome UX Report wrapper")
    parser.add_argument("--origin", help="Site origin (e.g. https://example.com)")
    parser.add_argument("--url", help="Single URL (mutually exclusive with --origin)")
    parser.add_argument("--form-factor", default="ALL_FORM_FACTORS", choices=FORM_FACTORS)
    parser.add_argument("--history", action="store_true", help="Pull weekly history instead of snapshot")
    parser.add_argument("--periods", type=int, default=25, help="History period count (max 25)")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        if args.history:
            out = query_history(origin=args.origin, url=args.url, form_factor=args.form_factor,
                                collection_period_count=args.periods,
                                use_cache=not args.no_cache)
        else:
            out = query_record(origin=args.origin, url=args.url, form_factor=args.form_factor,
                               use_cache=not args.no_cache)
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
