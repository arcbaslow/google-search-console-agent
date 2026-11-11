"""Tests for the MCP tool set.

Offline. Google HTTP calls go through a recording httplib2 fake (real googleapiclient
request building, so verbs and paths are the real wire values), the PSI and CrUX calls
go through a recording urllib fake, and page and sitemap fetches go through fake
sockets behind the real pinned opener, with a scripted resolver. Every operation is
checked against an explicit allow-list.
"""

import asyncio
import inspect
import io
import ipaddress
import json
import logging
import os
import re
import socket
import ssl
import subprocess
import sys
import types
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import google.auth
import gsc_admin
import gsc_auth
import gsc_crux
import gsc_data
import gsc_mcp
import gsc_psi
import gsc_structured_data
import gsc_utils
import httplib2
import pytest
from google.auth import credentials as google_credentials
from google.auth.exceptions import DefaultCredentialsError, RefreshError, TransportError
from googleapiclient.errors import HttpError
from gsc_utils import ApiReadError
from mcp.server.fastmcp import FastMCP

SITE = "sc-domain:example.com"
PAGE = "https://example.com/products/widget"
# Long and label-free on purpose: the scrubber must catch it without any context.
SENTINEL = "fake-access-" + "A1b2C3d4" * 6
# A fake 39-character Google API key, so it is not caught by the long-token rule alone.
API_KEY = "AIzaSy" + "FakeKeyForTests0123456789abcdefgh"
EXPECTED_TOOLS = {
    "list_sites", "search_analytics", "inspect_url", "list_sitemaps", "page_speed",
    "structured_data", "compare_periods", "crux_history",
}
ERROR_CATEGORIES = {
    "auth_required", "permission_denied", "quota_exceeded", "invalid_argument", "not_found",
    "upstream_error",
}
WRITE_FUNCTIONS = ("add_site", "delete_site", "submit_sitemap", "delete_sitemap")

# Search Analytics queries and URL inspections are POSTs on the wire but only read.
GOOGLE_ALLOWED = (
    ("GET", r"^https://searchconsole\.googleapis\.com/webmasters/v3/sites\?"),
    ("GET", r"^https://searchconsole\.googleapis\.com/webmasters/v3/sites/[^/?]+/sitemaps\?"),
    ("POST", r"^https://searchconsole\.googleapis\.com/webmasters/v3/sites/[^/?]+"
             r"/searchAnalytics/query\?"),
    ("POST", r"^https://searchconsole\.googleapis\.com/v1/urlInspection/index:inspect\?"),
)
# PSI is a GET. CrUX queries are POSTs that only read. With an API key the key is the only
# query parameter on the CrUX endpoints.
URLLIB_ALLOWED = (
    ("GET", r"^https://www\.googleapis\.com/pagespeedonline/v5/runPagespeed\?"),
    ("POST", r"^https://chromeuxreport\.googleapis\.com/v1/records:queryRecord(\?key=[^&]+)?$"),
    ("POST", r"^https://chromeuxreport\.googleapis\.com/v1/records:queryHistoryRecord"
             r"(\?key=[^&]+)?$"),
)
# Page and sitemap fetches are plain GETs.
SOCKET_ALLOWED = (
    ("GET", r"^https?://[a-z0-9.]+/(sitemap\.xml|sitemap_index\.xml|child\.xml|products/[a-z]+)$"),
)

SEARCH_ROWS = [{"keys": ["widgets", "https://example.com/a"], "clicks": 10,
                "impressions": 100, "ctr": 0.1, "position": 3.2}]
SITEMAPS = [
    {"path": "https://example.com/sitemap.xml", "type": "sitemap", "isPending": False,
     "isSitemapsIndex": False, "lastSubmitted": "2026-09-01T00:00:00Z",
     "lastDownloaded": "2026-10-01T00:00:00Z", "errors": "0", "warnings": "0",
     "contents": [{"type": "web", "submitted": "10", "indexed": "0"}]},
    {"path": "https://example.com/news.xml", "errors": "3", "warnings": "2"},
    {"path": "https://example.com/blog.xml", "errors": "0", "warnings": "1"},
]
PSI = {
    "id": PAGE,
    "analysisUTCTimestamp": "2026-10-04T10:00:00.000Z",
    "lighthouseResult": {
        "categories": {"performance": {"score": 0.91}, "seo": {"score": 1.0}},
        "audits": {
            "largest-contentful-paint": {"numericValue": 2400.0},
            "cumulative-layout-shift": {"numericValue": 0.05},
            "total-blocking-time": {"numericValue": 120.0},
            "first-contentful-paint": {"numericValue": 1100.0},
            "speed-index": {"numericValue": 2000.0},
            "bulky-audit": {"details": {"items": ["x" * 200] * 100}},
        },
    },
    "loadingExperience": {
        "overall_category": "FAST",
        "metrics": {"LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2300, "category": "FAST"}},
    },
}
CRUX_RECORD = {"record": {
    "collectionPeriod": {"firstDate": {"year": 2026, "month": 9, "day": 6}},
    "metrics": {"largest_contentful_paint": {"percentiles": {"p75": 2400}},
                "cumulative_layout_shift": {"percentiles": {"p75": "0.05"}}},
}}
CRUX_HISTORY = {"record": {
    "collectionPeriods": [{"lastDate": {"year": 2026, "month": 9, "day": d}} for d in (6, 13, 20)],
    "metrics": {"largest_contentful_paint": {
        "percentilesTimeseries": {"p75s": [2400, 2500, "NaN"]}}},
}}
SITEMAP_XML = (
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://example.com/products/widget</loc></url>"
    "<url><loc>https://example.com/products/gadget</loc></url></urlset>"
)
PUBLIC = "93.184.216.34"
HOSTS = {
    "example.com": [PUBLIC],
    "localhost": ["127.0.0.1"],
    "internal.example": ["10.0.0.9"],
    "mapped.example": ["::ffff:127.0.0.1"],
}


def jsonld_page(blocks=1):
    scripts = "".join(
        '<script type="application/ld+json">'
        + json.dumps({"@context": "https://schema.org", "@type": "Recipe", "name": f"R{i}"})
        + "</script>" for i in range(blocks))
    return f"<html><head>{scripts}</head><body></body></html>"


def as_json(payload):
    return json.dumps(payload).encode()


def default_payload(url):
    path = urlsplit(url).path
    if "googleapis.com/webmasters" in url or "urlInspection" in url:
        if path.endswith("/sites"):
            return as_json({"siteEntry": [
                {"siteUrl": SITE, "permissionLevel": "siteOwner"},
                {"siteUrl": "https://example.com/", "permissionLevel": "siteFullUser"},
                {"siteUrl": "sc-domain:example.org", "permissionLevel": "siteRestrictedUser"},
            ]})
        if path.endswith("/sitemaps"):
            return as_json({"sitemap": SITEMAPS})
        if path.endswith("/searchAnalytics/query"):
            return as_json({"rows": SEARCH_ROWS, "responseAggregationType": "byProperty"})
        if path.endswith("index:inspect"):
            return as_json({"inspectionResult": {"indexStatusResult": {
                "verdict": "PASS", "coverageState": "Submitted and indexed"}}})
    if "runPagespeed" in url:
        return as_json(PSI)
    if path.endswith("/records:queryRecord"):
        return as_json(CRUX_RECORD)
    if path.endswith("/records:queryHistoryRecord"):
        return as_json(CRUX_HISTORY)
    if url.endswith("/sitemap.xml"):
        return SITEMAP_XML.encode()
    if "/products/" in url:
        return jsonld_page().encode()
    return None


class FakeCredentials(google_credentials.Credentials):
    def __init__(self):
        super().__init__()
        self.token = SENTINEL
        self.expiry = None

    def refresh(self, request):
        raise AssertionError("fake credentials must not refresh")


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        return self.payload if size is None or size < 0 else self.payload[:size]


class Recorder:
    def __init__(self):
        self.operations = []
        self.bodies = []
        self.violations = []
        self.forbidden_calls = []
        self.credential_writes = []
        self.auth_headers = []
        self.sleeps = []
        self.respond = None
        self.page = jsonld_page()
        self.dns = {}
        self.resolutions = []
        self.connections = []
        self.tls_hosts = []
        self.sent = []
        self.urllib_headers = []

    def record(self, channel, method, url, body=None):
        self.operations.append((channel, method, url))
        if body:
            self.bodies.append((method, url, json.loads(body)))
        allowed = {"google": GOOGLE_ALLOWED, "urllib": URLLIB_ALLOWED,
                   "socket": SOCKET_ALLOWED}[channel]
        if not any(method == verb and re.match(pattern, url) for verb, pattern in allowed):
            self.violations.append((channel, method, url))

    def answer(self, channel, method, url):
        if self.respond is not None:
            custom = self.respond(channel, method, url)
            if custom is not None:
                return custom
        if "/products/" in url:
            return 200, {}, self.page.encode()
        payload = default_payload(url)
        if payload is None:
            return 404, {}, as_json({"error": {"code": 404, "message": "not found"}})
        return 200, {}, payload

    def paths(self, channel):
        return {(m, urlsplit(u).path) for c, m, u in self.operations if c == channel}

    def requests(self, fragment):
        return [b for _m, u, b in self.bodies if fragment in u]


_REAL_CONNECT = socket.socket.connect


@pytest.fixture(autouse=True)
def loopback_for_event_loops(monkeypatch, offline_only):
    """On Windows asyncio builds its self-pipe with a loopback connect, which the shared
    offline guard blocks. Allow loopback only; every other connect still fails."""
    def connect(self, address):
        if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1")):
            raise AssertionError("Mock network and credential discovery in tests")
        return _REAL_CONNECT(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)


@pytest.fixture
def rec(monkeypatch):
    recorder = Recorder()
    credentials = FakeCredentials()

    def get_credentials(write=False):
        recorder.credential_writes.append(write)
        return credentials

    def google_request(self, uri, method="GET", body=None, headers=None, *args, **kwargs):
        recorder.record("google", method, uri, body)
        recorder.auth_headers.append((headers or {}).get("authorization"))
        status, extra, payload = recorder.answer("google", method, uri)
        head = {"status": str(status), "content-type": "application/json", **extra}
        return httplib2.Response(head), payload

    def urlopen(request, timeout=None, *args, **kwargs):
        method, url = request.get_method(), request.full_url
        recorder.record("urllib", method, url, request.data)
        recorder.auth_headers.append(request.get_header("Authorization"))
        recorder.urllib_headers.append({k.lower(): v for k, v in request.header_items()})
        status, extra, payload = recorder.answer("urllib", method, url)
        if status >= 400:
            raise urllib.error.HTTPError(url, status, "error", extra, io.BytesIO(payload))
        return FakeResponse(payload)

    def getaddrinfo(host, port, *args, **kwargs):
        recorder.resolutions.append(host)
        try:
            ipaddress.ip_address(host)
            addresses = [host]
        except ValueError:
            scripted = recorder.dns.get(host)
            if scripted:
                # One scripted answer per lookup, the last one repeating.
                addresses = scripted[min(recorder.resolutions.count(host), len(scripted)) - 1]
            else:
                addresses = HOSTS.get(host)
        if not addresses:
            raise socket.gaierror("unknown host")
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 (a, port)) for a in addresses]

    class FakeSocket:
        def __init__(self, family=-1, kind=-1, proto=-1):
            self.tls_host = None
            self.request = b""

        def settimeout(self, timeout):
            pass

        def bind(self, address):
            pass

        def setsockopt(self, *args):
            pass

        def connect(self, sockaddr):
            recorder.connections.append(tuple(sockaddr[:2]))

        def sendall(self, data, *args):
            self.request += data

        def makefile(self, *args, **kwargs):
            recorder.sent.append(self.request)
            lines = self.request.partition(b"\r\n\r\n")[0].decode("latin-1").split("\r\n")
            method, target, _version = lines[0].split(" ")
            host = next(v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:])
                        if k.lower() == "host")
            url = f"{'https' if self.tls_host else 'http'}://{host}{target}"
            recorder.record("socket", method, url)
            status, extra, payload = recorder.answer("socket", method, url)
            head = "".join(f"{k}: {v}\r\n" for k, v in extra.items())
            return io.BytesIO(
                f"HTTP/1.1 {status} X\r\nContent-Length: {len(payload)}\r\n"
                f"Connection: close\r\n{head}\r\n".encode() + payload)

        def close(self):
            pass

    def wrap_socket(context, sock, *args, server_hostname=None, **kwargs):
        sock.tls_host = server_hostname
        recorder.tls_hosts.append(server_hostname)
        return sock

    def forbidden(name):
        def refuse(*args, **kwargs):
            recorder.forbidden_calls.append(name)
            raise AssertionError(f"{name} must never be called")
        return refuse

    for module in (gsc_admin, gsc_data, gsc_psi, gsc_crux):
        monkeypatch.setattr(module, "get_credentials", get_credentials)
    monkeypatch.setattr(httplib2.Http, "request", google_request)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    # Only the socket name gsc_mcp sees is swapped; asyncio on Windows needs the real module.
    monkeypatch.setattr(gsc_mcp, "socket", types.SimpleNamespace(
        getaddrinfo=getaddrinfo, socket=FakeSocket, SOCK_STREAM=socket.SOCK_STREAM))
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap_socket)
    monkeypatch.setattr(gsc_utils.time, "sleep", recorder.sleeps.append)
    for name in WRITE_FUNCTIONS:
        monkeypatch.setattr(gsc_admin, name, forbidden(name))
    return recorder


