"""
Shared utilities: JSON cache (15-min TTL), PII scrubber, slug helper.

Mirrors `ga4_utils` in the analytics agent. PII patterns deliberately
include identifier keys that sometimes leak into search query data when a
site allows user-input search reflected in the URL.
"""

from __future__ import annotations

import hashlib
import json
import re
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


def cache_get(*parts: Any) -> dict[str, Any] | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{_cache_key(*parts)}.json"
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
        return None
    with open(path) as f:
        return json.load(f)


def cache_set(value: dict[str, Any], *parts: Any) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{_cache_key(*parts)}.json"
    with open(path, "w") as f:
        json.dump(value, f, default=str)


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
        # `john%40gmail.com`. Redact against the decoded form, then keep
        # whichever version still has something to hide.
        decoded = urllib.parse.unquote(s)
        if decoded != s:
            decoded = _redact_phones(EMAIL_RE.sub("[email-redacted]", decoded))
            if "redacted]" in decoded and "redacted]" not in s:
                return decoded
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
