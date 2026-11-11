"""Search Console MCP tool set.

register(server, prefix) adds the read tools, which never change anything on Google
or on the inspected sites and request only the read-only Search Console scope.
register_writes(server, gate, prefix) adds delete_sitemap, which needs the
`webmasters` scope and a dry run followed by a confirmed call. main() serves the
read tools over stdio. Tool outputs pass through the repo's PII scrubber, and
failures come back as {"error": <category>, "hint": ...} instead of raised exceptions.
"""

from __future__ import annotations

import functools
import hashlib
import http.client
import inspect
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import threading
import time
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Callable, NamedTuple
from urllib.parse import urlsplit

import gsc_admin
import gsc_auth
import gsc_crux
import gsc_data
import gsc_psi
import gsc_structured_data
from gsc_utils import (
    ApiReadError,
    http_error_details,
    normalize_site_url,
    pagespeed_api_key,
    scrub_pii,
)

log = logging.getLogger("gsc_mcp")

LIST_SITES_MAX = 500
SEARCH_ANALYTICS_MAX = 500
LIST_SITEMAPS_MAX = 200
CRUX_HISTORY_MAX = 40
STRUCTURED_SAMPLE_MAX = 25
STRUCTURED_BLOCKS_MAX = 50

_AUTH_HINT = (
    "No usable Google credentials for Search Console. Provide "
    "~/.claude/gsc-credentials.json or set GOOGLE_APPLICATION_CREDENTIALS, or run: "
    + gsc_auth.adc_command(write=False)
    + " The tools themselves only request the read-only Search Console scope."
)

# Token-shaped values and key=value pairs that credential libraries can echo. The last
# pattern catches a bare long token with no label; it also hides long resource ids,
# which costs nothing in an error hint.
_SECRET_PATTERNS = (
    (re.compile(r"(?i)\bbearer\s+[\w.~+/=-]+"), "Bearer [redacted]"),
    (re.compile(r"\bya29\.[\w.-]+"), "[redacted]"),
    (re.compile(r"\b1//[\w-]{20,}"), "[redacted]"),
    (re.compile(r"\bGOCSPX-[\w-]{20,}"), "[redacted]"),
    (re.compile(r"\bAIza[\w-]{30,}"), "[redacted]"),
    (re.compile(r"(?i)([?&]key=)[^&\s\"']+"), r"\1[redacted]"),
    (re.compile(
        r"(?i)\b((?:access_|refresh_|id_)?token|client_secret|api[_-]?key|authorization"
        r"|password|secret)\b([\"']?\s*[:=]\s*[\"']?)[^\s\"',&}\])]+"),
     r"\1\2[redacted]"),
    (re.compile(r"[A-Za-z0-9_-]{40,}"), "[redacted]"),
)

_API_CATEGORIES = {
    "quota_exhausted": "quota_exceeded",
    "rate_or_quota_limit": "quota_exceeded",
    "authentication": "auth_required",
    "access_denied": "permission_denied",
    "service_unavailable": "upstream_error",
}


def _scrub_text(text: str, limit: int = 300) -> str:
    key = pagespeed_api_key()
    if key:
        text = text.replace(key, "[redacted]")
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return scrub_pii(text)[:limit]


def _error(category: str, hint: str, **extra: Any) -> dict[str, Any]:
    return {"error": category, "hint": hint, **extra}


_API_KEY_SETUP = (
    "Set PAGESPEED_API_KEY to a Google API key from a Cloud project with the PageSpeed "
    "Insights API and the Chrome UX Report API enabled."
)


def _page_speed_refusal(source: str, status: Any) -> tuple[str, str] | None:
    """Category and hint for a 400 or 403 from PSI or CrUX, which depend on whether an API
    key was sent. Without one the OAuth bearer token goes out, and both APIs are
    expected to refuse it (PSI 403 scope error, CrUX 400; observed, not covered by offline checks). That is a credential problem, not a bad
    site URL."""
    name = {"PSI": "PageSpeed Insights", "CrUX": "The Chrome UX Report API"}.get(source)
    if name is None or status not in (400, 403):
        return None
    if pagespeed_api_key() is None:
        if status == 403 or source == "CrUX":
            return "auth_required", (
                f"{name} refused the OAuth token that is sent when PAGESPEED_API_KEY is not "
                f"set (HTTP {status}). {_API_KEY_SETUP}")
        return None
    if status == 403:
        return "permission_denied", (
            f"{name} refused the API key (HTTP 403). Enable the PageSpeed Insights API and the "
            "Chrome UX Report API on the key's Cloud project, and check the key's API "
            "restrictions and any IP or referrer restrictions.")
    return "invalid_argument", (
        f"{name} rejected the request (HTTP 400). Check url, origin and form_factor, and "
        "that PAGESPEED_API_KEY is a valid key.")