TOOL_FNS = {spec.name: spec.fn for spec in gsc_mcp.TOOLS}
SWEEP = {
    "list_sites": [{}],
    "search_analytics": [
        {"site_url": SITE, "dimensions": ["query", "page"], "start_date": "2026-09-01",
         "end_date": "2026-09-07", "filter_expr": "query CONTAINS 'widget'"},
        {"site_url": SITE, "start_date": "2026-09-08", "end_date": "2026-09-14",
         "compare_previous": True},
    ],
    "inspect_url": [{"site_url": SITE, "url": PAGE}],
    "list_sitemaps": [{"site_url": SITE}],
    "page_speed": [
        {"url": PAGE},
        {"url": PAGE, "source": "crux"},
        {"url": PAGE, "source": "crux_history", "scope": "origin"},
    ],
    "structured_data": [{"url": PAGE}, {"site_url": SITE}],
    "compare_periods": [
        {"site_url": SITE, "date_from": "2026-09-08", "date_to": "2026-09-14",
         "compare_from": "2026-09-01", "compare_to": "2026-09-07", "dimension": "page"},
    ],
    "crux_history": [{"url_or_origin": "https://example.com"}, {"url_or_origin": PAGE}],
}


def run_sweep():
    return {name: [TOOL_FNS[name](**kwargs) for kwargs in calls] for name, calls in SWEEP.items()}


def structured(result):
    if isinstance(result, tuple):
        result = result[1]
    if isinstance(result, dict):
        return result
    return json.loads(result[0].text)


def build_server(prefix=""):
    server = FastMCP("test")
    gsc_mcp.register(server, prefix)
    return server



def test_inventory_lists_exactly_the_read_only_tools():
    tools = asyncio.run(build_server().list_tools())
    assert {t.name for t in tools} == EXPECTED_TOOLS
    assert len(tools) == 8
    for tool in tools:
        assert tool.title
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.openWorldHint is True
        assert tool.description


def test_register_applies_prefix_and_returns_the_count():
    server = FastMCP("test")
    assert gsc_mcp.register(server, "gsc_") == len(gsc_mcp.TOOLS) == 8
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"gsc_" + n for n in EXPECTED_TOOLS}


def test_register_and_the_table_describe_one_inventory():
    tools = {t.name: t for t in asyncio.run(build_server().list_tools())}
    assert set(tools) == {spec.name for spec in gsc_mcp.TOOLS}
    for spec in gsc_mcp.TOOLS:
        assert tools[spec.name].title == spec.title
        assert tools[spec.name].description == spec.description


def test_inspect_url_description_states_the_quota():
    description = next(s for s in gsc_mcp.TOOLS if s.name == "inspect_url").description
    assert "2,000 inspections per day" in description
    assert "600 per minute" in description


@pytest.mark.parametrize("name,keywords", [
    ("list_sites", ["Search Console", "properties"]),
    ("search_analytics", ["search analytics", "clicks", "impressions"]),
    ("inspect_url", ["URL Inspection", "index status"]),
    ("list_sitemaps", ["sitemaps", "error", "warning"]),
    ("page_speed", ["PageSpeed", "Core Web Vitals", "Chrome UX Report"]),
    ("structured_data", ["JSON-LD", "structured data"]),
    ("compare_periods", ["search analytics", "periods"]),
    ("crux_history", ["Chrome UX Report", "Core Web Vitals"]),
])
def test_first_sentence_carries_the_search_keywords(name, keywords):
    description = next(s for s in gsc_mcp.TOOLS if s.name == name).description
    first = description.split(". ")[0].lower()
    assert all(k.lower() in first for k in keywords)


def test_search_analytics_keeps_the_connector_parameter_names():
    tools = {t.name: t for t in asyncio.run(build_server().list_tools())}
    props = tools["search_analytics"].inputSchema["properties"]
    assert {"site_url", "start_date", "end_date", "dimensions", "limit"} <= set(props)
    for name in ("list_sites", "list_sitemaps", "search_analytics", "structured_data"):
        assert "limit" in tools[name].inputSchema["properties"]


def test_tool_runs_through_the_sdk(rec):
    server = build_server("gsc_")
    out = structured(asyncio.run(server.call_tool("gsc_list_sites", {})))
    assert out["rows_returned"] == 3
    assert out["sites"][0] == {"site_url": SITE, "permission_level": "siteOwner"}


def test_read_tools_never_reference_write_functions_or_scopes():
    read_part = "\n".join(inspect.getsource(spec.fn) for spec in gsc_mcp.TOOLS)
    assert all(f"def {spec.fn.__name__}(" in read_part for spec in gsc_mcp.TOOLS)
    markers = ("_confirm_write", "SCOPES_WRITE", "write=True", "_send_delete", "_confirmed",
               "_get_service", "_WRITE_SCOPE", ".execute(", "_issue(", "_invalidate_inventory")
    for name in WRITE_FUNCTIONS + markers:
        assert name not in read_part



def test_every_tool_only_makes_allow_listed_calls(rec, tmp_cache_dir):
    assert set(SWEEP) == {spec.name for spec in gsc_mcp.TOOLS}
    results = run_sweep()
    for name, outputs in results.items():
        for out in outputs:
            assert "error" not in out, (name, out)
            assert "rows_returned" in out and "complete" in out
            json.dumps(out)
    assert rec.violations == []
    assert rec.forbidden_calls == []
    assert set(rec.credential_writes) == {False}
    assert rec.paths("google") == {
        ("GET", "/webmasters/v3/sites"),
        ("GET", "/webmasters/v3/sites/sc-domain%3Aexample.com/sitemaps"),
        ("POST", "/webmasters/v3/sites/sc-domain%3Aexample.com/searchAnalytics/query"),
        ("POST", "/v1/urlInspection/index:inspect"),
    }
    assert rec.paths("urllib") == {
        ("GET", "/pagespeedonline/v5/runPagespeed"),
        ("POST", "/v1/records:queryRecord"),
        ("POST", "/v1/records:queryHistoryRecord"),
    }
    assert rec.paths("socket") == {
        ("GET", "/products/widget"),
        ("GET", "/products/gadget"),
        ("GET", "/sitemap.xml"),
    }
    assert set(rec.connections) == {(PUBLIC, 443)}
    cache_dir = tmp_cache_dir / "gsc-cache"
    written = [p for p in tmp_cache_dir.rglob("*") if p.is_file()]
    assert written and all(cache_dir in p.parents for p in written)


