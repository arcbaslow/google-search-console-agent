"""
Backlinks / domain-authority adapter.

Two free data sources are bundled:

  1. Open PageRank (Domcop) — domain rank on a 0-10 PR-style scale,
     derived from Common Crawl. Optional: set OPENPAGERANK_API_KEY in
     the environment. Free signup at https://www.domcop.com/openpagerank/.
     1,000 requests/day; up to 100 domains per request.

  2. Tranco top-1M list — a research-grade combined ranking that
     averages Cisco Umbrella, Majestic, Alexa (historic), and others.
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
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

OPENPAGERANK_URL = "https://openpagerank.com/api/v1.0/getPageRank"
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
    """Query Open PageRank for a list of bare domains. Returns a dict keyed
    by domain plus a `rate_limit` block. Returns `{"error": ...}` when no
    API key is configured."""
    api_key = api_key or os.environ.get("OPENPAGERANK_API_KEY")
    if not api_key:
        return {
            "error": "no_api_key",
            "hint": (
                "Set OPENPAGERANK_API_KEY. Free signup at "
                "https://www.domcop.com/openpagerank/ — 1,000 requests/day."
            ),
        }
    if not domains:
        return {"error": "no_domains"}

    qs_parts = [("domains[]", d) for d in domains[:100]]
    url = f"{OPENPAGERANK_URL}?{urllib.parse.urlencode(qs_parts)}"
    req = urllib.request.Request(
        url,
        headers={"API-OPR": api_key, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": f"http_{e.code}", "message": body[:300]}
    except (urllib.error.URLError, TimeoutError) as e:
        return {"error": "transport", "message": str(e)}

    results = {}
    for item in data.get("response", []):
        domain = item.get("domain")
        if not domain:
            continue
        results[domain] = {
            "rank": _to_int(item.get("rank")),
            "page_rank_decimal": _to_float(item.get("page_rank_decimal")),
            "page_rank_integer": _to_int(item.get("page_rank_integer")),
            "status": item.get("status_code"),
            "error": item.get("error") or None,
        }
    return {
        "results": results,
        "rate_limit": data.get("rate_limit", {}),
        "source": "open_pagerank",
    }


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
        raw = resp.read()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        csv_name = next((n for n in z.namelist() if n.endswith(".csv")), None)
        if not csv_name:
            raise RuntimeError("no .csv inside Tranco zip")
        with z.open(csv_name) as f:
            TRANCO_CACHE.write_bytes(f.read())


def _load_tranco_dict() -> dict[str, int]:
    global _tranco_dict_cache
    if _tranco_dict_cache is not None:
        return _tranco_dict_cache
    _ensure_tranco_cache()
    out: dict[str, int] = {}
    with open(TRANCO_CACHE, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(",", 1)
            if len(parts) != 2:
                continue
            rank_s, dom = parts
            try:
                out[dom.lower()] = int(rank_s)
            except ValueError:
                continue
    _tranco_dict_cache = out
    return out


def tranco_rank(domain: str) -> int | None:
    """Return Tranco's top-1M rank for `domain`, or None if outside the list."""
    return _load_tranco_dict().get(_strip_scheme(domain))


# ---------- High-level helpers ----------

def domain_authority(domain: str) -> dict:
    """Single-domain lookup that combines both data sources."""
    domain = _strip_scheme(domain)
    out: dict = {"domain": domain}
    out["tranco_rank"] = tranco_rank(domain)
    out["tranco_band"] = _tranco_band(out["tranco_rank"])
    opr = query_open_pagerank([domain])
    if "error" not in opr:
        result = opr["results"].get(domain) or {}
        out["open_pagerank"] = result
        out["open_pagerank_rate_limit"] = opr.get("rate_limit")
    else:
        out["open_pagerank_error"] = opr["error"]
        out["open_pagerank_hint"] = opr.get("hint")
    return out


def compare_domains(domains: list[str]) -> dict:
    """Compare a list of domains. The first entry is treated as the
    "primary" (your site); the rest are competitors."""
    domains = [_strip_scheme(d) for d in domains]
    out: dict = {"primary": domains[0] if domains else None, "rows": []}

    opr = query_open_pagerank(domains)
    opr_results = opr.get("results", {}) if "error" not in opr else {}
    if "error" in opr:
        out["open_pagerank_error"] = opr["error"]
        out["open_pagerank_hint"] = opr.get("hint")

    for d in domains:
        row = {
            "domain": d,
            "tranco_rank": tranco_rank(d),
        }
        row["tranco_band"] = _tranco_band(row["tranco_rank"])
        opr_row = opr_results.get(d)
        if opr_row:
            row["open_pagerank_decimal"] = opr_row.get("page_rank_decimal")
            row["open_pagerank_integer"] = opr_row.get("page_rank_integer")
            row["open_pagerank_rank"] = opr_row.get("rank")
        out["rows"].append(row)

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
    parser.add_argument("--api-key", help="Override OPENPAGERANK_API_KEY for this call")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        if args.tranco:
            rank = tranco_rank(args.tranco)
            out = {"domain": _strip_scheme(args.tranco), "tranco_rank": rank,
                   "tranco_band": _tranco_band(rank)}
        elif args.compare:
            doms = [d.strip() for d in args.compare.split(",") if d.strip()]
            out = compare_domains(doms)
        elif args.domain:
            if args.api_key:
                os.environ["OPENPAGERANK_API_KEY"] = args.api_key
            out = domain_authority(args.domain)
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
