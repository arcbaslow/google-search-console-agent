"""
Backlinks / domain-authority adapter.

Two free data sources are bundled:

  1. Open PageRank — current POST bulk API, up to 100 domains per request.
     Set OPENPAGERANK_V1_API_KEY to a newly issued OPR key. Legacy keys are
     not forwarded to the new host. Source scores are informational.

  2. Tranco top-1M list — a combined popularity ranking using Umbrella,
     Majestic, Farsight, CrUX and Cloudflare inputs.
     No API key. Downloaded once and cached locally under
     `~/.claude/gsc-cache/tranco.csv`. Refreshes weekly.

Neither gives you a literal "list of backlinks", but together they
answer the question every audit needs to ask: "how authoritative is
this domain vs the competitors I care about?". For the actual link
graph, Common Crawl WAT files are the open-data path — too heavy for
a CLI, kept as future work.

CLI:
  python scripts/gsc_backlinks.py --domain example.com --json
  python scripts/gsc_backlinks.py --compare example.com,competitor.com --json
  python scripts/gsc_backlinks.py --tranco example.com --json
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

OPENPAGERANK_URL = "https://openpagerank.keywordseverywhere.com/v1/domains/bulk"
TRANCO_URL = "https://tranco-list.eu/top-1m.csv.zip"
TRANCO_CACHE = Path.home() / ".claude" / "gsc-cache" / "tranco.csv"
TRANCO_REFRESH_SECONDS = 7 * 24 * 3600  # rebuild weekly

FETCH_TIMEOUT_SECONDS = 60


def _strip_scheme(host: str) -> str:
    if host.startswith("sc-domain:"):
        return host[len("sc-domain:"):].strip().strip("/")
    parsed = urllib.parse.urlparse(host)
    if parsed.scheme:
        return parsed.netloc.lower()
    return host.strip().strip("/").lower()


# ---------- Open PageRank ----------

def query_open_pagerank(domains: list[str], api_key: str | None = None) -> dict:
    """One current-API request. Legacy environment keys are never forwarded."""
    api_key = api_key or os.environ.get("OPENPAGERANK_V1_API_KEY")
    if not api_key:
        return {"error": "no_api_key", "hint":
                "Create a new OPR key at https://openpagerank.keywordseverywhere.com/docs "
                "and set OPENPAGERANK_V1_API_KEY. Legacy OPENPAGERANK_API_KEY is not used."}
    if not domains:
        return {"error": "no_domains"}
    if len(domains) > 100:
        return {"error": "too_many_domains", "limit": 100,
                "message": "Request at most 100 domains explicitly; no domains were sent."}
    if not api_key.startswith("opr_live_"):
        return {"error": "migration_required", "hint": "Use a newly issued opr_live_ key; legacy keys are not supported."}
    req = urllib.request.Request(OPENPAGERANK_URL,
        data=json.dumps({"domains": domains, "include_history": False}).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json",
                 "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            budgets = _opr_budgets(resp.headers)
    except urllib.error.HTTPError as e:
        try:
            error = json.loads(e.read().decode("utf-8"))
        except (ValueError, UnicodeError):
            error = {}
        detail = error.get("error") or {}
        return {"error": f"http_{e.code}", "error_type": detail.get("type") if isinstance(detail, dict) else None,
                "rate_limit": _opr_budgets(e.headers), "retry_after": e.headers.get("Retry-After"),
                "message": "Open PageRank request failed; check the reported quota or authentication status."}
    except (urllib.error.URLError, TimeoutError) as e:
        return {"error": "transport", "message": str(e)}
    results = {}
    for item in data.get("results", []):
        domain = item.get("domain")
        if domain:
            results[domain] = _opr_row(item, "domain")
        for host in item.get("hosts", []):
            if host.get("host"):
                results[host["host"]] = _opr_row(host, "host")
    for domain in domains:
        if domain.startswith("www.") and domain not in results and domain[4:] in results:
            results[domain] = {**results[domain[4:]], "source_domain": domain[4:]}
    return {"results": results, "rate_limit": budgets, "source": "open_pagerank",
            "as_of": data.get("as_of"), "invalid": data.get("invalid", [])}


def _opr_budgets(headers):
    names = ("X-Domains-Limit", "X-Domains-Remaining", "X-Domains-Reset",
             "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset")
    return {name: headers.get(name) for name in names if headers.get(name) is not None}


def _opr_row(item, scope):
    found = item.get("found") is True
    return {"rank": _to_int(item.get("rank")) if found else None,
            "page_rank_decimal": _to_float(item.get("open_page_rank")) if found else None,
            "page_rank_integer": None, "status": 200 if found else 404,
            "error": None if found else "not_found", "rank_scope": scope,
            "referring_domains": item.get("referring_domains"),
            "referring_hosts": item.get("referring_hosts")}


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------- Tranco ----------

_tranco_dict_cache: dict[str, int] | None = None
_tranco_signature = None


def _ensure_tranco_cache():
    """Download and persist the Tranco top-1M CSV if missing or stale."""
    import time

    if TRANCO_CACHE.exists():
        if time.time() - TRANCO_CACHE.stat().st_mtime < TRANCO_REFRESH_SECONDS:
            return
    TRANCO_CACHE.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        TRANCO_URL,
        headers={"User-Agent": "google-search-console-agent/0.2 (+tranco-fetch)"},
    )
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
        raw = resp.read(50_000_001)
        if len(raw) > 50_000_000:
            raise ValueError("Tranco archive exceeds 50 MB")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        csv_name = next((n for n in z.namelist() if n.endswith(".csv")), None)
        if not csv_name:
            raise RuntimeError("no .csv inside Tranco zip")
        if z.getinfo(csv_name).file_size > 100_000_000:
            raise ValueError("Tranco CSV exceeds 100 MB")
        with z.open(csv_name) as f:
            payload = f.read(100_000_001)
        if len(payload) > 100_000_000:
            raise ValueError("Tranco CSV exceeds 100 MB")
        _parse_tranco(payload.decode("utf-8"))
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=TRANCO_CACHE.parent, prefix=".tranco-",
                                             suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                output.write(payload)
            os.replace(temporary, TRANCO_CACHE)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _parse_tranco(text):
    out = {}
    for line in text.splitlines():
        parts = line.strip().split(",", 1)
        if len(parts) != 2 or not parts[1] or not parts[0].isdigit() or int(parts[0]) < 1:
            raise ValueError("invalid Tranco CSV row")
        out[parts[1].lower()] = int(parts[0])
    if not out:
        raise ValueError("empty Tranco CSV")
    return out


def _load_tranco_dict() -> dict[str, int]:
    global _tranco_dict_cache, _tranco_signature
    _ensure_tranco_cache()
    with TRANCO_CACHE.open(encoding="utf-8") as f:
        stat = os.fstat(f.fileno())
        signature = (str(TRANCO_CACHE), stat.st_mtime_ns, stat.st_size)
        if _tranco_dict_cache is not None and _tranco_signature == signature:
            return _tranco_dict_cache
        out = _parse_tranco(f.read())
    _tranco_dict_cache, _tranco_signature = out, signature
    return out


def tranco_rank(domain: str) -> int | None:
    """Return Tranco's top-1M rank for `domain`, or None if outside the list."""
    return _load_tranco_dict().get(_strip_scheme(domain))