def test_write_functions_are_never_called_by_any_tool(rec):
    run_sweep()
    assert rec.forbidden_calls == []
    for name in WRITE_FUNCTIONS:
        with pytest.raises(AssertionError):
            getattr(gsc_admin, name)()
    assert rec.forbidden_calls == list(WRITE_FUNCTIONS)


def test_search_analytics_sends_the_requested_query(rec):
    TOOL_FNS["search_analytics"](**SWEEP["search_analytics"][0])
    (body,) = rec.requests("searchAnalytics/query")
    assert body["dimensions"] == ["query", "page"]
    assert (body["startDate"], body["endDate"]) == ("2026-09-01", "2026-09-07")
    assert body["rowLimit"] == 100 and body["startRow"] == 0
    assert body["dimensionFilterGroups"][0]["filters"][0] == {
        "dimension": "query", "operator": "contains", "expression": "widget"}


def test_search_analytics_dimension_defaults_and_totals(rec):
    search = TOOL_FNS["search_analytics"]
    search(site_url=SITE, start_date="2026-09-01", end_date="2026-09-02")
    search(site_url=SITE, start_date="2026-09-01", end_date="2026-09-02", dimensions=[])
    default, totals = rec.requests("searchAnalytics/query")
    assert default["dimensions"] == ["query"]
    assert totals["dimensions"] == []


def test_compare_previous_makes_two_aggregate_queries(rec):
    out = TOOL_FNS["search_analytics"](**SWEEP["search_analytics"][1])
    current, previous = rec.requests("searchAnalytics/query")
    assert (current["startDate"], current["endDate"]) == ("2026-09-08", "2026-09-14")
    assert (previous["startDate"], previous["endDate"]) == ("2026-09-01", "2026-09-07")
    assert current["dimensions"] == [] and current["rowLimit"] == 1
    assert out["comparison_status"] == "ok"
    assert out["changes"]["clicks_change_pct"] == 0.0
    assert out["rows_returned"] == 2 and out["complete"] is True


@pytest.mark.parametrize("kwargs", [
    {"compare_previous": True},
    {"compare_previous": True, "start_date": "2026-09-08"},
    {"compare_previous": True, "start_date": "2026-09-08", "end_date": "2026-09-14",
     "dimensions": ["query"]},
    {"compare_previous": True, "start_date": "2026-09-08", "end_date": "2026-09-14",
     "start_row": 5},
])
def test_compare_previous_rejects_grouped_or_unbounded_input(rec, kwargs):
    out = TOOL_FNS["search_analytics"](site_url=SITE, **kwargs)
    assert out["error"] == "invalid_argument"
    assert rec.operations == []


def test_search_analytics_pages_with_complete_and_next_start_row(rec):
    rows = [{"keys": [f"q{i}"], "clicks": i, "impressions": 10, "ctr": 0.1, "position": 1.0}
            for i in range(3)]
    rec.respond = lambda c, m, u: (
        (200, {}, as_json({"rows": rows})) if "searchAnalytics" in u else None)
    search = TOOL_FNS["search_analytics"]
    dates = {"start_date": "2026-09-01", "end_date": "2026-09-07"}
    full = search(site_url=SITE, limit=3, start_row=10, **dates)
    assert (full["rows_returned"], full["complete"], full["next_start_row"]) == (3, False, 13)
    short = search(site_url=SITE, limit=4, start_row=10, **dates)
    assert (short["rows_returned"], short["complete"]) == (3, True)
    assert "next_start_row" not in short


def test_search_analytics_scrubs_pii_from_rows(rec):
    row = {"keys": ["call john@example.com now"], "clicks": 1, "impressions": 2, "ctr": 0.5,
           "position": 1.0}
    rec.respond = lambda c, m, u: (
        (200, {}, as_json({"rows": [row]})) if "searchAnalytics" in u else None)
    out = TOOL_FNS["search_analytics"](site_url=SITE, dimensions=["query"], days=7)
    assert out["rows"][0]["query"] == "call [email-redacted] now"


def test_list_sites_is_bounded(rec):
    out = TOOL_FNS["list_sites"](limit=2)
    assert (out["rows_returned"], out["sites_total"], out["complete"]) == (2, 3, False)
    assert TOOL_FNS["list_sites"](limit=3)["complete"] is True


def test_list_sitemaps_reports_counts_worst_first_and_bounded(rec):
    out = TOOL_FNS["list_sitemaps"](site_url=SITE)
    assert [s["path"].rsplit("/", 1)[1] for s in out["sitemaps"]] == [
        "news.xml", "blog.xml", "sitemap.xml"]
    assert out["sitemaps"][0]["errors"] == 3 and out["sitemaps"][0]["warnings"] == 2
    assert (out["errors_total"], out["warnings_total"], out["sitemaps_total"]) == (3, 3, 3)
    assert out["complete"] is True
    short = TOOL_FNS["list_sitemaps"](site_url="example.com", limit=1)
    assert short["site_url"] == SITE
    assert (short["rows_returned"], short["complete"]) == (1, False)
    assert short["sitemaps"][0]["path"].endswith("news.xml")


def test_inspect_url_returns_the_inspection(rec):
    out = TOOL_FNS["inspect_url"](site_url=SITE, url=PAGE, language_code="en-US")
    assert out["inspectionResult"]["indexStatusResult"]["verdict"] == "PASS"
    (body,) = rec.requests("index:inspect")
    assert body == {"inspectionUrl": PAGE, "siteUrl": SITE, "languageCode": "en-US"}


def test_page_speed_psi_drops_the_raw_payload(rec):
    out = TOOL_FNS["page_speed"](url=PAGE, strategy="desktop")
    assert "raw" not in out
    assert out["lh_performance_score"] == 0.91
    assert out["lab"]["lcp_s"] == 2.4
    assert out["field"]["lcp_p75_ms"] == 2300
    assert len(json.dumps(out)) < 3000
    (_c, _m, url), = rec.operations
    assert "strategy=desktop" in url


def test_page_speed_crux_targets_url_or_origin(rec):
    speed = TOOL_FNS["page_speed"]
    speed(url="https://example.com:8443/a/b?x=1", source="crux", form_factor="PHONE")
    speed(url=PAGE, source="crux_history", scope="origin", limit=7)
    record, history = (b for _m, u, b in rec.bodies)
    assert record == {"formFactor": "PHONE", "url": "https://example.com:8443/a/b?x=1"}
    assert history == {"collectionPeriodCount": 7, "origin": "https://example.com"}


def test_page_speed_history_counts_periods_and_nulls_missing_values(rec):
    out = TOOL_FNS["page_speed"](url=PAGE, source="crux_history")
    assert out["rows_returned"] == 3
    assert out["history"]["lcp_p75_ms"] == [2400.0, 2500.0, None]
    assert rec.requests("queryHistoryRecord")[0]["collectionPeriodCount"] == 25


def test_page_speed_crux_without_data_is_a_result_not_an_error(rec):
    rec.respond = lambda c, m, u: (404, {}, b"no data") if "chromeux" in u else None
    out = TOOL_FNS["page_speed"](url=PAGE, source="crux")
    assert out["status"] == "no_data" and out["rows_returned"] == 0


def test_structured_data_single_url_truncates_blocks(rec):
    rec.page = jsonld_page(blocks=60)
    out = TOOL_FNS["structured_data"](url=PAGE)
    assert out["block_count"] == 60
    assert len(out["blocks"]) == out["rows_returned"] == gsc_mcp.STRUCTURED_BLOCKS_MAX
    assert out["complete"] is False
    assert out["verdicts"] == {"fail": 60}


def test_structured_data_sample_keeps_counts_not_block_detail(rec):
    out = TOOL_FNS["structured_data"](site_url="example.com", limit=5)
    assert out["rows_returned"] == len(out["per_url"]) == 2
    assert all("blocks" not in entry and entry["block_count"] == 1 for entry in out["per_url"])
    assert out["complete"] is True
    assert out["sampling"]["exhaustive"] is False
    assert out["rollup"]["urls_analyzed"] == 2


def test_structured_data_sample_smaller_than_discovery_is_incomplete(rec):
    out = TOOL_FNS["structured_data"](site_url=SITE, limit=1)
    assert out["rows_returned"] == 1 and out["complete"] is False


@pytest.mark.parametrize("tool,kwargs", [
    ("list_sites", {"limit": 0}),
    ("list_sites", {"limit": 501}),
    ("list_sites", {"limit": True}),
    ("list_sites", {"limit": "5"}),
    ("list_sitemaps", {"site_url": SITE, "limit": 201}),
    ("list_sitemaps", {"site_url": "  "}),
    ("search_analytics", {"site_url": SITE, "limit": 501}),
    ("search_analytics", {"site_url": None}),
    ("search_analytics", {"site_url": SITE, "dimensions": ["nonsense"]}),
    ("search_analytics", {"site_url": SITE, "start_date": "2026-09-01"}),
    ("search_analytics", {"site_url": SITE, "start_date": "09/01", "end_date": "09/02"}),
    ("search_analytics", {"site_url": SITE, "filter_expr": "gibberish"}),
    ("search_analytics", {"site_url": SITE, "search_type": "carrier-pigeon"}),
    ("inspect_url", {"site_url": SITE, "url": None}),
    ("inspect_url", {"site_url": SITE, "url": "example.com/page"}),
    ("inspect_url", {"site_url": SITE, "url": "ftp://example.com/page"}),
    ("page_speed", {"url": 123}),
    ("page_speed", {"url": PAGE, "source": "lighthouse-ci"}),
    ("page_speed", {"url": PAGE, "scope": "domain"}),
    ("page_speed", {"url": PAGE, "strategy": "tablet"}),
    ("page_speed", {"url": PAGE, "source": "crux", "form_factor": "WATCH"}),
    ("page_speed", {"url": PAGE, "source": "crux_history", "limit": 41}),
    ("structured_data", {}),
    ("structured_data", {"url": PAGE, "site_url": SITE}),
    ("structured_data", {"site_url": SITE, "limit": 26}),
])
def test_invalid_arguments_are_rejected_before_any_request(rec, tool, kwargs):
    out = TOOL_FNS[tool](**kwargs)
    assert out["error"] == "invalid_argument" and out["hint"]
    assert rec.operations == []



