"""
GSC Search Analytics API wrapper.

Exposes searchanalytics.query: distinct queries, pages, countries, devices,
search appearance, and dates with clicks / impressions / ctr / position.

All calls accept either a domain property (`sc-domain:example.com`) or a
URL-prefix property (`https://example.com/`). The `normalize_site_url`
helper accepts either bare-domain or full URL.

CLI:
  python scripts/gsc_data.py --site example.com --queries --days 28 --json
  python scripts/gsc_data.py --site example.com --pages --days 28 --json
  python scripts/gsc_data.py --site example.com --report --dimensions query,page --days 28 --rows 500 --json
  python scripts/gsc_data.py --site example.com --filter "query CONTAINS 'pricing'" --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from typing import Any

from gsc_auth import get_credentials
from gsc_utils import (
    build_search_service,
    cache_get,
    cache_set,
    date_range,
    execute_read,
    normalize_site_url,
    scrub_pii,
)

_FILTER_RE = re.compile(
    r"^\s*(?P<dim>\w+)\s+(?P<op>=|!=|CONTAINS|EQUALS|NOT_CONTAINS|NOT_EQUALS|INCLUDING_REGEX|EXCLUDING_REGEX)\s+(?P<val>.+?)\s*$",
    re.IGNORECASE,
)

DIMENSIONS = {"query", "page", "country", "device", "searchAppearance", "date", "hour"}
SEARCH_TYPES = {"web", "image", "video", "news", "discover", "googleNews"}
DATA_STATES = {"all", "final", "hourly_all"}


def parse_filter(expr: str | None) -> dict[str, Any] | None:
    """Parse `<dimension> <op> <value>` into a GSC dimensionFilterGroup entry."""
    if not expr:
        return None
    m = _FILTER_RE.match(expr)
    if not m:
        raise ValueError(f"Unparseable filter: {expr!r}")
    dim = m.group("dim")
    op = m.group("op").upper()
    val = m.group("val").strip().strip("'\"")

    op_map = {
        "=": "equals",
        "EQUALS": "equals",
        "!=": "notEquals",
        "NOT_EQUALS": "notEquals",
        "CONTAINS": "contains",
        "NOT_CONTAINS": "notContains",
        "INCLUDING_REGEX": "includingRegex",
        "EXCLUDING_REGEX": "excludingRegex",
    }
    return {"dimension": dim, "operator": op_map[op], "expression": val}


def _get_service():
    return build_search_service(get_credentials())


def query(site_url: str, dimensions: list[str] | None = None, days: int = 28,
          search_type: str = "web", row_limit: int = 1000, start_row: int = 0,
          filter_expr: str | None = None, data_state: str = "final",
          use_cache: bool = True, start_date: str | None = None,
          end_date: str | None = None) -> dict[str, Any]:
    """Run a search analytics query. Returns flattened rows with the requested
    dimensions plus the four metrics."""
    site_url = normalize_site_url(site_url)
    dims = dimensions or []
    for d in dims:
        if d not in DIMENSIONS:
            raise ValueError(f"unknown dimension {d!r}; expected one of {sorted(DIMENSIONS)}")
    if search_type not in SEARCH_TYPES:
        raise ValueError(f"search_type must be one of {sorted(SEARCH_TYPES)}")
    if data_state not in DATA_STATES:
        raise ValueError(f"data_state must be one of {sorted(DATA_STATES)}")

    if type(row_limit) is not int or not 1 <= row_limit <= 25000:
        raise ValueError("row_limit must be an integer between 1 and 25000")
    if type(start_row) is not int or start_row < 0:
        raise ValueError("start_row must be a nonnegative integer")

    if len(dims) != len(set(dims)):
        raise ValueError("dimensions must not repeat")
    if ("hour" in dims) != (data_state == "hourly_all"):
        raise ValueError("hour and hourly_all must be used together")
    if data_state == "hourly_all" and not start_date:
        raise ValueError("hourly data requires explicit start_date and end_date")
    start, end = resolve_dates(days, start_date, end_date)
    cache_args = ("query", site_url, tuple(dims), search_type, row_limit, start_row,
                  filter_expr, data_state, start, end)
    if use_cache:
        cached = cache_get(*cache_args)
        if cached:
            scrubbed = scrub_pii(cached)
            if scrubbed != cached:
                cache_set(scrubbed, *cache_args)
            return scrubbed

    body: dict[str, Any] = {
        "startDate": start,
        "endDate": end,
        "dimensions": dims,
        "rowLimit": row_limit,
        "startRow": start_row,
        "type": search_type,
        "dataState": data_state,
    }
    if filter_expr:
        f = parse_filter(filter_expr)
        if f:
            body["dimensionFilterGroups"] = [{"groupType": "and", "filters": [f]}]

    service = _get_service()
    resp = execute_read(service.searchanalytics().query(siteUrl=site_url, body=body))

    rows_out = []
    for row in resp.get("rows", []):
        item = {}
        for i, d in enumerate(dims):
            item[d] = (row.get("keys") or [None] * len(dims))[i]
        item["clicks"] = row.get("clicks", 0)
        item["impressions"] = row.get("impressions", 0)
        item["ctr"] = row.get("ctr", 0.0)
        item["position"] = row.get("position", 0.0)
        rows_out.append(item)

    out = {
        "site_url": site_url,
        "start_date": start,
        "end_date": end,
        "dimensions": dims,
        "search_type": search_type,
        "data_state": data_state,
        "row_count": len(rows_out),
        "rows": rows_out,
        "response_aggregation_type": resp.get("responseAggregationType"),
        "metadata": resp.get("metadata") or {},
        "date_timezone": "America/Los_Angeles",
    }
    out = scrub_pii(out)
    if use_cache:
        cache_set(out, *cache_args)
    return out


def resolve_dates(days=28, start_date=None, end_date=None):
    """Explicit dates are inclusive Search Console PT calendar dates."""
    if start_date is not None or end_date is not None:
        if not start_date or not end_date:
            raise ValueError("start_date and end_date must be supplied together")
        for value in (start_date, end_date):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("dates must use YYYY-MM-DD")
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        if start > end:
            raise ValueError("start_date must not follow end_date")
        return str(start), str(end)
    if type(days) is not int or not 1 <= days <= 500:
        raise ValueError("days must be an integer between 1 and 500")
    return date_range(days)


def compare_periods(site_url, start_date, end_date, **kw):
    """Two explicit aggregate queries, not a sum of truncated top rows."""
    start, end = resolve_dates(start_date=start_date, end_date=end_date)
    size = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    previous_end = date.fromisoformat(start) - timedelta(days=1)
    previous_start = previous_end - timedelta(days=size - 1)
    current = query(site_url, start_date=start, end_date=end, row_limit=1, **kw)
    previous = query(site_url, start_date=str(previous_start), end_date=str(previous_end), row_limit=1, **kw)
    result = {"current": current, "previous": previous, "days_per_period": size,
              "changes": {}, "comparison_status": "unavailable"}
    # Fresh aggregate queries cannot identify partial dates; only compare final data.
    if kw.get("data_state", "final") != "final":
        result["comparison_status"] = "partial_data_possible"
    elif current["rows"] and previous["rows"]:
        new, old = current["rows"][0], previous["rows"][0]
        result["changes"] = {
            **{f"{key}_change_pct": round((new[key] - old[key]) / old[key] * 100, 2)
               if old[key] else None for key in ("clicks", "impressions")},
            "ctr_change_percentage_points": round((new["ctr"] - old["ctr"]) * 100, 4),
            "position_change": round(new["position"] - old["position"], 4),
        }
        result["comparison_status"] = "ok"
    return result


def top_queries(site_url: str, days: int = 28, row_limit: int = 100, **kw) -> dict[str, Any]:
    return query(site_url, dimensions=["query"], days=days, row_limit=row_limit, **kw)


def top_pages(site_url: str, days: int = 28, row_limit: int = 100, **kw) -> dict[str, Any]:
    return query(site_url, dimensions=["page"], days=days, row_limit=row_limit, **kw)


def by_device(site_url: str, days: int = 28, **kw) -> dict[str, Any]:
    return query(site_url, dimensions=["device"], days=days, row_limit=10, **kw)


def by_country(site_url: str, days: int = 28, row_limit: int = 50, **kw) -> dict[str, Any]:
    return query(site_url, dimensions=["country"], days=days, row_limit=row_limit, **kw)


def by_search_appearance(site_url: str, days: int = 28, **kw) -> dict[str, Any]:
    return query(site_url, dimensions=["searchAppearance"], days=days, row_limit=50, **kw)


def time_series(site_url: str, days: int = 90, **kw) -> dict[str, Any]:
    start, end = resolve_dates(days, kw.get("start_date"), kw.get("end_date"))
    count = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    return query(site_url, dimensions=["date"], days=days, row_limit=min(count + 5, 25000), **kw)


def main():
    parser = argparse.ArgumentParser(description="GSC Search Analytics wrapper")
    parser.add_argument("--site", required=True, help="domain (e.g. example.com) or URL prefix")
    parser.add_argument("--queries", action="store_true")
    parser.add_argument("--pages", action="store_true")
    parser.add_argument("--devices", action="store_true")
    parser.add_argument("--countries", action="store_true")
    parser.add_argument("--appearance", action="store_true")
    parser.add_argument("--timeseries", action="store_true")
    parser.add_argument("--report", action="store_true",
                        help="Custom query (needs --dimensions)")
    parser.add_argument("--dimensions", help="Comma-separated dimensions for --report")
    parser.add_argument("--filter", help="Optional filter: '<dim> <op> <value>'")
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--start-date", help="Inclusive PT date; requires --end-date; overrides --days")
    parser.add_argument("--end-date", help="Inclusive PT date, YYYY-MM-DD")
    parser.add_argument("--compare-previous", action="store_true", help="Compare aggregate totals for two equal periods")
    parser.add_argument("--rows", type=int, default=100, help="Rows per request (1-25000)")
    parser.add_argument("--start-row", type=int, default=0,
                        help="Zero-based offset for one request; no automatic pagination")
    parser.add_argument("--search-type", default="web")
    parser.add_argument("--data-state", default="final", choices=sorted(DATA_STATES))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    use_cache = not args.no_cache
    kw = {
        "use_cache": use_cache,
        "search_type": args.search_type,
        "data_state": args.data_state,
        "filter_expr": args.filter,
        "start_row": args.start_row,
        "start_date": args.start_date,
        "end_date": args.end_date,
    }
    try:
        if args.compare_previous:
            if not args.start_date or not args.end_date or args.start_row:
                raise ValueError("comparison requires both explicit dates and start-row 0")
            if any([args.queries, args.pages, args.devices, args.countries, args.appearance,
                    args.timeseries, args.report, args.dimensions]):
                raise ValueError("comparison is a standalone aggregate mode")
            result = compare_periods(args.site, **kw)
        elif args.queries:
            result = top_queries(args.site, days=args.days, row_limit=args.rows, **kw)
        elif args.pages:
            result = top_pages(args.site, days=args.days, row_limit=args.rows, **kw)
        elif args.devices:
            result = by_device(args.site, days=args.days, **kw)
        elif args.countries:
            result = by_country(args.site, days=args.days, row_limit=args.rows, **kw)
        elif args.appearance:
            result = by_search_appearance(args.site, days=args.days, **kw)
        elif args.timeseries:
            result = time_series(args.site, days=args.days, **kw)
        elif args.report:
            dims = [d.strip() for d in (args.dimensions or "").split(",") if d.strip()]
            result = query(args.site, dimensions=dims, days=args.days, row_limit=args.rows, **kw)
        else:
            parser.print_help()
            return 1
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__, **getattr(e, "details", {})}), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
