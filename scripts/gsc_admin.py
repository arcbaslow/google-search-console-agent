"""
GSC site, sitemap, and URL Inspection API wrapper.

Read surfaces:
  list_sites, get_site, list_sitemaps, get_sitemap, inspect_url

Write surfaces (require the `webmasters` scope, not `.readonly`):
  add_site, delete_site, submit_sitemap, delete_sitemap

CLI flag → call mapping mirrors the analytics agent's ga4_admin.py.
"""

from __future__ import annotations

import argparse
import json
import sys

from gsc_auth import get_credentials
from gsc_utils import cache_get, cache_set, normalize_site_url


def _get_service(write: bool = False):
    from googleapiclient.discovery import build
    return build("searchconsole", "v1", credentials=get_credentials(write=write), cache_discovery=False)


# ---------- sites ----------

def list_sites():
    cached = cache_get("sites")
    if cached:
        return cached
    service = _get_service()
    resp = service.sites().list().execute()
    out = [
        {"site_url": s.get("siteUrl"), "permission_level": s.get("permissionLevel")}
        for s in resp.get("siteEntry", [])
    ]
    cache_set(out, "sites")
    return out


def get_site(site_url: str):
    service = _get_service()
    site_url = normalize_site_url(site_url)
    return service.sites().get(siteUrl=site_url).execute()


def add_site(site_url: str):
    service = _get_service(write=True)
    site_url = normalize_site_url(site_url)
    service.sites().add(siteUrl=site_url).execute()
    return {"status": "added", "site_url": site_url}


def delete_site(site_url: str):
    service = _get_service(write=True)
    site_url = normalize_site_url(site_url)
    service.sites().delete(siteUrl=site_url).execute()
    return {"status": "deleted", "site_url": site_url}


# ---------- sitemaps ----------

def list_sitemaps(site_url: str):
    site_url = normalize_site_url(site_url)
    cached = cache_get("sitemaps", site_url)
    if cached:
        return cached
    service = _get_service()
    resp = service.sitemaps().list(siteUrl=site_url).execute()
    out = resp.get("sitemap", [])
    cache_set(out, "sitemaps", site_url)
    return out


def get_sitemap(site_url: str, feedpath: str):
    site_url = normalize_site_url(site_url)
    service = _get_service()
    return service.sitemaps().get(siteUrl=site_url, feedpath=feedpath).execute()


def submit_sitemap(site_url: str, feedpath: str):
    site_url = normalize_site_url(site_url)
    service = _get_service(write=True)
    service.sitemaps().submit(siteUrl=site_url, feedpath=feedpath).execute()
    return {"status": "submitted", "site_url": site_url, "feedpath": feedpath}


def delete_sitemap(site_url: str, feedpath: str):
    site_url = normalize_site_url(site_url)
    service = _get_service(write=True)
    service.sitemaps().delete(siteUrl=site_url, feedpath=feedpath).execute()
    return {"status": "deleted", "site_url": site_url, "feedpath": feedpath}


# ---------- URL inspection ----------

def inspect_url(site_url: str, url: str, lang: str | None = None):
    """One URL → indexing status, last crawl, mobile usability, rich results,
    page fetch state. Slow and quota-heavy; do not bulk-call."""
    site_url = normalize_site_url(site_url)
    cached = cache_get("inspect", site_url, url, lang)
    if cached:
        return cached
    service = _get_service()
    body = {"inspectionUrl": url, "siteUrl": site_url}
    if lang:
        body["languageCode"] = lang
    resp = service.urlInspection().index().inspect(body=body).execute()
    cache_set(resp, "inspect", site_url, url, lang)
    return resp


# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(description="GSC sites, sitemaps, URL inspection")
    parser.add_argument("--site", help="domain or URL prefix")
    parser.add_argument("--url", help="URL to inspect (with --inspect)")
    parser.add_argument("--lang", help="language code for inspection (e.g. en-US)")
    parser.add_argument("--feedpath", help="Sitemap URL (for sitemap commands)")

    # reads
    parser.add_argument("--list-sites", action="store_true")
    parser.add_argument("--get-site", action="store_true")
    parser.add_argument("--list-sitemaps", action="store_true")
    parser.add_argument("--get-sitemap", action="store_true")
    parser.add_argument("--inspect", action="store_true")

    # writes
    parser.add_argument("--add-site", action="store_true")
    parser.add_argument("--delete-site", action="store_true")
    parser.add_argument("--submit-sitemap", action="store_true")
    parser.add_argument("--delete-sitemap", action="store_true")

    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        out = _dispatch(args)
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}), file=sys.stderr)
        return 1

    if out is None:
        parser.print_help()
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


def _dispatch(args):
    if args.list_sites:
        return list_sites()
    if args.get_site:
        return get_site(args.site)
    if args.list_sitemaps:
        return list_sitemaps(args.site)
    if args.get_sitemap:
        return get_sitemap(args.site, args.feedpath)
    if args.inspect:
        return inspect_url(args.site, args.url, args.lang)
    if args.add_site:
        return add_site(args.site)
    if args.delete_site:
        return delete_site(args.site)
    if args.submit_sitemap:
        return submit_sitemap(args.site, args.feedpath)
    if args.delete_sitemap:
        return delete_sitemap(args.site, args.feedpath)
    return None


if __name__ == "__main__":
    sys.exit(main())