@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://example.com/x",
    "http://127.0.0.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://[::ffff:7f00:1]/",
    "http://10.0.0.5:8080/",
    "http://localhost/",
    "http://internal.example/",
    "http://mapped.example/",
    "http://user:secret@example.com/",
    "https://no-such-host.invalid/",
])
def test_structured_data_never_fetches_non_public_or_unsafe_urls(rec, url):
    out = TOOL_FNS["structured_data"](url=url)
    assert out["error"] == "invalid_argument"
    assert rec.operations == []


@pytest.mark.parametrize("site_url", [
    "http://10.0.0.5/", "sc-domain:localhost", "https://internal.example/blog/",
])
def test_structured_data_sample_never_fetches_non_public_properties(rec, site_url):
    out = TOOL_FNS["structured_data"](site_url=site_url)
    assert out["error"] == "invalid_argument"
    assert rec.operations == []


def test_structured_data_fetch_failure_and_missing_sitemap_use_the_contract(rec):
    rec.respond = lambda c, m, u: (503, {}, b"down") if c == "socket" else None
    failed = TOOL_FNS["structured_data"](url=PAGE)
    assert failed["error"] == "upstream_error" and failed["url"] == PAGE
    missing = TOOL_FNS["structured_data"](site_url=SITE)
    assert missing["error"] == "not_found"
    assert missing["sampling"]["sitemap_requests"] == 2



INDEX_XML = (
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<sitemap><loc>http://10.0.0.5/x.xml</loc></sitemap>"
    "<sitemap><loc>http://internal.example/y.xml</loc></sitemap>"
    "<sitemap><loc>https://example.com/child.xml</loc></sitemap></sitemapindex>"
)
URLSET = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{}</urlset>'


def serve(rec, pages):
    """Answer these exact page URLs over the socket channel; everything else as default."""
    def respond(channel, method, url):
        if channel == "socket" and url in pages:
            return 200, {}, pages[url].encode()
    rec.respond = respond


def redirect_page_to(target):
    def respond(channel, method, url):
        if channel == "socket" and url == PAGE:
            return 302, {"Location": target}, b""
    return respond


@pytest.mark.parametrize("target", [
    "http://127.0.0.1:8421/",
    "http://[::1]:8421/",
    "http://[::ffff:7f00:1]/",
    "http://localhost:8421/",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/",
    "http://internal.example/admin",
    "http://mapped.example/",
    "ftp://internal.example/x",
    "file:///etc/passwd",
])
def test_redirect_from_a_public_page_to_a_non_public_target_is_refused(rec, target):
    rec.respond = redirect_page_to(target)
    out = TOOL_FNS["structured_data"](url=PAGE)
    assert out["error"] == "upstream_error" and out["url"] == PAGE
    assert [op[2] for op in rec.operations] == [PAGE]
    assert rec.connections == [(PUBLIC, 443)]
    assert rec.violations == []


def test_redirect_between_public_pages_is_still_followed(rec):
    rec.respond = redirect_page_to("https://example.com/products/gadget")
    out = TOOL_FNS["structured_data"](url=PAGE)
    assert "error" not in out and out["block_count"] == 1
    assert [op[2] for op in rec.operations] == [PAGE, "https://example.com/products/gadget"]
    assert rec.connections == [(PUBLIC, 443)] * 2


def test_sitemap_index_children_on_private_addresses_are_never_connected(rec):
    child = URLSET.format("<url><loc>https://example.com/products/widget</loc></url>")
    serve(rec, {"https://example.com/sitemap.xml": INDEX_XML,
                "https://example.com/child.xml": child})
    out = TOOL_FNS["structured_data"](site_url=SITE)
    assert out["rows_returned"] == 1 and out["complete"] is False
    issues = out["sampling"]["issues"]
    assert {i["url"] for i in issues} == {"http://10.0.0.5/x.xml", "http://internal.example/y.xml"}
    assert all(i["error"] == "fetch_failed_or_empty" for i in issues)
    assert set(rec.connections) == {(PUBLIC, 443)}
    assert rec.violations == []


def test_sampled_subdomain_resolving_to_a_private_address_is_not_fetched(rec):
    rec.dns["intranet.example.com"] = [["10.0.0.9"]]
    urlset = URLSET.format("<url><loc>https://intranet.example.com/products/a</loc></url>"
                           "<url><loc>https://example.com/products/b</loc></url>")
    serve(rec, {"https://example.com/sitemap.xml": urlset})
    out = TOOL_FNS["structured_data"](site_url=SITE)
    failed = [e for e in out["per_url"] if e.get("error")]
    assert [e["url"] for e in failed] == ["https://intranet.example.com/products/a"]
    assert out["rollup"]["fetch_failures"] == 1 and out["rollup"]["urls_analyzed"] == 1
    assert "intranet.example.com" in rec.resolutions
    assert set(rec.connections) == {(PUBLIC, 443)}


def test_rebinding_resolver_cannot_reach_a_private_address(rec):
    # The early check sees the public answer, the connection's own lookup the private one.
    rec.dns["rebind.example"] = [[PUBLIC], ["10.0.0.9"]]
    out = TOOL_FNS["structured_data"](url="https://rebind.example/products/widget")
    assert out["error"] == "upstream_error"
    assert rec.resolutions.count("rebind.example") == 2
    assert rec.connections == []


def test_connection_uses_the_validated_address_and_keeps_the_hostname_for_tls(rec):
    # A third lookup would see a private address; there must not be one.
    rec.dns["pin.example"] = [[PUBLIC], [PUBLIC], ["10.0.0.9"]]
    out = TOOL_FNS["structured_data"](url="https://pin.example/products/widget")
    assert "error" not in out
    assert rec.connections == [(PUBLIC, 443)]
    assert rec.resolutions.count("pin.example") == 2
    assert rec.tls_hosts == ["pin.example"]
    assert any(b"Host: pin.example" in request for request in rec.sent)


def test_every_resolved_address_must_be_public(rec):
    rec.dns["split.example"] = [[PUBLIC, "10.0.0.9"]]
    early = TOOL_FNS["structured_data"](url="https://split.example/products/widget")
    assert early["error"] == "invalid_argument" and rec.connections == []
    rec.respond = redirect_page_to("http://split.example/")
    later = TOOL_FNS["structured_data"](url=PAGE)
    assert later["error"] == "upstream_error"
    assert rec.connections == [(PUBLIC, 443)]


def test_plain_http_pages_connect_to_the_validated_address_without_tls(rec):
    out = TOOL_FNS["structured_data"](url="http://example.com/products/widget")
    assert "error" not in out
    assert rec.connections == [(PUBLIC, 80)] and rec.tls_hosts == []


def test_proxy_environment_is_ignored(rec, monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
                 "all_proxy"):
        monkeypatch.setenv(name, "http://proxy.invalid:3128")
    out = TOOL_FNS["structured_data"](url=PAGE)
    assert "error" not in out
    assert "proxy.invalid" not in rec.resolutions
    assert rec.connections == [(PUBLIC, 443)]


@pytest.mark.parametrize("url", [
    "file:///etc/hosts", "ftp://example.com/x", "data:text/plain,hi", "gopher://example.com/",
])
def test_guarded_opener_speaks_only_http_and_https(rec, url):
    with pytest.raises(urllib.error.URLError):
        gsc_mcp._guarded_opener().open(url, timeout=5)
    assert rec.connections == [] and rec.resolutions == []


def test_credentials_are_never_sent_to_fetched_pages(rec):
    TOOL_FNS["structured_data"](url=PAGE)
    TOOL_FNS["structured_data"](site_url=SITE)
    assert rec.sent
    for request in rec.sent:
        assert SENTINEL.encode() not in request and b"authorization" not in request.lower()



def api_error(status, body=b"{}", headers=None):
    return ApiReadError(gsc_utils.http_error_details("GSC", status, body, headers or {}))


def http_error(status, body=b"{}"):
    return HttpError(httplib2.Response({"status": str(status)}), body)


ERROR_CASES = [
    (gsc_auth.AuthRequiredError("No credentials found. Run gcloud ..."), "auth_required"),
    (RefreshError("invalid_grant: Token has been expired or revoked."), "auth_required"),
    (RuntimeError("Could not obtain access token from credentials"), "auth_required"),
    (api_error(401), "auth_required"),
    (api_error(403), "permission_denied"),
    (api_error(403, b'{"error": {"errors": [{"reason": "dailyLimitExceeded"}]}}'),
     "quota_exceeded"),
    (api_error(429, headers={"Retry-After": "30"}), "quota_exceeded"),
    (api_error(400), "invalid_argument"),
    (api_error(404), "not_found"),
    (api_error(500), "upstream_error"),
    (api_error(503), "upstream_error"),
    (api_error(418), "upstream_error"),
    (http_error(403), "permission_denied"),
    (http_error(404), "not_found"),
    (http_error(429), "quota_exceeded"),
    (ValueError("limit must be an integer between 1 and 500"), "invalid_argument"),
    (RuntimeError("boom"), "upstream_error"),
    (OSError("disk full"), "upstream_error"),
    (TimeoutError("timed out"), "upstream_error"),
    (TransportError("network down"), "upstream_error"),
]
ADAPTERS = {
    "list_sites": (gsc_admin, "list_sites", {}),
    "search_analytics": (gsc_data, "query", {"site_url": SITE}),
    "inspect_url": (gsc_admin, "inspect_url", {"site_url": SITE, "url": PAGE}),
    "list_sitemaps": (gsc_admin, "list_sitemaps", {"site_url": SITE}),
    "page_speed": (gsc_psi, "run_psi", {"url": PAGE}),
    "structured_data": (gsc_structured_data, "analyze_url", {"url": PAGE}),
    "compare_periods": (gsc_data, "query", {
        "site_url": SITE, "date_from": "2026-09-08", "date_to": "2026-09-14",
        "compare_from": "2026-09-01", "compare_to": "2026-09-07"}),
    "crux_history": (gsc_crux, "query_history", {"url_or_origin": PAGE}),
}


