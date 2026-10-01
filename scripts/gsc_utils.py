"""
Shared utilities: JSON cache (15-min TTL), PII scrubber, slug helper.

Mirrors `ga4_utils` in the analytics agent. PII patterns deliberately
include identifier keys that sometimes leak into search query data when a
site allows user-input search reflected in the URL.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any

CACHE_DIR = Path.home() / ".claude" / "gsc-cache"
CACHE_TTL_SECONDS = 15 * 60

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Dots are a real-world phone separator (+7.701.234.5678) and were missing from
# the separator class, so dotted numbers passed through untouched.
PHONE_RE = re.compile(r"\+?\d[\d\s\-.()]{7,}\d")
# A match only counts as a phone if it carries enough actual digits. Without
# this, `2026-08-14` matches on length alone - and that is the shape of every
# value in the GSC `date` dimension, so a cached time series came back with
# every date replaced by the redaction marker.
_MIN_PHONE_DIGITS = 9


def _redact_phones(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        digits = sum(1 for c in m.group(0) if c.isdigit())
        return "[phone-redacted]" if digits >= _MIN_PHONE_DIGITS else m.group(0)

    return PHONE_RE.sub(repl, text)
PII_PARAM_DENY = {
    "email",
    "user_email",
    "phone",
    "user_phone",
    "first_name",
    "last_name",
    "full_name",
    "address",
    "ip",
    "user_ip",
    "ssn",
    "tax_id",
    "credit_card",
}


def _cache_key(*parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def cache_get(*parts: Any) -> Any:
    """Read one complete entry; missing, expired or malformed entries miss."""
    path = CACHE_DIR / f"{_cache_key(*parts)}.json"
    try:
        with path.open(encoding="utf-8") as f:
            # Use the opened file's timestamp, even if another writer replaces it.
            if time.time() - os.fstat(f.fileno()).st_mtime > CACHE_TTL_SECONDS:
                return None
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeError):
        return None


def cache_set(value: Any, *parts: Any) -> None:
    """Replace an entry atomically after serializing it in the same directory."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(*parts)
    path = CACHE_DIR / f"{key}.json"
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CACHE_DIR,
                                         prefix=f".{key}.", suffix=".tmp", delete=False) as f:
            temporary_path = Path(f.name)
            json.dump(value, f, default=str)
        # Close first for Windows. Readers see the previous or the complete new entry.
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def cache_delete(*parts: Any) -> None:
    """Remove one exact cache entry. Missing entries need no action."""
    (CACHE_DIR / f"{_cache_key(*parts)}.json").unlink(missing_ok=True)


def scrub_pii(data: Any) -> Any:
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if k.lower() in PII_PARAM_DENY:
                continue
            out[k] = scrub_pii(v)
        return out
    if isinstance(data, list):
        return [scrub_pii(x) for x in data]
    if isinstance(data, str):
        # No numeric short-circuit here. It used to return any all-digit string
        # unchanged, which is exactly the shape of a phone number, a card
        # number, or a national ID - and search queries contain all three.
        # Genuine metrics arrive as int/float and fall through at the bottom.
        s = EMAIL_RE.sub("[email-redacted]", data)
        s = _redact_phones(s)
        # GSC returns page dimensions percent-encoded, so an address that
        # survives the pass above can still be sitting in the URL as
        # `john%40gmail.com`. Preserve encoding unless the decoded pass
        # finds additional identifiers; existing markers must not hide them.
        decoded = urllib.parse.unquote(s)
        if decoded != s:
            redacted = _redact_phones(EMAIL_RE.sub("[email-redacted]", decoded))
            if redacted != decoded:
                return redacted
        return s
    return data


_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def slug(name: str) -> str:
    s = _SLUG_RE.sub("-", name.lower().strip())
    return s.strip("-") or "unnamed"


def date_range(days: int) -> tuple[str, str]:
    """Return (start_date, end_date) as YYYY-MM-DD, end = three days ago."""
    from datetime import date, timedelta

    # GSC data has a ~2-day reporting lag; end the window three days back so
    # the most recent day in the response is actually complete.
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def normalize_site_url(site: str) -> str:
    """Accept a domain or URL prefix and return the canonical GSC siteUrl form.
    Domain properties: `sc-domain:example.com`. URL prefixes keep the scheme."""
    if site.startswith("sc-domain:") or site.startswith("http"):
        return site
    if "/" not in site:
        return f"sc-domain:{site}"
    return site

# ---------- Google read transport ----------

class ApiReadError(RuntimeError):
    def __init__(self, details):
        self.details = details
        super().__init__(f"{details['source']} HTTP {details['http_status']}: "
                         f"{details['category']}; retry_after={details['retry_after']}")


def http_error_details(source, status, content, headers):
    """Expose status/reasons without echoing request URLs, tokens or raw bodies."""
    try:
        payload = json.loads(content)
        error = payload.get("error", {})
        reasons = [e.get("reason") for e in error.get("errors", []) if isinstance(e, dict)]
        reasons += [error.get("status")]
    except (ValueError, TypeError, AttributeError):
        reasons = []
    reasons = [r for r in reasons if isinstance(r, str)]
    if any(r in ("dailyLimitExceeded", "quotaExceeded", "dailyLimitExceededUnreg") for r in reasons):
        category = "quota_exhausted"
    elif status == 429 or any(r in ("rateLimitExceeded", "userRateLimitExceeded") for r in reasons):
        category = "rate_or_quota_limit"
    elif status in (401, 403):
        category = "authentication" if status == 401 else "access_denied"
    elif status >= 500:
        category = "service_unavailable"
    else:
        category = "request_failed"
    headers = {str(k).lower(): v for k, v in (headers or {}).items()}
    return {"source": source, "http_status": status, "category": category,
            "reasons": reasons, "retry_after": headers.get("retry-after")}


def _retry_delay(hint):
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime
    if hint is None:
        return 1.0
    try:
        delay = float(hint)
    except (TypeError, ValueError):
        try:
            delay = (parsedate_to_datetime(hint) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    # Do not shorten upstream delays to fit our budget.
    return max(0.0, delay) if 0 <= delay <= 5 else None


def execute_read(request, *, retry=True):
    """One retry at most for eligible GSC reads; never use for writes."""
    from googleapiclient.errors import HttpError
    for attempt in range(2 if retry else 1):
        try:
            return request.execute()
        except HttpError as error:
            details = http_error_details("GSC", error.resp.status, error.content, error.resp)
            details["attempts"] = attempt + 1
            delay = _retry_delay(details["retry_after"])
            eligible = details["category"] == "rate_or_quota_limit" or error.resp.status in (500, 502, 503, 504)
            if retry and attempt == 0 and eligible and delay is not None:
                time.sleep(delay)
                continue
            raise ApiReadError(details) from None


def build_search_service(credentials):
    """A separate bounded transport per service; never replay after a 401."""
    import google_auth_httplib2
    import httplib2
    from googleapiclient.discovery import build
    transport = google_auth_httplib2.AuthorizedHttp(
        credentials, http=httplib2.Http(timeout=60), max_refresh_attempts=0)
    return build("searchconsole", "v1", http=transport, cache_discovery=False)