def _api_error(details: dict[str, Any]) -> dict[str, Any]:
    source = _scrub_text(str(details.get("source", "Google")), 40)
    status = details.get("http_status")
    category = _API_CATEGORIES.get(details.get("category")) or {
        400: "invalid_argument", 404: "not_found"}.get(status, "upstream_error")
    hints = {
        "quota_exceeded": f"{source} quota or rate limit reached. Wait and retry later.",
        "auth_required": _AUTH_HINT,
        "permission_denied": (f"{source} refused access. The account behind the credentials "
                              "needs access to this property, and the API must be enabled on "
                              "the quota project."),
        "invalid_argument": f"{source} rejected the request. Check site_url, url and dates.",
        "not_found": f"{source} has no such resource. Use list_sites for exact property names.",
        "upstream_error": f"{source} failed or is unavailable (HTTP {status}). Retry later.",
    }
    hint = hints[category]
    category, hint = _page_speed_refusal(source, status) or (category, hint)
    result = _error(category, hint, source=source, http_status=status)
    reasons =[_scrub_text(r, 80) for r in details.get("reasons") or [] if isinstance(r, str)]
    if reasons:
        result["reasons"] = reasons
    if details.get("retry_after") is not None:
        result["retry_after"] = _scrub_text(str(details["retry_after"]), 40)
    return result


def _is_auth_failure(exc: Exception) -> bool:
    if isinstance(exc, gsc_auth.AuthRequiredError):
        return True
    try:
        from google.auth.exceptions import GoogleAuthError, TransportError

        if isinstance(exc, GoogleAuthError) and not isinstance(exc, TransportError):
            return True
    except ImportError:
        pass
    # gsc_auth reads, refreshes and re-saves the credentials file itself, so a missing
    # key, bad JSON or an unwritable file raised inside it is a credentials problem.
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_globals.get("__name__") == "gsc_auth":
            return True
        tb = tb.tb_next
    return "obtain access token" in str(exc)


class _ToolError(Exception):
    def __init__(self, category: str, hint: str, **extra: Any):
        super().__init__(hint)
        self.result = _error(category, hint, **extra)


def _error_result(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, _ToolError):
        return exc.result
    if isinstance(exc, ApiReadError):
        return _api_error(exc.details)
    if _is_auth_failure(exc):
        return _error("auth_required", _AUTH_HINT)
    try:
        from googleapiclient.errors import HttpError

        if isinstance(exc, HttpError):
            return _api_error(http_error_details("GSC", exc.resp.status, exc.content, exc.resp))
    except ImportError:
        pass
    if isinstance(exc, ValueError):
        return _error("invalid_argument", _scrub_text(str(exc)))
    return _error("upstream_error", f"Unexpected {type(exc).__name__}: {_scrub_text(str(exc))}")