def fail_with(monkeypatch, tool, exc):
    module, attr, kwargs = ADAPTERS[tool]

    def boom(*args, **kw):
        raise exc

    monkeypatch.setattr(module, attr, boom)
    return TOOL_FNS[tool](**kwargs)


@pytest.mark.parametrize("exc,category", ERROR_CASES, ids=[repr(e)[:50] for e, _ in ERROR_CASES])
@pytest.mark.parametrize("tool", sorted(ADAPTERS))
def test_every_failure_becomes_a_contract_error(rec, monkeypatch, tool, exc, category):
    out = fail_with(monkeypatch, tool, exc)
    assert out["error"] == category
    assert isinstance(out["hint"], str) and out["hint"]
    assert out["error"] in ERROR_CATEGORIES
    assert "Traceback" not in json.dumps(out)


@pytest.mark.parametrize("module,attr,kwargs", [
    (gsc_crux, "query_record", {"url": PAGE, "source": "crux"}),
    (gsc_crux, "query_history", {"url": PAGE, "source": "crux_history"}),
])
def test_crux_failures_become_contract_errors(rec, monkeypatch, module, attr, kwargs):
    def boom(*args, **kw):
        raise api_error(403)

    monkeypatch.setattr(module, attr, boom)
    assert TOOL_FNS["page_speed"](**kwargs)["error"] == "permission_denied"


def test_missing_credentials_file_key_is_auth_required(monkeypatch):
    def no_adc(*args, **kwargs):
        raise DefaultCredentialsError("no adc")

    monkeypatch.setattr(google.auth, "default", no_adc)
    monkeypatch.setattr(gsc_auth, "_load_credentials", lambda: {
        "refresh_token": "r", "client_id": "c", "client_secret": "s"})
    out = gsc_mcp.list_sites()
    assert out["error"] == "auth_required"
    assert "webmasters.readonly" in out["hint"]


def test_unresolved_credentials_are_auth_required(monkeypatch):
    def no_adc(*args, **kwargs):
        raise DefaultCredentialsError("no adc")

    monkeypatch.setattr(google.auth, "default", no_adc)
    monkeypatch.setattr(gsc_auth, "_load_credentials", lambda: None)
    out = gsc_mcp.list_sitemaps(site_url=SITE)
    assert out["error"] == "auth_required"
    assert gsc_auth.adc_command(write=False) in out["hint"]


@pytest.mark.parametrize("exc", [
    gsc_auth.AuthRequiredError("none"), RefreshError("invalid_grant"), api_error(401),
], ids=["no_credentials", "refresh_error", "http_401"])
def test_auth_hint_carries_the_repo_gcloud_command(rec, monkeypatch, exc):
    out = fail_with(monkeypatch, "list_sites", exc)
    command = gsc_auth.adc_command(write=False)
    assert out["error"] == "auth_required"
    assert command in out["hint"]
    assert command.startswith("gcloud auth application-default login --scopes=")
    assert "gcloud application-default" not in out["hint"]


def test_google_http_errors_map_end_to_end(rec):
    def answer(status, headers=None):
        rec.respond = lambda c, m, u: (status, headers or {}, b'{"error": {"code": %d}}' % status)
        rec.operations.clear()

    answer(403)
    out = TOOL_FNS["list_sites"]()
    assert (out["error"], out["http_status"], out["source"]) == ("permission_denied", 403, "GSC")
    answer(404)
    assert TOOL_FNS["list_sitemaps"](site_url=SITE)["error"] == "not_found"
    answer(400)
    assert TOOL_FNS["inspect_url"](site_url=SITE, url=PAGE)["error"] == "invalid_argument"
    answer(401)
    assert TOOL_FNS["search_analytics"](site_url=SITE, days=7)["error"] == "auth_required"


def test_rate_limits_retry_once_for_reads_but_never_for_inspection(rec):
    rec.respond = lambda c, m, u: (429, {"retry-after": "1"}, b'{"error": {"code": 429}}')
    out = TOOL_FNS["list_sites"]()
    assert out["error"] == "quota_exceeded" and out["retry_after"] == "1"
    assert len(rec.operations) == 2 and rec.sleeps == [1.0]
    rec.operations.clear()
    assert TOOL_FNS["inspect_url"](site_url=SITE, url=PAGE)["error"] == "quota_exceeded"
    assert len(rec.operations) == 1 and rec.sleeps == [1.0]


def test_psi_and_crux_http_errors_map_end_to_end(rec, monkeypatch):
    monkeypatch.setenv("PAGESPEED_API_KEY", API_KEY)
    rec.respond = lambda c, m, u: (403, {}, b'{"error": {"status": "PERMISSION_DENIED"}}')
    out = TOOL_FNS["page_speed"](url=PAGE)
    assert (out["error"], out["source"]) == ("permission_denied", "PSI")
    out = TOOL_FNS["page_speed"](url=PAGE, source="crux")
    assert (out["error"], out["source"]) == ("permission_denied", "CrUX")
    rec.respond = lambda c, m, u: (429, {}, b"{}")
    assert TOOL_FNS["page_speed"](url=PAGE)["error"] == "quota_exceeded"
    assert rec.sleeps == []



# Refusals reported for the OAuth token (PSI 403, CrUX 400), not captured from a live call: the
# bodies are rebuilt from the reported status, reason and message.
PSI_SCOPE_REFUSAL = as_json({"error": {
    "code": 403, "message": "Request had insufficient authentication scopes.",
    "errors": [{"message": "Insufficient Permission", "domain": "global",
                "reason": "insufficientPermissions"}],
    "status": "PERMISSION_DENIED",
    "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                 "reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT", "domain": "googleapis.com"}],
}})
CRUX_INVALID_ARGUMENT = as_json({"error": {
    "code": 400, "message": "Request contains an invalid argument.",
    "status": "INVALID_ARGUMENT",
}})
PAGE_SPEED_CALLS = {
    "psi": {"url": PAGE},
    "crux": {"url": PAGE, "source": "crux"},
    "crux_history": {"url": PAGE, "source": "crux_history", "scope": "origin"},
}


def page_speed_variants():
    return {name: TOOL_FNS["page_speed"](**call) for name, call in PAGE_SPEED_CALLS.items()}


def urllib_urls(rec):
    return [url for channel, _method, url in rec.operations if channel == "urllib"]


def answer_urllib(status, body):
    return lambda channel, method, url: (status, {}, body) if channel == "urllib" else None


def test_api_key_is_a_query_parameter_and_nothing_looks_up_credentials(rec, monkeypatch):
    monkeypatch.setenv("PAGESPEED_API_KEY", API_KEY)
    assert all("error" not in out for out in page_speed_variants().values())
    urls = urllib_urls(rec)
    assert len(urls) == 3
    assert all(parse_qs(urlsplit(url).query)["key"] == [API_KEY] for url in urls)
    assert [urlsplit(url).query for url in urls[1:]] == [f"key={API_KEY}"] * 2
    assert all("authorization" not in headers for headers in rec.urllib_headers)
    assert rec.credential_writes == []
    assert rec.violations == []


def test_without_the_key_requests_carry_the_bearer_token_as_before(rec):
    page_speed_variants()
    assert all("key=" not in url for url in urllib_urls(rec))
    assert all(h["authorization"] == f"Bearer {SENTINEL}" for h in rec.urllib_headers)
    assert rec.credential_writes == [False] * 3


def test_key_is_read_at_call_time_and_a_blank_value_counts_as_unset(rec, monkeypatch):
    speed = TOOL_FNS["page_speed"]
    monkeypatch.setenv("PAGESPEED_API_KEY", "   ")
    speed(url=PAGE, strategy="mobile")
    monkeypatch.setenv("PAGESPEED_API_KEY", API_KEY)
    speed(url=PAGE, strategy="desktop")
    first, second = urllib_urls(rec)
    assert "key=" not in first and f"key={API_KEY}" in second
    assert rec.credential_writes == [False]


def test_credentials_present_ignores_the_api_key(home, monkeypatch):
    monkeypatch.setenv("PAGESPEED_API_KEY", API_KEY)
    assert gsc_mcp.credentials_present() is False


def test_the_read_only_allow_list_holds_with_the_key_in_the_query_string(rec, monkeypatch):
    monkeypatch.setenv("PAGESPEED_API_KEY", API_KEY)
    for name, outputs in run_sweep().items():
        assert all("error" not in out for out in outputs), name
    assert rec.violations == [] and rec.forbidden_calls == []
    assert rec.paths("urllib") == {
        ("GET", "/pagespeedonline/v5/runPagespeed"),
        ("POST", "/v1/records:queryRecord"),
        ("POST", "/v1/records:queryHistoryRecord"),
    }


