"""
Page experience / security-posture adapter.

Three free signals are bundled:

  1. Local header probe — fetch the homepage with HTTP HEAD and grade
     the presence and shape of HSTS, Content-Security-Policy,
     X-Content-Type-Options, X-Frame-Options, Referrer-Policy, and
     Permissions-Policy. No external service.

  2. Mozilla HTTP Observatory — A+ to F grade based on a wider set of
     header / cookie / TLS rules. Public endpoint, no API key.
     A synchronous POST returns a completed or cached scan.

  3. SSL Labs — A+ to F TLS grade including cipher suite, certificate,
     protocol-version, and known-vulnerability checks. Public endpoint,
     no API key. Polls up to 120 seconds. Cached results are used when
     available via `fromCache=on`.

These describe security posture. Header grades do not establish a ranking
impact or replace Core Web Vitals measurements.

CLI:
  python scripts/gsc_page_experience.py --host example.com --json
  python scripts/gsc_page_experience.py --host example.com --headers --json
  python scripts/gsc_page_experience.py --host example.com --observatory --json
  python scripts/gsc_page_experience.py --host example.com --ssl --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

MOZILLA_OBSERVATORY_URL = "https://observatory-api.mdn.mozilla.net/api/v2/scan"
SSL_LABS_URL = "https://api.ssllabs.com/api/v3/analyze"

DEFAULT_TIMEOUT_S = 15
OBSERVATORY_POLL_BUDGET_S = 30
SSL_POLL_BUDGET_S = 120
POLL_INTERVAL_S = 5

USER_AGENT = "google-search-console-agent/0.2 (+page-experience)"


def _strip_scheme(host: str) -> str:
    if host.startswith("sc-domain:"):
        return host[len("sc-domain:"):].strip().strip("/")
    p = urllib.parse.urlparse(host)
    if p.scheme:
        return p.netloc.lower()
    return host.strip().strip("/").lower()


# ---------- Local header probe ----------

SECURITY_HEADERS = (
    "strict-transport-security",
    "content-security-policy",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "permissions-policy",
)


def probe_headers(host: str) -> dict[str, Any]:
    """HEAD request to https://<host>/. Returns header presence + a
    coarse grade based on how many are configured. Never raises."""
    host = _strip_scheme(host)
    url = f"https://{host}/"
    req = urllib.request.Request(url, method="HEAD", headers={
        "User-Agent": USER_AGENT, "Accept": "*/*",
    })
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_S) as resp:
            status = resp.status
            headers = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError:
        # Many sites disallow HEAD; fall back to a small GET.
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT, "Accept": "*/*",
            })
            with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_S) as resp:
                status = resp.status
                headers = {k.lower(): v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as e2:
            return {"host": host, "url": url, "error": f"http_{e2.code}"}
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e2:
            return {"host": host, "url": url, "error": "transport", "message": str(e2)}
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return {"host": host, "url": url, "error": "transport", "message": str(e)}

    present = {h: headers.get(h) for h in SECURITY_HEADERS if h in headers}
    missing = [h for h in SECURITY_HEADERS if h not in headers]
    coverage = round(len(present) / len(SECURITY_HEADERS) * 100, 1)
    if coverage >= 85:
        grade = "good"
    elif coverage >= 50:
        grade = "needs_improvement"
    else:
        grade = "poor"

    return {
        "host": host,
        "url": url,
        "status": status,
        "server": headers.get("server"),
        "headers_present": present,
        "headers_missing": missing,
        "coverage_pct": coverage,
        "grade": grade,
    }


# ---------- Mozilla HTTP Observatory ----------

def run_observatory(host: str, poll_budget_s: int = OBSERVATORY_POLL_BUDGET_S) -> dict[str, Any]:
    host = _strip_scheme(host)
    # v2 returns the completed scan in the POST response; there is no GET poll.
    if poll_budget_s <= 0:
        return {"host": host, "error": "timeout"}
    url = f"{MOZILLA_OBSERVATORY_URL}?{urllib.parse.urlencode({'host': host})}"
    req = urllib.request.Request(
        url, method="POST", data=b"",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=min(DEFAULT_TIMEOUT_S, poll_budget_s)) as resp:
            scan = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"host": host, "error": f"observatory_http_{e.code}"}
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return {"host": host, "error": "transport", "message": str(e)}
    except (ValueError, UnicodeError):
        return {"host": host, "error": "invalid_response"}
    if not isinstance(scan, dict):
        return {"host": host, "error": "invalid_response"}
    if scan.get("error"):
        return {"host": host, "error": "observatory_scan_failed", "message": str(scan["error"])}
    if scan.get("grade") is None:
        return {"host": host, "error": "incomplete_response"}
    return {
        "host": host,
        "grade": scan.get("grade"),
        "score": scan.get("score"),
        "tests_passed": scan.get("tests_passed"),
        "tests_failed": scan.get("tests_failed"),
        "tests_quantity": scan.get("tests_quantity"),
        "scan_id": scan.get("id"),
        "state": "FINISHED",
    }


# ---------- SSL Labs ----------

def _ssl_json(url: str, deadline: float) -> dict[str, Any]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return {"error": "timeout"}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=min(DEFAULT_TIMEOUT_S, remaining)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) else {"error": "invalid_response"}
    except urllib.error.HTTPError as e:
        out = {"error": f"ssllabs_http_{e.code}"}
        retry = (e.headers or {}).get("Retry-After")
        if retry:
            out["retry_after"] = retry
        elif e.code in (429, 503, 529):
            out["retry_after_seconds"] = {429: 60, 503: 900, 529: 1800}[e.code]
        return out
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return {"error": "transport", "message": str(e)}
    except (ValueError, UnicodeError):
        return {"error": "invalid_response"}


def run_ssl_labs(host: str, poll_budget_s: int = SSL_POLL_BUDGET_S,
                 use_cache: bool = True) -> dict[str, Any]:
    host = _strip_scheme(host)
    params = {
        "host": host,
        "publish": "off",
        "all": "done",
    }
    if use_cache:
        params["fromCache"] = "on"
        params["maxAge"] = "24"
    deadline = time.monotonic() + poll_budget_s
    last = None
    if poll_budget_s <= 0:
        return {"host": host, "error": "timeout"}
    print(
        "SSL Labs assesses this host remotely. Use only with the owner's permission. "
        "Commercial use requires Qualys permission. Terms: "
        "https://www.ssllabs.com/downloads/Qualys_SSL_Labs_Terms_of_Use.pdf",
        file=sys.stderr,
    )
    # The integration terms require displaying server notices before assessment.
    info = _ssl_json(SSL_LABS_URL.rsplit("/", 1)[0] + "/info", deadline)
    if info.get("error"):
        return {"host": host, **info}
    for message in info.get("messages") or []:
        print(f"SSL Labs notice: {message}", file=sys.stderr)
    if not use_cache:
        params["startNew"] = "on"
    while time.monotonic() < deadline:
        url = f"{SSL_LABS_URL}?{urllib.parse.urlencode(params)}"
        last = _ssl_json(url, deadline)
        params.pop("startNew", None)  # Only initiate once, never on subsequent polls.
        if last.get("error"):
            return {"host": host, **last}
        status = last.get("status")
        if status == "READY":
            break
        if status == "ERROR":
            return {"host": host, "error": "ssllabs_error",
                    "status_message": last.get("statusMessage")}
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(POLL_INTERVAL_S, remaining))

    if not last or last.get("status") != "READY":
        return {"host": host, "error": "timeout", "status": (last or {}).get("status")}
    endpoints = last.get("endpoints") or []
    worst_grade = None
    grade_order = ["A+", "A", "A-", "B", "C", "D", "E", "F", "T", "M"]
    grade_index = {g: i for i, g in enumerate(grade_order)}
    for ep in endpoints:
        g = ep.get("grade")
        if g and (worst_grade is None or grade_index.get(g, 99) > grade_index.get(worst_grade, -1)):
            worst_grade = g
    return {
        "host": host,
        "status": last.get("status"),
        "grade": worst_grade,
        "endpoints_tested": len(endpoints),
        "endpoint_grades": [ep.get("grade") for ep in endpoints],
        "test_time": last.get("testTime"),
        "protocol": last.get("protocol"),
    }


# ---------- Combined ----------

def full_report(host: str, with_observatory: bool = True,
                with_ssl: bool = True, use_cache: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {"host": _strip_scheme(host)}
    sources = [("headers", lambda: probe_headers(host))]
    if with_observatory:
        sources.append(("observatory", lambda: run_observatory(host)))
    if with_ssl:
        sources.append(("ssl_labs", lambda: run_ssl_labs(host, use_cache=use_cache)))
    for name, fetch in sources:
        try:
            out[name] = fetch()
        except Exception as e:
            out[name] = {"host": out["host"], "error": type(e).__name__, "message": str(e)}
    return out


# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(description="Page experience / security adapter")
    parser.add_argument("--host", required=True, help="Domain (no scheme)")
    parser.add_argument("--headers", action="store_true", help="Local header probe only")
    parser.add_argument("--observatory", action="store_true", help="Mozilla Observatory only")
    parser.add_argument("--ssl", action="store_true", help="SSL Labs only")
    parser.add_argument("--no-cache", action="store_true", help="Skip SSL Labs cached results")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        if args.headers and not (args.observatory or args.ssl):
            out = probe_headers(args.host)
        elif args.observatory and not (args.headers or args.ssl):
            out = run_observatory(args.host)
        elif args.ssl and not (args.headers or args.observatory):
            out = run_ssl_labs(args.host, use_cache=not args.no_cache)
        else:
            out = full_report(args.host, use_cache=not args.no_cache)
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