def _guarded(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            out = fn(*args, **kwargs)
            # A confirm token is hex and can look like a phone number to the scrubber.
            token = out.get("confirm") if isinstance(out, dict) else None
            if isinstance(token, str) and _CONFIRM_RE.fullmatch(token):
                out = {**scrub_pii({k: v for k, v in out.items() if k != "confirm"}),
                       "confirm": token}
            else:
                out = scrub_pii(out)
            return out
        except Exception as exc:
            result = _error_result(exc)
            log.warning("%s failed: %s (%s)", fn.__name__, result["error"], type(exc).__name__)
            return result

    return wrapper


def _limit(value: Any, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"limit must be an integer between 1 and {maximum}")
    return value


def _site(site_url: Any) -> str:
    if not isinstance(site_url, str) or not site_url.strip():
        raise ValueError("site_url is required")
    return site_url.strip()


def _http_url(value: Any, name: str):
    parts = urlsplit(value) if isinstance(value, str) else None
    if (parts is None or parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username or parts.password):
        raise ValueError(f"{name} must be an absolute http(s) URL without credentials")
    return parts


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


class _NonPublicAddress(OSError):
    pass


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    # Judge IPv4-mapped and NAT64 (64:ff9b::/96) addresses by the IPv4 address inside
    # them; the stdlib's own answer for these differs between Python versions.
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    elif ip.version == 6 and ip in _NAT64:
        ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.is_global


def _public_infos(host: str, port: int) -> list:
    """Resolve once and refuse unless every answer is a global address."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not infos or not all(_is_public(info[4][0]) for info in infos):
        raise _NonPublicAddress(f"{host} does not resolve to a public address")
    return infos


def _require_public_host(parts, name: str) -> None:
    """Early refusal of the caller's own URL, so it reports invalid_argument. The
    enforcement is the pinned opener, which also covers every later hop."""
    try:
        _public_infos(parts.hostname, parts.port or 443)
    except _NonPublicAddress:
        raise ValueError(f"{name} must point to a public host") from None
    except OSError:
        raise ValueError(f"{name} host does not resolve") from None


def _connect_public(address, timeout=None, source_address=None):
    """Dial the address that was validated, not the name, so a resolver that answers
    differently a moment later cannot redirect the connection."""
    host, port = address
    error = None
    for family, kind, proto, _canonical, sockaddr in _public_infos(host, port):
        sock = socket.socket(family, kind, proto)
        try:
            if isinstance(timeout, (int, float)):
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            sock.close()
            error = exc
    raise error


class _Pinned:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # http.client dials through this attribute. HTTPS still wraps the socket with the
        # original hostname, so SNI and certificate verification are unchanged.
        self._create_connection = _connect_public


class _PinnedHTTPConnection(_Pinned, http.client.HTTPConnection):
    pass


class _PinnedHTTPSConnection(_Pinned, http.client.HTTPSConnection):
    pass


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinnedHTTPConnection, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PinnedHTTPSConnection, req)


def _guarded_opener() -> urllib.request.OpenerDirector:
    """An opener whose every connection, redirect hops included, goes through
    _connect_public. Built from scratch rather than with build_opener, which would add
    FTP and file handlers and read proxy settings from the environment."""
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler({}), urllib.request.UnknownHandler(),
        _PinnedHTTPHandler(), _PinnedHTTPSHandler(),
        urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPRedirectHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def _count(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@_guarded
def list_sites(limit: int = 100) -> dict[str, Any]:
    limit = _limit(limit, LIST_SITES_MAX)
    sites = gsc_admin.list_sites()
    rows = sites[:limit]
    return {"sites": rows, "sites_total": len(sites),
            "rows_returned": len(rows), "complete": len(sites) <= limit}


@_guarded
def search_analytics(
    site_url: str,
    start_date: str | None = None,
    end_date: str | None = None,
    dimensions: list[str] | None = None,
    filter_expr: str | None = None,
    search_type: str = "web",
    data_state: str = "final",
    start_row: int = 0,
    limit: int = 100,
    days: int = 28,
    compare_previous: bool = False,
) -> dict[str, Any]:
    site = _site(site_url)
    if compare_previous:
        if dimensions or start_row != 0 or not (start_date and end_date):
            raise ValueError(
                "compare_previous needs start_date and end_date, no dimensions and start_row 0")
        result = gsc_data.compare_periods(
            site, start_date, end_date, search_type=search_type, data_state=data_state,
            filter_expr=filter_expr)
        returned = len(result["current"]["rows"]) + len(result["previous"]["rows"])
        return {**result, "rows_returned": returned, "complete": True}
    limit = _limit(limit, SEARCH_ANALYTICS_MAX)
    result = gsc_data.query(
        site, dimensions=["query"] if dimensions is None else dimensions, days=days,
        search_type=search_type, row_limit=limit, start_row=start_row,
        filter_expr=filter_expr, data_state=data_state, start_date=start_date,
        end_date=end_date)
    returned = len(result["rows"])
    out = {**result, "rows_returned": returned, "complete": returned < limit}
    if returned >= limit:
        out["next_start_row"] = start_row + returned
    return out


@_guarded
def inspect_url(site_url: str, url: str, language_code: str | None = None) -> dict[str, Any]:
    site = _site(site_url)
    _http_url(url, "url")
    result = gsc_admin.inspect_url(site, url, language_code)
    return {**result, "rows_returned": 1, "complete": True}


def _sitemap_row(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": s.get("path"),
        "type": s.get("type"),
        "is_pending": s.get("isPending"),
        "is_sitemaps_index": s.get("isSitemapsIndex"),
        "last_submitted": s.get("lastSubmitted"),
        "last_downloaded": s.get("lastDownloaded"),
        "errors": _count(s.get("errors")),
        "warnings": _count(s.get("warnings")),
        "contents": s.get("contents") or [],
    }


@_guarded
def list_sitemaps(site_url: str, limit: int = 100) -> dict[str, Any]:
    limit = _limit(limit, LIST_SITEMAPS_MAX)
    site = normalize_site_url(_site(site_url))
    rows = [_sitemap_row(s) for s in gsc_admin.list_sitemaps(site)]
    # Worst first, so truncation by limit never drops the sitemaps that have problems.
    rows.sort(key=lambda r: -((r["errors"] or 0) + (r["warnings"] or 0)))
    page = rows[:limit]
    return {"site_url": site, "sitemaps": page, "sitemaps_total": len(rows),
            "errors_total": sum(r["errors"] or 0 for r in rows),
            "warnings_total": sum(r["warnings"] or 0 for r in rows),
            "rows_returned": len(page), "complete": len(rows) <= limit}


@_guarded
def page_speed(
    url: str,
    source: str = "psi",
    strategy: str = "mobile",
    form_factor: str = "ALL_FORM_FACTORS",
    scope: str = "url",
    limit: int = 25,
) -> dict[str, Any]:
    parts = _http_url(url, "url")
    if scope not in ("url", "origin"):
        raise ValueError("scope must be 'url' or 'origin'")
    if source == "psi":
        result = gsc_psi.run_psi(url, strategy=strategy)
        # The full Lighthouse payload is far beyond a tool-sized response.
        return {**{k: v for k, v in result.items() if k != "raw"},
                "rows_returned": 1, "complete": True}
    target = {"origin": f"{parts.scheme}://{parts.netloc}"} if scope == "origin" else {"url": url}
    if source == "crux":
        result = gsc_crux.query_record(form_factor=form_factor, **target)
        return {**result, "rows_returned": int(result.get("status") == "ok"), "complete": True}
    if source == "crux_history":
        limit = _limit(limit, CRUX_HISTORY_MAX)
        result = gsc_crux.query_history(
            form_factor=form_factor, collection_period_count=limit, **target)
        return {**result, "rows_returned": len(result.get("collection_periods") or []),
                "complete": True}
    raise ValueError("source must be 'psi', 'crux' or 'crux_history'")


@_guarded
def structured_data(
    url: str | None = None, site_url: str | None = None, limit: int = 10,
) -> dict[str, Any]:
    if bool(url) == bool(site_url):
        raise ValueError("pass exactly one of url or site_url")
    if url:
        _require_public_host(_http_url(url, "url"), "url")
        report = gsc_structured_data.analyze_url(url, opener=_guarded_opener())
        if report.get("error") == "fetch_failed":
            return _error("upstream_error",
                          "The page could not be fetched (network error, HTTP error status, "
                          "timeout, or a redirect to a non-public address). Check that the "
                          "URL is public and reachable.", url=url)
        blocks = report["blocks"]
        return {**report, "blocks": blocks[:STRUCTURED_BLOCKS_MAX],
                "rows_returned": min(len(blocks), STRUCTURED_BLOCKS_MAX),
                "complete": len(blocks) <= STRUCTURED_BLOCKS_MAX}
    limit = _limit(limit, STRUCTURED_SAMPLE_MAX)
    site = normalize_site_url(_site(site_url))
    root = "https://" + site[len("sc-domain:"):] if site.startswith("sc-domain:") else site
    _require_public_host(_http_url(root, "site_url"), "site_url")
    report = gsc_structured_data.analyze_sitemap_sample(
        site, sample_size=limit, opener=_guarded_opener())
    if report.get("error") == "no_sitemap_urls":
        return _error("not_found",
                      "No sitemap URLs were found at the standard locations for this property.",
                      sampling=report.get("sampling"))
    # Per-block detail is left to a single-URL call; the sample keeps counts and verdicts.
    per_url = [{k: v for k, v in entry.items() if k != "blocks"} for entry in report["per_url"]]
    sampling = report["sampling"]
    return {**report, "per_url": per_url, "rows_returned": len(per_url),
            "complete": sampling["discovered_urls"] <= len(per_url) and not sampling["issues"]}


COMPARE_DIMENSIONS = ("query", "page", "country", "device", "searchAppearance")
_METRICS = ("clicks", "impressions", "ctr", "position")


def _period(start: str, end: str, label: str) -> tuple[str, str, int]:
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError(f"{label} must be YYYY-MM-DD strings")
    first, last = gsc_data.resolve_dates(start_date=start, end_date=end)
    return first, last, (date.fromisoformat(last) - date.fromisoformat(first)).days + 1


def _row_delta(key: str, dimension: str, new: dict | None, old: dict | None) -> dict[str, Any]:
    row: dict[str, Any] = {dimension: key}
    for metric in _METRICS:
        row[metric] = new[metric] if new else None
        row[f"{metric}_previous"] = old[metric] if old else None
    # A row missing from one period's top rows is unknown there, not zero.
    if new and old:
        for metric in ("clicks", "impressions"):
            row[f"{metric}_change"] = new[metric] - old[metric]
            row[f"{metric}_change_pct"] = (
                round((new[metric] - old[metric]) / old[metric] * 100, 2) if old[metric] else None)
        row["ctr_change_percentage_points"] = round((new["ctr"] - old["ctr"]) * 100, 4)
        row["position_change"] = round(new["position"] - old["position"], 4)
    else:
        for name in ("clicks_change", "clicks_change_pct", "impressions_change",
                     "impressions_change_pct", "ctr_change_percentage_points",
                     "position_change"):
            row[name] = None
    return row


def _ambiguous_keys(rows: list[dict[str, Any]], dimension: str) -> set[Any]:
    counts = Counter(r[dimension] for r in rows)
    return {k for k, n in counts.items() if n > 1 or "-redacted]" in str(k)}


@_guarded
def compare_periods(
    site_url: str,
    date_from: str,
    date_to: str,
    compare_from: str,
    compare_to: str,
    dimension: str = "query",
    limit: int = 100,
) -> dict[str, Any]:
    site = _site(site_url)
    limit = _limit(limit, SEARCH_ANALYTICS_MAX)
    if dimension not in COMPARE_DIMENSIONS:
        raise ValueError(f"dimension must be one of {', '.join(COMPARE_DIMENSIONS)}")
    start, end, days = _period(date_from, date_to, "date_from/date_to")
    prev_start, prev_end, prev_days = _period(compare_from, compare_to, "compare_from/compare_to")
    if days != prev_days:
        raise ValueError(f"periods must have the same length: {days} days against {prev_days}")
    kwargs = {"dimensions": [dimension], "row_limit": limit, "data_state": "final"}
    current = gsc_data.query(site, start_date=start, end_date=end, **kwargs)
    previous = gsc_data.query(site, start_date=prev_start, end_date=prev_end, **kwargs)
    # gsc_data.query returns keys after PII scrubbing, so two different pages can share a
    # redacted key. Such keys are never joined across periods.
    ambiguous = _ambiguous_keys(current["rows"], dimension) | _ambiguous_keys(
        previous["rows"], dimension)
    new_rows = {r[dimension]: r for r in current["rows"] if r[dimension] not in ambiguous}
    old_rows = {r[dimension]: r for r in previous["rows"] if r[dimension] not in ambiguous}
    keys = list(new_rows) + [k for k in old_rows if k not in new_rows]
    rows = [_row_delta(k, dimension, new_rows.get(k), old_rows.get(k)) for k in keys]
    unjoined = [
        {**_row_delta(r[dimension], dimension, r if side == "current" else None,
                      r if side == "previous" else None), "ambiguous_key": True}
        for side, period in (("current", current), ("previous", previous))
        for r in period["rows"] if r[dimension] in ambiguous]
    rows += unjoined
    complete = (len(current["rows"]) < limit and len(previous["rows"]) < limit
                and not unjoined)
    return {
        "site_url": current["site_url"],
        "dimension": dimension,
        "data_state": "final",
        "date_timezone": current["date_timezone"],
        "days_per_period": days,
        "current": {"start_date": start, "end_date": end, "row_count": len(current["rows"]),
                    "metadata": current["metadata"]},
        "previous": {"start_date": prev_start, "end_date": prev_end,
                     "row_count": len(previous["rows"]), "metadata": previous["metadata"]},
        "rows": rows,
        "ambiguous_rows": len(unjoined),
        "coverage": "Each period is the top rows Search Console returns. A row missing from "
                    "one period has null values and deltas there, not zeros. Rows whose key "
                    "was redacted as personal data are listed per period with ambiguous_key "
                    "and null deltas. Aggregate queries do not establish daily coverage "
                    "within each period.",
        "rows_returned": len(rows),
        "complete": complete,
    }


CWV_HISTORY_KEYS = ("lcp_p75_ms", "inp_p75_ms", "cls_p75")


@_guarded
def crux_history(url_or_origin: str, form_factor: str | None = None) -> dict[str, Any]:
    parts = _http_url(url_or_origin, "url_or_origin")
    if parts.path or parts.query or parts.fragment:
        target, kind = {"url": url_or_origin}, "url"
    else:
        target, kind = {"origin": f"{parts.scheme}://{parts.netloc}"}, "origin"
    result = gsc_crux.query_history(
        form_factor="ALL_FORM_FACTORS" if form_factor is None else form_factor, **target)
    out = {**result, "target_kind": kind}
    if "history" in result:
        out["history"] = {k: v for k, v in result["history"].items() if k in CWV_HISTORY_KEYS}
    return {**out, "rows_returned": len(result.get("collection_periods") or []),
            "complete": True}


CONFIRM_TTL_SECONDS = 600
MAX_PENDING_CONFIRMS = 100
_CONFIRM_RE = re.compile(r"[0-9a-f]{32}")
_WRITE_SCOPE = gsc_auth.SCOPES_WRITE[0]
_STALE_CONFIRM = (
    "confirm is unknown, expired, already used or was issued for a different request. Nothing "
    "was sent. Call again without confirm for a new dry run, check it, then confirm."
)
_CONFIRM_HINT = (
    "Nothing was sent. Check the sitemap entry. To delete it, repeat the call with identical "
    "arguments plus confirm within 10 minutes; a token works once."
)
_CONFLICT_HINT = (
    "The sitemap entry changed since the dry run. Nothing was sent. Run the dry run again."
)
_WRITE_AUTH_HINT = (
    f"delete_sitemap needs credentials with the {_WRITE_SCOPE} scope (the read tools only need "
    "webmasters.readonly). Run: " + gsc_auth.adc_command(write=True)
)
_WRITE_DENIED_HINT = (
    f"Search Console refused the delete. The credentials need the {_WRITE_SCOPE} scope, not "
    "only webmasters.readonly, and the account needs permission to manage sitemaps on this "
    "property. To grant the scope run: " + gsc_auth.adc_command(write=True)
)
_MAYBE_APPLIED_HINT = (
    "The delete request failed or timed out after it was sent, so the sitemap may already be "
    "deleted. Call list_sitemaps before trying again."
)
_pending: dict[str, tuple[str, str | None, float]] = {}
_pending_lock = threading.Lock()


def _digest(parts: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _issue(digest: str, fingerprint: str | None) -> str:
    now = time.monotonic()
    token = secrets.token_hex(16)
    with _pending_lock:
        for old in [t for t, (_, _, at) in _pending.items() if now - at > CONFIRM_TTL_SECONDS]:
            del _pending[old]
        _pending[token] = (digest, fingerprint, now)
        while len(_pending) > MAX_PENDING_CONFIRMS:
            del _pending[next(iter(_pending))]
    return token


def _check_confirm(confirm: Any) -> None:
    if confirm is not None and (not isinstance(confirm, str)
                                or not _CONFIRM_RE.fullmatch(confirm)):
        raise _ToolError("invalid_argument", _STALE_CONFIRM)


def _refusal(gate: Callable[[], Any]) -> dict[str, Any] | None:
    refusal = gate()
    if refusal is None:
        return None
    if isinstance(refusal, dict):
        return refusal
    return _error("permission_denied", "The host does not allow writes.")


class _NotSent(_ToolError):
    pass


def _confirmed(token: str, digest: str, fingerprint: str | None, tool: str, target: str,
               send: Callable[[], Any]) -> Any:
    """Redeem the token and send the write once. The token is gone after a mismatch or a
    sent write; it is put back when the write failed before anything was sent."""
    with _pending_lock:
        entry = _pending.pop(token, None)
    if entry is None or time.monotonic() - entry[2] > CONFIRM_TTL_SECONDS or entry[0] != digest:
        raise _ToolError("invalid_argument", _STALE_CONFIRM)
    if entry[1] != fingerprint:
        raise _ToolError("conflict", _CONFLICT_HINT)
    try:
        out = send()
    except _NotSent as exc:
        with _pending_lock:
            _pending[token] = entry
        log.info("gsc write %s %s outcome=%s", tool, target, exc.result["error"])
        raise
    except Exception as exc:
        log.info("gsc write %s %s outcome=%s", tool, target, _error_result(exc)["error"])
        raise
    log.info("gsc write %s %s outcome=ok", tool, target)
    return out


def _forget_sitemaps(site: str) -> dict[str, Any]:
    """Failure paths: the delete did not necessarily succeed, so the warning must not say it did."""
    extra = gsc_admin._invalidate_inventory({}, ("sitemaps", site))
    if "cache_warning" in extra:
        extra["cache_warning"] = ("Local sitemap cache invalidation failed. Cached reads may be "
                                  "stale; read the live sitemap list before trying again.")
    return extra


def _send_delete(site: str, feedpath: str) -> None:
    """One sitemaps.delete, not retried by this module: a failure after sending may have
    been applied. Once the request may have gone out, the cached sitemap list is dropped
    whatever the outcome."""
    from googleapiclient.errors import HttpError

    try:
        request = gsc_admin._get_service(write=True).sitemaps().delete(
            siteUrl=site, feedpath=feedpath)
    except Exception as exc:
        if _is_auth_failure(exc):
            raise _NotSent("auth_required", _WRITE_AUTH_HINT) from None
        raise
    try:
        request.execute()
    except HttpError as exc:
        extra = _forget_sitemaps(site)
        details = http_error_details("GSC", exc.resp.status, exc.content, exc.resp)
        reasons = [_scrub_text(r, 80) for r in details["reasons"]]
        if details["category"] == "authentication":
            raise _ToolError("auth_required", _WRITE_AUTH_HINT, http_status=401,
                             reasons=reasons, **extra) from None
        if details["category"] == "access_denied":
            raise _ToolError("permission_denied", _WRITE_DENIED_HINT, http_status=403,
                             reasons=reasons, **extra) from None
        if exc.resp.status >= 500:
            raise _ToolError("upstream_error", _MAYBE_APPLIED_HINT,
                             http_status=exc.resp.status, **extra) from None
        result = _api_error(details)
        raise _ToolError(result.pop("error"), result.pop("hint"), **result, **extra) from None
    except Exception as exc:
        # Credentials refresh inside execute() before the request is sent.
        if _is_auth_failure(exc):
            raise _NotSent("auth_required", _WRITE_AUTH_HINT) from None
        raise _ToolError("upstream_error", _MAYBE_APPLIED_HINT,
                         **_forget_sitemaps(site)) from None


@_guarded
def delete_sitemap(
    site_url: str,
    sitemap_url: str,
    confirm: str | None = None,
    *,
    gate: Callable[[], Any],
) -> dict[str, Any]:
    site = normalize_site_url(_site(site_url))
    _http_url(sitemap_url, "sitemap_url")
    _check_confirm(confirm)
    entry = gsc_admin.get_sitemap(site, sitemap_url)
    # The Sitemaps API has no fingerprint; a resubmission between the dry run and the
    # confirmed call changes lastSubmitted.
    fingerprint = entry.get("lastSubmitted")
    head = {"site_url": site, "sitemap_url": sitemap_url}
    digest = _digest({"tool": "delete_sitemap", **head})
    if confirm is None:
        return {"dry_run": True, **head, "sitemap": _sitemap_row(entry),
                "confirm": _issue(digest, fingerprint),
                "confirm_expires_in": CONFIRM_TTL_SECONDS, "hint": _CONFIRM_HINT}
    refusal = _refusal(gate)
    if refusal is not None:
        return refusal
    _confirmed(confirm, digest, fingerprint, "delete_sitemap", site,
               lambda: _send_delete(site, sitemap_url))
    out = gsc_admin._invalidate_inventory(
        {"dry_run": False, **head, "deleted": True}, ("sitemaps", site))
    return {**out, "rows_returned": 1, "complete": True}


class ToolSpec(NamedTuple):
    name: str
    title: str
    description: str
    fn: Callable[..., dict[str, Any]]


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "list_sites",
        "List Search Console properties",
        "List Google Search Console properties (sites) the credentials can access, with "
        "permission level. Use the returned site_url values (sc-domain:example.com or "
        "https://example.com/) as site_url in the other tools. limit defaults to 100, maximum "
        "500. Read-only.",
        list_sites,
    ),
    ToolSpec(
        "search_analytics",
        "Search Console search analytics",
        "Query Google Search Console search analytics: clicks, impressions, CTR and average "
        "position by query, page, country, device, date or searchAppearance, with an optional "
        "filter and previous-period comparison. Dates are inclusive YYYY-MM-DD in Pacific Time; "
        "omit both to use the last `days` (default 28) ending three days ago. dimensions defaults to "
        "[\"query\"]; pass [] for aggregate totals. filter_expr is \"<dimension> <op> <value>\" "
        "with op =, !=, CONTAINS, NOT_CONTAINS, INCLUDING_REGEX or EXCLUDING_REGEX. "
        "compare_previous returns aggregate totals against the adjacent equal period and needs "
        "both dates, no dimensions and start_row 0. Rows are the top rows Search Console "
        "returns, not an exhaustive export: limit defaults to 100, maximum 500; use "
        "next_start_row as start_row for the next page. Read-only.",
        search_analytics,
    ),
    ToolSpec(
        "inspect_url",
        "Inspect a URL in Search Console",
        "Inspect one URL with the Google Search Console URL Inspection API: index status, "
        "canonical, last crawl, mobile usability and rich results as Google sees it. Quota: "
        "2,000 inspections per day and 600 per minute per site (property). Every call counts "
        "and is never retried, so inspect only the URLs you need. The URL must belong to "
        "site_url. language_code is optional (for example en-US). Read-only.",
        inspect_url,
    ),
    ToolSpec(
        "list_sitemaps",
        "List Search Console sitemaps",
        "List the sitemaps submitted to a Google Search Console property with error and "
        "warning counts, last submitted and last downloaded times. Sitemaps with problems come "
        "first and the totals cover all of them. limit defaults to 100, maximum 200. Read-only: "
        "it never submits or deletes a sitemap.",
        list_sitemaps,
    ),
    ToolSpec(
        "page_speed",
        "Page speed and Core Web Vitals",
        "Check page speed and Core Web Vitals for a URL: PageSpeed Insights lab and field "
        "metrics (source=psi), the Chrome UX Report p75 snapshot for LCP, INP and CLS "
        "(source=crux) or its weekly history (source=crux_history). scope=origin queries the "
        "whole origin instead of the URL (CrUX only). strategy is mobile or desktop (PSI only); "
        "form_factor is PHONE, DESKTOP, TABLET or ALL_FORM_FACTORS (CrUX only). limit is the "
        "number of history periods, default 25, maximum 40. PSI can take up to a minute and "
        "the full Lighthouse payload is omitted. Both APIs are expected to refuse the OAuth token (PSI lists only the openid scope, CrUX declares no OAuth), so set the "
        "PAGESPEED_API_KEY environment variable to a Google API key with the PageSpeed "
        "Insights and Chrome UX Report APIs enabled. Read-only queries.",
        page_speed,
    ),
    ToolSpec(
        "structured_data",
        "Check JSON-LD structured data",
        "Check JSON-LD structured data (schema.org markup) on one page or on a sample of "
        "sitemap URLs: types found, missing required and recommended fields and a verdict per "
        "block. Pass url for one page, or site_url to sample up to limit URLs (default 10, "
        "maximum 25) from the property's sitemap; sample results keep counts and verdicts "
        "per URL, not block detail. Pages are fetched from this server and must be public "
        "http(s). These are limited top-level field checks, not rich-result eligibility. "
        "Read-only.",
        structured_data,
    ),
    ToolSpec(
        "compare_periods",
        "Compare Search Console periods",
        "Compare Google Search Console search analytics between two equal-length periods: "
        "clicks, impressions, CTR and position per query, page, country, device or "
        "searchAppearance, with per-row deltas. date_from/date_to is the period of interest, "
        "compare_from/compare_to the baseline; dates are inclusive YYYY-MM-DD in Pacific Time "
        "and both periods must have the same number of days. Only final data is used. Each "
        "period is its top `limit` rows (default 100, maximum 500); a row missing from one "
        "period has null values and null deltas there, not zeros. Percent changes are null "
        "for a zero baseline. Read-only.",
        compare_periods,
    ),
    ToolSpec(
        "crux_history",
        "Core Web Vitals history from CrUX",
        "Get the Chrome UX Report history of Core Web Vitals (LCP, INP and CLS p75) for a URL "
        "or an origin: 25 weekly collection periods, each an overlapping 28-day window, "
        "missing values as null. Pass an origin with no path (https://example.com) for "
        "origin-level data; anything with a path, including a trailing slash, is queried as "
        "that URL. form_factor is PHONE, DESKTOP or TABLET; omit it for all devices. Needs "
        "PAGESPEED_API_KEY set to a Google API key with the Chrome UX Report API enabled. "
        "Read-only.",
        crux_history,
    ),
)


def register(server: Any, prefix: str = "") -> int:
    """Add the read tools to a host FastMCP. Returns how many were added."""
    from mcp.types import ToolAnnotations

    annotations = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
    for spec in TOOLS:
        server.add_tool(spec.fn, name=prefix + spec.name, title=spec.title,
                        description=spec.description, annotations=annotations)
    return len(TOOLS)


WRITE_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "delete_sitemap",
        "Delete a Search Console sitemap",
        "Delete a sitemap from a Google Search Console property's Sitemaps report, after a dry "
        "run. sitemap_url is the full sitemap URL as list_sitemaps shows it. A call without "
        "confirm deletes nothing: it reads the sitemap entry and returns it with a single-use "
        "confirm token valid for 10 minutes. The identical call with that token deletes it "
        "once; if the entry was resubmitted in between, nothing is sent and the result is "
        "conflict. Deleting does not stop Google from crawling the sitemap or its URLs. Needs "
        f"credentials with the {_WRITE_SCOPE} scope.",
        delete_sitemap,
    ),
)


def _bind_gate(fn: Callable[..., Any], gate: Callable[[], Any]) -> Callable[..., Any]:
    def tool(**kwargs: Any) -> Any:
        return fn(**kwargs, gate=gate)

    # FastMCP builds the input schema from __signature__; the gate is not an argument.
    sig = inspect.signature(fn, eval_str=True)
    tool.__signature__ = sig.replace(
        parameters=[p for p in sig.parameters.values() if p.name != "gate"])
    tool.__name__ = fn.__name__
    tool.__doc__ = fn.__doc__
    return tool


def register_writes(server: Any, gate: Callable[[], Any], prefix: str = "") -> int:
    """Add the write tools to a host FastMCP. gate is called before every confirmed write,
    never for a dry run, and returns None to allow it or an error dict that the tool returns
    unchanged. Returns how many tools were added."""
    from mcp.types import ToolAnnotations

    if not callable(gate):
        raise TypeError("gate must be a callable that returns None or an error dict")
    for spec in WRITE_TOOLS:
        server.add_tool(
            _bind_gate(spec.fn, gate), name=prefix + spec.name, title=spec.title,
            description=spec.description,
            annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                        idempotentHint=False, openWorldHint=True))
    return len(WRITE_TOOLS)


def _adc_file() -> Path:
    """Well-known gcloud ADC path, as google.auth resolves it, without its private import."""
    config = os.environ.get("CLOUDSDK_CONFIG")
    if config:
        base = Path(config)
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", "C:\\")) / "gcloud"
    else:
        base = Path.home() / ".config" / "gcloud"
    return base / "application_default_credentials.json"


def credentials_present() -> bool:
    """True when a credential source exists. Checks files only: no network call, so no
    metadata-server probe, and it never raises."""
    try:
        candidates = [Path.home() / ".claude" / "gsc-credentials.json", _adc_file()]
        explicit = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if explicit:
            candidates.append(Path(explicit))
        return any(path.is_file() for path in candidates)
    except Exception:
        return False


def main() -> None:
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("google-search-console-agent")
    register(server)
    server.run()


if __name__ == "__main__":
    main()