@pytest.mark.parametrize("name,refusal", [
    ("psi", (403, PSI_SCOPE_REFUSAL)),
    ("crux", (400, CRUX_INVALID_ARGUMENT)),
    ("crux_history", (400, CRUX_INVALID_ARGUMENT)),
])
def test_live_refusals_without_a_key_tell_the_operator_to_set_one(rec, name, refusal):
    status, body = refusal
    rec.respond = answer_urllib(status, body)
    out = TOOL_FNS["page_speed"](**PAGE_SPEED_CALLS[name])
    assert out["error"] == "auth_required" and out["http_status"] == status
    for needle in ("PAGESPEED_API_KEY", "PageSpeed Insights API", "Chrome UX Report API"):
        assert needle in out["hint"]
    assert "site_url" not in out["hint"] and "dates" not in out["hint"]
    assert len(urllib_urls(rec)) == 1


def test_with_a_key_crux_400_is_invalid_argument_and_403_is_permission_denied(rec, monkeypatch):
    monkeypatch.setenv("PAGESPEED_API_KEY", API_KEY)
    speed = TOOL_FNS["page_speed"]
    rec.respond = answer_urllib(400, CRUX_INVALID_ARGUMENT)
    out = speed(**PAGE_SPEED_CALLS["crux"])
    assert out["error"] == "invalid_argument"
    assert "Check url, origin and form_factor" in out["hint"]
    rec.respond = answer_urllib(403, PSI_SCOPE_REFUSAL)
    for name in ("psi", "crux"):
        out = speed(**PAGE_SPEED_CALLS[name])
        assert out["error"] == "permission_denied"
        assert "PageSpeed Insights API" in out["hint"] and "restrictions" in out["hint"]


def test_without_a_key_a_bad_psi_url_and_server_errors_keep_their_meaning(rec):
    speed = TOOL_FNS["page_speed"]
    rec.respond = answer_urllib(400, b'{"error": {"status": "INVALID_ARGUMENT"}}')
    out = speed(url=PAGE)
    assert out["error"] == "invalid_argument" and "PAGESPEED_API_KEY" not in out["hint"]
    rec.respond = answer_urllib(500, b"{}")
    assert speed(url=PAGE, strategy="desktop")["error"] == "upstream_error"


def echoing(status):
    """An upstream error whose body and reason strings repeat the request URL."""
    def respond(channel, method, url):
        if channel != "urllib":
            return None
        return status, {}, as_json({"error": {
            "code": status, "message": f"Bad request: {url}", "status": "INVALID_ARGUMENT",
            "errors": [{"message": url, "reason": f"echo {url}"}]}})
    return respond


def test_api_key_never_reaches_outputs_hints_logs_or_cache(rec, monkeypatch, caplog,
                                                           tmp_cache_dir):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("PAGESPEED_API_KEY", API_KEY)
    outputs = list(page_speed_variants().values())
    for status in (400, 403, 404, 429, 500):
        rec.respond = echoing(status)
        for call in ({}, {"source": "crux"}, {"source": "crux_history"}):
            outputs.append(TOOL_FNS["page_speed"](url=f"https://example.com/f{status}", **call))
    assert API_KEY not in json.dumps(outputs) and API_KEY not in caplog.text
    cached = [p for p in tmp_cache_dir.rglob("*") if p.is_file()]
    assert cached
    for path in cached:
        assert API_KEY not in str(path) and API_KEY not in path.read_text(encoding="utf-8")


def test_exception_text_that_echoes_the_request_url_is_scrubbed(rec, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("PAGESPEED_API_KEY", API_KEY)

    def unreachable(request, timeout=None, **kwargs):
        raise urllib.error.URLError(f"cannot reach {request.full_url}")

    monkeypatch.setattr(urllib.request, "urlopen", unreachable)
    for call in PAGE_SPEED_CALLS.values():
        out = TOOL_FNS["page_speed"](**call)
        assert out["error"] == "upstream_error" and "[redacted]" in out["hint"]
        assert API_KEY not in json.dumps(out) and API_KEY not in caplog.text


@pytest.mark.parametrize("key_in_environment", [True, False])
def test_scrubber_removes_the_key_with_or_without_the_environment(monkeypatch,
                                                                  key_in_environment):
    if key_in_environment:
        monkeypatch.setenv("PAGESPEED_API_KEY", API_KEY)
    for text in (f"https://x.example/v1?key={API_KEY}", f"GET /v5?a=1&key={API_KEY}&b=2",
                 API_KEY, f"cannot reach {API_KEY}"):
        assert API_KEY not in gsc_mcp._scrub_text(text)



SECRET_SHAPES = [
    f"Bearer {SENTINEL}",
    f"Authorization: Bearer {SENTINEL}",
    f"access_token={SENTINEL}",
    f"{{'access_token': '{SENTINEL}', 'expires_in': 3599}}",
    f'{{"refresh_token": "{SENTINEL}"}}',
    f"refresh failed, token: {SENTINEL}",
    f"client_secret = {SENTINEL}",
    f"ya29.{SENTINEL}",
    "1//" + "0g" * 30,
    "GOCSPX-" + "ab12" * 8,
    SENTINEL,
]


def test_sentinel_token_is_live_on_the_wire_but_absent_from_every_output(rec, caplog):
    caplog.set_level(logging.DEBUG)
    results = run_sweep()
    assert any(SENTINEL in (h or "") for h in rec.auth_headers)
    assert SENTINEL not in json.dumps(results)
    assert SENTINEL not in caplog.text


@pytest.mark.parametrize("shape", SECRET_SHAPES, ids=[str(i) for i in range(len(SECRET_SHAPES))])
@pytest.mark.parametrize("tool", sorted(ADAPTERS))
def test_secrets_in_exception_text_never_reach_hints_or_logs(rec, monkeypatch, caplog, tool, shape):
    caplog.set_level(logging.DEBUG)
    module, attr, kwargs = ADAPTERS[tool]
    secret = SENTINEL if SENTINEL in shape else shape
    candidates = [RuntimeError(shape), ValueError(shape), RefreshError(shape), OSError(shape),
                  ApiReadError({"source": shape, "http_status": 500, "category": "request_failed",
                                "reasons": [shape], "retry_after": shape})]
    for exc in candidates:
        def boom(*args, _exc=exc, **kw):
            raise _exc

        monkeypatch.setattr(module, attr, boom)
        out = TOOL_FNS[tool](**kwargs)
        assert out["error"] in ERROR_CATEGORIES
        text = json.dumps(out)
        for needle in {secret, SENTINEL, "ab12ab12ab12", "0g0g0g0g"}:
            assert needle not in text and needle not in caplog.text, (tool, exc, text)



@pytest.fixture
def home(monkeypatch, tmp_path):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home_dir))
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path / "gcloud"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    return home_dir


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    return path


def test_credentials_absent_by_default(home):
    assert gsc_mcp.credentials_present() is False


def test_credentials_present_for_the_home_file_evaluated_at_call_time(home):
    assert gsc_mcp.credentials_present() is False
    touch(home / ".claude" / "gsc-credentials.json")
    assert gsc_mcp.credentials_present() is True


def test_credentials_present_for_an_existing_application_credentials_file(home, tmp_path,
                                                                           monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "sa.json"))
    assert gsc_mcp.credentials_present() is False
    touch(tmp_path / "sa.json")
    assert gsc_mcp.credentials_present() is True


def test_credentials_present_for_the_gcloud_adc_file(home, tmp_path):
    touch(tmp_path / "gcloud" / "application_default_credentials.json")
    assert gsc_mcp.credentials_present() is True


def test_credentials_present_for_the_default_adc_location(home, tmp_path, monkeypatch):
    monkeypatch.delenv("CLOUDSDK_CONFIG")
    base = tmp_path / "appdata" if os.name == "nt" else home / ".config"
    assert gsc_mcp.credentials_present() is False
    touch(base / "gcloud" / "application_default_credentials.json")
    assert gsc_mcp.credentials_present() is True


def test_a_directory_is_not_a_credentials_file(home):
    (home / ".claude" / "gsc-credentials.json").mkdir(parents=True)
    assert gsc_mcp.credentials_present() is False


def test_credentials_present_never_raises(monkeypatch):
    def no_home():
        raise RuntimeError("no home")

    monkeypatch.setattr(Path, "home", staticmethod(no_home))
    monkeypatch.delenv("CLOUDSDK_CONFIG", raising=False)
    assert gsc_mcp.credentials_present() is False


def test_credentials_present_makes_no_network_call_and_no_adc_probe(home, monkeypatch):
    calls = []
    touch(home / ".claude" / "gsc-credentials.json")
    monkeypatch.setattr(google.auth, "default", lambda *a, **k: calls.append("default"))
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: calls.append("connect"))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: calls.append("getaddrinfo"))
    assert gsc_mcp.credentials_present() is True
    assert gsc_mcp.credentials_present() is True
    assert calls == []



def test_main_builds_the_server_inside_the_call_and_runs_stdio(monkeypatch):
    runs = []
    monkeypatch.setattr(FastMCP, "run", lambda self, *a, **k: runs.append(self))
    gsc_mcp.main()
    (server,) = runs
    assert server.name == "google-search-console-agent"
    assert {t.name for t in asyncio.run(server.list_tools())} == EXPECTED_TOOLS