# ---------- High-level helpers ----------

def _tranco_rows(domains: list[str]) -> list[dict]:
    try:
        ranks = {d: tranco_rank(d) for d in domains}
    except Exception as e:
        return [{"domain": d, "tranco_rank": None, "tranco_band": "unavailable",
                 "tranco_error": type(e).__name__, "tranco_message": str(e)} for d in domains]
    return [{"domain": d, "tranco_rank": ranks[d],
             "tranco_band": _tranco_band(ranks[d])} for d in domains]


def _open_pagerank_result(domains: list[str], api_key: str | None) -> dict:
    try:
        return query_open_pagerank(domains, api_key=api_key)
    except Exception as e:
        return {"error": type(e).__name__, "message": str(e)}


def domain_authority(domain: str, api_key: str | None = None) -> dict:
    """Single-domain lookup that combines both data sources."""
    domain = _strip_scheme(domain)
    out = _tranco_rows([domain])[0]
    opr = _open_pagerank_result([domain], api_key)
    if "error" not in opr:
        result = opr["results"].get(domain) or {}
        out["open_pagerank"] = result
        out["open_pagerank_rate_limit"] = opr.get("rate_limit")
        out["open_pagerank_as_of"] = opr.get("as_of")
    else:
        out["open_pagerank_error"] = opr["error"]
        out["open_pagerank_hint"] = opr.get("hint") or opr.get("message")
    return out


def compare_domains(domains: list[str], api_key: str | None = None) -> dict:
    """Compare a list of domains. The first entry is treated as the
    "primary" (your site); the rest are competitors."""
    domains = [_strip_scheme(d) for d in domains]
    out: dict = {"primary": domains[0] if domains else None, "rows": _tranco_rows(domains)}

    opr = _open_pagerank_result(domains, api_key)
    out["open_pagerank_rate_limit"] = opr.get("rate_limit", {})
    out["open_pagerank_as_of"] = opr.get("as_of")
    opr_results = opr.get("results", {}) if "error" not in opr else {}
    if "error" in opr:
        out["open_pagerank_error"] = opr["error"]
        out["open_pagerank_hint"] = opr.get("hint") or opr.get("message")

    for row in out["rows"]:
        opr_row = opr_results.get(row["domain"])
        if opr_row:
            row["open_pagerank_decimal"] = opr_row.get("page_rank_decimal")
            row["open_pagerank_integer"] = opr_row.get("page_rank_integer")
            row["open_pagerank_rank"] = opr_row.get("rank")
            row["open_pagerank_rank_scope"] = opr_row.get("rank_scope")
            row["open_pagerank_status"] = opr_row.get("status")

    return out


def _tranco_band(rank: int | None) -> str:
    if rank is None:
        return "outside_top_1m"
    if rank <= 1_000:
        return "top_1k"
    if rank <= 10_000:
        return "top_10k"
    if rank <= 100_000:
        return "top_100k"
    return "top_1m"


# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(description="Domain authority / backlinks adapter")
    parser.add_argument("--domain", help="Single domain lookup")
    parser.add_argument("--compare", help="Comma-separated list of domains")
    parser.add_argument("--tranco", metavar="DOMAIN", help="Tranco-only lookup")
    parser.add_argument("--api-key", help="New OPR key; overrides OPENPAGERANK_V1_API_KEY for this call")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        if args.tranco:
            rank = tranco_rank(args.tranco)
            out = {"domain": _strip_scheme(args.tranco), "tranco_rank": rank,
                   "tranco_band": _tranco_band(rank)}
        elif args.compare:
            doms = [d.strip() for d in args.compare.split(",") if d.strip()]
            out = compare_domains(doms, api_key=args.api_key)
        elif args.domain:
            out = domain_authority(args.domain, api_key=args.api_key)
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