def test_importing_the_module_loads_no_heavy_libraries():
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import gsc_mcp; "
        "heavy = ('mcp', 'googleapiclient', 'google.auth', 'httplib2', 'jinja2'); "
        "print([m for m in heavy if m in sys.modules])"
    )
    out = subprocess.run([sys.executable, "-c", code, str(Path(gsc_mcp.__file__).parent)],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"


PERIODS = {"site_url": SITE, "date_from": "2026-09-08", "date_to": "2026-09-14",
           "compare_from": "2026-09-01", "compare_to": "2026-09-07"}


def ok(payload):
    return 200, {}, json.dumps(payload).encode()


def search_rows(rec, by_start):
    def respond(channel, method, url):
        if url.split("?")[0].endswith("/searchAnalytics/query"):
            return ok({"rows": by_start[rec.bodies[-1][2]["startDate"]]})
        return None

    rec.respond = respond


def test_compare_periods_queries_both_periods_and_joins_rows(rec):
    search_rows(rec, {
        "2026-09-08": [{"keys": ["a"], "clicks": 30, "impressions": 300, "ctr": 0.1,
                        "position": 2.0},
                       {"keys": ["new"], "clicks": 5, "impressions": 50, "ctr": 0.1,
                        "position": 8.0}],
        "2026-09-01": [{"keys": ["a"], "clicks": 20, "impressions": 0, "ctr": 0.05,
                        "position": 3.5},
                       {"keys": ["gone"], "clicks": 4, "impressions": 40, "ctr": 0.1,
                        "position": 9.0}],
    })
    out = gsc_mcp.compare_periods(**PERIODS, limit=10)
    current, previous = rec.requests("searchAnalytics/query")
    assert (current["startDate"], current["endDate"]) == ("2026-09-08", "2026-09-14")
    assert (previous["startDate"], previous["endDate"]) == ("2026-09-01", "2026-09-07")
    for body in (current, previous):
        assert body["dimensions"] == ["query"] and body["rowLimit"] == 10
        assert body["dataState"] == "final"
    a, new, gone = out["rows"]
    assert a["query"] == "a" and a["clicks_change"] == 10 and a["clicks_change_pct"] == 50.0
    assert a["impressions_change_pct"] is None
    assert a["ctr_change_percentage_points"] == 5.0 and a["position_change"] == -1.5
    assert new["query"] == "new" and new["clicks_previous"] is None
    assert new["clicks_change"] is None and new["position_change"] is None
    assert gone["clicks"] is None and gone["clicks_previous"] == 4
    assert out["days_per_period"] == 7 and out["rows_returned"] == 3
    assert out["complete"] is True


def test_compare_periods_is_incomplete_when_a_period_fills_the_limit(rec):
    row = {"keys": ["https://example.com/a"], "clicks": 1, "impressions": 2, "ctr": 0.5,
           "position": 1.0}
    search_rows(rec, {"2026-09-08": [row], "2026-09-01": []})
    out = gsc_mcp.compare_periods(**PERIODS, dimension="page", limit=1)
    assert out["complete"] is False
    assert out["rows"][0]["page"] == "https://example.com/a"


@pytest.mark.parametrize("kwargs", [
    {"compare_from": "2026-08-31"},
    {"compare_to": "2026-09-08"},
    {"dimension": "date"},
    {"dimension": "hour"},
    {"limit": 501},
    {"date_from": "2026-09-15"},
    {"compare_to": None},
])
def test_compare_periods_rejects_bad_input_before_any_request(rec, kwargs):
    out = gsc_mcp.compare_periods(**{**PERIODS, **kwargs})
    assert out["error"] == "invalid_argument"
    assert rec.operations == []


def test_compare_periods_names_both_lengths_when_they_differ(rec):
    out = gsc_mcp.compare_periods(**{**PERIODS, "compare_from": "2026-08-31"})
    assert "7 days against 8" in out["hint"]


CWV_HISTORY = {"record": {
    "collectionPeriods": [{"lastDate": {"year": 2026, "month": 9, "day": d}} for d in (6, 13)],
    "metrics": {
        "largest_contentful_paint": {"percentilesTimeseries": {"p75s": [2400, "NaN"]}},
        "interaction_to_next_paint": {"percentilesTimeseries": {"p75s": [180, 190]}},
        "cumulative_layout_shift": {"percentilesTimeseries": {"p75s": ["0.05", "0.06"]}},
        "first_contentful_paint": {"percentilesTimeseries": {"p75s": [1000, 1100]}},
        "experimental_time_to_first_byte": {"percentilesTimeseries": {"p75s": [600, 700]}},
    },
}}


def test_crux_history_origin_without_path_and_url_with_path(rec, monkeypatch):
    monkeypatch.setenv("PAGESPEED_API_KEY", API_KEY)
    rec.respond = lambda c, m, u: ok(CWV_HISTORY) if "queryHistoryRecord" in u else None
    origin = gsc_mcp.crux_history("https://example.com")
    page = gsc_mcp.crux_history("https://example.com/", form_factor="PHONE")
    first, second = rec.requests("queryHistoryRecord")
    assert first == {"collectionPeriodCount": 25, "origin": "https://example.com"}
    assert second == {"collectionPeriodCount": 25, "url": "https://example.com/",
                      "formFactor": "PHONE"}
    assert (origin["target_kind"], page["target_kind"]) == ("origin", "url")
    assert origin["history"] == {"lcp_p75_ms": [2400.0, None], "inp_p75_ms": [180.0, 190.0],
                                 "cls_p75": [0.05, 0.06]}
    assert origin["rows_returned"] == 2 and origin["complete"] is True
    assert set(rec.auth_headers) == {None}


def test_crux_history_without_data_is_a_result(rec):
    rec.respond = lambda c, m, u: (404, {}, b"{}") if "queryHistoryRecord" in u else None
    out = gsc_mcp.crux_history("https://example.com/none")
    assert out["status"] == "no_data" and out["rows_returned"] == 0
    assert "history" not in out


@pytest.mark.parametrize("kwargs", [
    {"url_or_origin": "example.com"},
    {"url_or_origin": "ftp://example.com"},
    {"url_or_origin": "https://example.com", "form_factor": "WATCH"},
])
def test_crux_history_rejects_bad_input_before_any_request(rec, kwargs):
    assert gsc_mcp.crux_history(**kwargs)["error"] == "invalid_argument"
    assert rec.operations == []


def test_crux_history_without_a_key_tells_the_operator_to_set_one(rec):
    rec.respond = lambda c, m, u: (400, {}, b"{}") if "queryHistoryRecord" in u else None
    out = gsc_mcp.crux_history("https://example.com")
    assert out["error"] == "auth_required" and "PAGESPEED_API_KEY" in out["hint"]


SITEMAP_URL = "https://example.com/sitemap.xml"
SITEMAP_ENTRY = {
    "path": SITEMAP_URL, "type": "sitemap", "isPending": False, "isSitemapsIndex": False,
    "lastSubmitted": "2026-09-01T00:00:00Z", "lastDownloaded": "2026-10-01T00:00:00Z",
    "errors": "2", "warnings": "0"}
SITEMAP_ENTRY_PATH = "/webmasters/v3/sites/sc-domain:example.com/sitemaps/" + SITEMAP_URL


class Gate:
    def __init__(self, refusal=None):
        self.calls = 0
        self.refusal = refusal

    def __call__(self):
        self.calls += 1
        return self.refusal


def entry_server(rec, delete_answer=(204, {}, b"")):
    state = {"entry": dict(SITEMAP_ENTRY)}

    def respond(channel, method, url):
        if channel != "google" or "/sitemaps/" not in url:
            return None
        if method == "GET":
            return ok(state["entry"])
        if method == "DELETE":
            return delete_answer
        return None

    rec.respond = respond
    return state


def sitemap_calls(rec):
    from urllib.parse import unquote

    return [(m, unquote(urlsplit(u).path)) for c, m, u in rec.operations
            if c == "google" and "/sitemaps/" in u]


def deletes(rec):
    return [m for m, _ in sitemap_calls(rec)].count("DELETE")


def delete(gate, **kwargs):
    return gsc_mcp.delete_sitemap(
        **{"site_url": SITE, "sitemap_url": SITEMAP_URL, **kwargs}, gate=gate)


def test_delete_dry_run_reads_the_entry_and_sends_nothing(rec):
    entry_server(rec)
    gate = Gate()
    out = delete(gate)
    assert out["dry_run"] is True
    assert re.fullmatch(r"[0-9a-f]{32}", out["confirm"])
    assert out["confirm_expires_in"] == 600
    assert out["sitemap"]["path"] == SITEMAP_URL and out["sitemap"]["errors"] == 2
    assert sitemap_calls(rec) == [("GET", SITEMAP_ENTRY_PATH)]
    assert gate.calls == 0
    assert set(rec.credential_writes) == {False}


def test_confirmed_delete_sends_once_with_the_write_scope(rec, caplog, tmp_cache_dir):
    entry_server(rec)
    gsc_utils.cache_set([SITEMAP_ENTRY], "sitemaps", SITE)
    gate = Gate()
    token = delete(gate)["confirm"]
    caplog.set_level(logging.INFO, logger="gsc_mcp")
    out = delete(gate, confirm=token)
    assert out == {"dry_run": False, "site_url": SITE, "sitemap_url": SITEMAP_URL,
                   "deleted": True, "rows_returned": 1, "complete": True}
    assert sitemap_calls(rec) == [("GET", SITEMAP_ENTRY_PATH), ("GET", SITEMAP_ENTRY_PATH),
                                  ("DELETE", SITEMAP_ENTRY_PATH)]
    assert rec.credential_writes[-1] is True and rec.credential_writes.count(True) == 1
    assert gate.calls == 1
    assert gsc_utils.cache_get("sitemaps", SITE) is None
    lines = [r.getMessage() for r in caplog.records if " write " in r.getMessage()]
    assert lines == [f"gsc write delete_sitemap {SITE} outcome=ok"]
    assert token not in caplog.text
    assert rec.forbidden_calls == []


def test_delete_token_is_single_use(rec):
    entry_server(rec)
    gate = Gate()
    token = delete(gate)["confirm"]
    delete(gate, confirm=token)
    assert delete(gate, confirm=token)["error"] == "invalid_argument"
    assert deletes(rec) == 1


def test_delete_token_is_bound_to_the_arguments(rec):
    entry_server(rec)
    gate = Gate()
    token = delete(gate)["confirm"]
    out = delete(gate, sitemap_url="https://example.com/other.xml", confirm=token)
    assert out["error"] == "invalid_argument"
    assert deletes(rec) == 0


@pytest.mark.parametrize("confirm", ["abc", "G" * 32, 12345])
def test_malformed_confirm_is_refused_before_any_request(rec, confirm):
    assert delete(Gate(), confirm=confirm)["error"] == "invalid_argument"
    assert rec.operations == []


def test_resubmission_after_the_dry_run_is_a_conflict(rec):
    state = entry_server(rec)
    gate = Gate()
    token = delete(gate)["confirm"]
    state["entry"]["lastSubmitted"] = "2026-10-02T00:00:00Z"
    assert delete(gate, confirm=token)["error"] == "conflict"
    assert deletes(rec) == 0


def test_gate_refusal_is_returned_unchanged_and_keeps_the_token(rec):
    entry_server(rec)
    refusal = {"error": "permission_denied", "hint": "writes are off"}
    gate = Gate(refusal)
    token = delete(gate)["confirm"]
    assert delete(gate, confirm=token) == refusal
    assert deletes(rec) == 0
    gate.refusal = None
    assert delete(gate, confirm=token)["deleted"] is True


@pytest.mark.parametrize("status,category", [(403, "permission_denied"), (401, "auth_required")])
def test_missing_write_scope_names_the_scope(rec, status, category):
    body = json.dumps({"error": {"code": status, "status": "PERMISSION_DENIED", "errors": [
        {"reason": "insufficientPermissions"}]}}).encode()
    entry_server(rec, delete_answer=(status, {}, body))
    gate = Gate()
    out = delete(gate, confirm=delete(gate)["confirm"])
    assert out["error"] == category
    assert "https://www.googleapis.com/auth/webmasters scope" in out["hint"]
    assert gsc_auth.adc_command(write=True) in out["hint"]


def test_write_credentials_that_do_not_resolve_are_auth_required(rec, monkeypatch):
    entry_server(rec)
    gate = Gate()
    token = delete(gate)["confirm"]
    read_credentials = gsc_admin.get_credentials

    def no_write_credentials(write=False):
        if write:
            raise gsc_auth.AuthRequiredError("none")
        return read_credentials(write)

    monkeypatch.setattr(gsc_admin, "get_credentials", no_write_credentials)
    out = delete(gate, confirm=token)
    assert out["error"] == "auth_required"
    assert gsc_auth.adc_command(write=True) in out["hint"]
    assert deletes(rec) == 0


def test_server_error_on_the_delete_is_never_retried_and_may_have_applied(rec, caplog):
    entry_server(rec, delete_answer=(503, {}, b"{}"))
    gate = Gate()
    token = delete(gate)["confirm"]
    caplog.set_level(logging.INFO, logger="gsc_mcp")
    out = delete(gate, confirm=token)
    assert out["error"] == "upstream_error" and "list_sitemaps" in out["hint"]
    assert deletes(rec) == 1
    assert rec.sleeps == []
    assert f"gsc write delete_sitemap {SITE} outcome=upstream_error" in caplog.text


def test_unknown_sitemap_is_not_found_and_issues_no_token(rec):
    rec.respond = lambda c, m, u: (
        (404, {}, b'{"error": {"code": 404}}') if "/sitemaps/" in u else None)
    out = delete(Gate())
    assert out["error"] == "not_found" and "confirm" not in out


@pytest.mark.parametrize("kwargs", [{"sitemap_url": "sitemap.xml"}, {"site_url": ""}])
def test_bad_delete_targets_are_rejected_before_any_request(rec, kwargs):
    assert delete(Gate(), **kwargs)["error"] == "invalid_argument"
    assert rec.operations == []


def test_register_writes_adds_the_destructive_tool_without_a_gate_argument():
    server = FastMCP("test")
    assert gsc_mcp.register_writes(server, Gate(), "gsc_") == 1
    (tool,) = asyncio.run(server.list_tools())
    assert tool.name == "gsc_delete_sitemap" and tool.title
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is True
    assert tool.annotations.idempotentHint is False
    assert tool.annotations.openWorldHint is True
    assert set(tool.inputSchema["properties"]) == {"site_url", "sitemap_url", "confirm"}
    assert "webmasters" in tool.description


def test_register_writes_needs_a_callable_gate():
    with pytest.raises(TypeError):
        gsc_mcp.register_writes(FastMCP("test"), None)


def test_write_tool_runs_through_the_sdk(rec):
    entry_server(rec)
    gate = Gate()
    server = FastMCP("test")
    gsc_mcp.register_writes(server, gate)
    args = {"site_url": SITE, "sitemap_url": SITEMAP_URL}
    dry = structured(asyncio.run(server.call_tool("delete_sitemap", args)))
    done = structured(asyncio.run(server.call_tool(
        "delete_sitemap", {**args, "confirm": dry["confirm"]})))
    assert done["deleted"] is True and gate.calls == 1


def test_compare_periods_never_joins_keys_that_redaction_made_ambiguous(rec):
    def page(path, clicks):
        return {"keys": [f"https://example.com/p/{path}"], "clicks": clicks,
                "impressions": clicks * 10, "ctr": 0.1, "position": 2.0}

    search_rows(rec, {"2026-09-08": [page("1234567890", 900), page("9876543210", 5),
                                     page("plain", 7)],
                      "2026-09-01": [page("1234567890", 3), page("plain", 6)]})
    out = gsc_mcp.compare_periods(**PERIODS, dimension="page", limit=10)
    plain, *ambiguous = out["rows"]
    assert plain["page"] == "https://example.com/p/plain" and plain["clicks_change"] == 1
    assert [(r["clicks"], r["clicks_previous"]) for r in ambiguous] == [
        (900, None), (5, None), (None, 3)]
    assert all(r["ambiguous_key"] and r["clicks_change"] is None for r in ambiguous)
    assert out["ambiguous_rows"] == 3 and out["complete"] is False
    assert "1234567890" not in json.dumps(out)


def test_guarded_keeps_only_a_real_token_unscrubbed():
    phone = "+1 555 123 4567 890"
    token = "a" * 32
    passthrough = gsc_mcp._guarded(lambda value: {"confirm": value, "note": phone})
    assert passthrough(token) == {"confirm": token, "note": "[phone-redacted]"}
    assert passthrough(phone)["confirm"] == "[phone-redacted]"
    assert passthrough({"x": phone})["confirm"] == {"x": "[phone-redacted]"}


def test_refresh_failure_before_the_delete_is_auth_required_and_keeps_the_token(rec,
                                                                                monkeypatch):
    entry_server(rec)
    gate = Gate()
    token = delete(gate)["confirm"]
    read_credentials = gsc_admin.get_credentials

    class ReadOnlyCredentials(FakeCredentials):
        def before_request(self, *args, **kwargs):
            raise RefreshError("invalid_scope: Bad Request")

    def credentials(write=False):
        return ReadOnlyCredentials() if write else read_credentials(write)

    monkeypatch.setattr(gsc_admin, "get_credentials", credentials)
    out = delete(gate, confirm=token)
    assert out["error"] == "auth_required"
    assert gsc_auth.adc_command(write=True) in out["hint"]
    assert deletes(rec) == 0
    monkeypatch.setattr(gsc_admin, "get_credentials", read_credentials)
    assert delete(gate, confirm=token)["deleted"] is True


def test_refused_delete_reasons_are_scrubbed(rec):
    body = json.dumps({"error": {"code": 403, "errors": [
        {"reason": "denied for owner@example.com"}]}}).encode()
    entry_server(rec, delete_answer=(403, {}, body))
    gate = Gate()
    out = delete(gate, confirm=delete(gate)["confirm"])
    assert out["error"] == "permission_denied"
    assert "owner@example.com" not in json.dumps(out)


@pytest.mark.parametrize("answer", [(503, {}, b"{}"), (403, {}, b"{}"), (400, {}, b"{}")])
def test_a_sent_delete_drops_the_cached_sitemap_list_whatever_the_outcome(rec, answer,
                                                                          tmp_cache_dir):
    entry_server(rec, delete_answer=answer)
    gate = Gate()
    token = delete(gate)["confirm"]
    gsc_utils.cache_set([SITEMAP_ENTRY], "sitemaps", SITE)
    assert "error" in delete(gate, confirm=token)
    assert gsc_utils.cache_get("sitemaps", SITE) is None


def test_failed_delete_with_a_cache_error_does_not_claim_the_write_succeeded(rec, monkeypatch):
    entry_server(rec, delete_answer=(403, {}, b"{}"))
    gate = Gate()
    token = delete(gate)["confirm"]

    def broken(*key):
        raise OSError("read-only")

    monkeypatch.setattr(gsc_admin, "cache_delete", broken)
    out = delete(gate, confirm=token)
    assert out["error"] == "permission_denied"
    assert "succeeded" not in out["cache_warning"]


def test_rate_limited_delete_with_a_cache_error_keeps_the_cache_warning(rec, monkeypatch):
    body = json.dumps({"error": {"code": 429, "errors": [{"reason": "rateLimitExceeded"}]}})
    entry_server(rec, delete_answer=(429, {"retry-after": "30"}, body.encode()))
    gate = Gate()
    token = delete(gate)["confirm"]

    def broken(*key):
        raise OSError("read-only")

    monkeypatch.setattr(gsc_admin, "cache_delete", broken)
    out = delete(gate, confirm=token)
    assert out["error"] == "quota_exceeded" and out["http_status"] == 429
    assert "stale" in out["cache_warning"] and "succeeded" not in out["cache_warning"]
    assert deletes(rec) == 1


@pytest.mark.parametrize("address,public", [
    ("64:ff9b::a00:5", False), ("64:ff9b::7f00:1", False), ("64:ff9b::5db8:d822", True),
])
def test_nat64_addresses_are_judged_by_the_embedded_ipv4_address(address, public):
    assert gsc_mcp._is_public(address) is public


def test_nat64_answer_for_a_private_address_is_never_fetched(rec):
    rec.dns["nat64.example"] = [["64:ff9b::a00:5"]]
    out = TOOL_FNS["structured_data"](url="https://nat64.example/products/widget")
    assert out["error"] == "invalid_argument" and rec.connections == []
