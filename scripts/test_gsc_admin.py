"""Tests for the GSC sites / sitemaps / URL inspection adapter."""

from unittest.mock import MagicMock

import gsc_admin


def test_list_sites_flattens_response(monkeypatch):
    mock_service = MagicMock()
    mock_service.sites().list().execute.return_value = {
        "siteEntry": [
            {"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"},
            {"siteUrl": "https://other.example/", "permissionLevel": "siteRestrictedUser"},
        ],
    }
    monkeypatch.setattr(gsc_admin, "_get_service", lambda write=False: mock_service)

    out = gsc_admin.list_sites()
    assert out == [
        {"site_url": "sc-domain:example.com", "permission_level": "siteOwner"},
        {"site_url": "https://other.example/", "permission_level": "siteRestrictedUser"},
    ]


def test_list_sitemaps_returns_inner_list(monkeypatch):
    mock_service = MagicMock()
    mock_service.sitemaps().list().execute.return_value = {
        "sitemap": [{"path": "https://example.com/sitemap.xml", "errors": 0, "warnings": 0}],
    }
    monkeypatch.setattr(gsc_admin, "_get_service", lambda write=False: mock_service)

    out = gsc_admin.list_sitemaps("example.com")
    assert out[0]["path"] == "https://example.com/sitemap.xml"


def test_submit_sitemap_uses_write_service(monkeypatch):
    """The submit() endpoint must use the write-scoped service."""
    called_with = {}

    def fake_get_service(write=False):
        called_with["write"] = write
        return MagicMock()

    monkeypatch.setattr(gsc_admin, "_get_service", fake_get_service)
    out = gsc_admin.submit_sitemap("example.com", "https://example.com/sitemap.xml")
    assert called_with["write"] is True
    assert out["status"] == "submitted"


def test_delete_sitemap_uses_write_service(monkeypatch):
    called_with = {}

    def fake_get_service(write=False):
        called_with["write"] = write
        return MagicMock()

    monkeypatch.setattr(gsc_admin, "_get_service", fake_get_service)
    out = gsc_admin.delete_sitemap("example.com", "https://example.com/sitemap.xml")
    assert called_with["write"] is True
    assert out["status"] == "deleted"


def test_inspect_url_passes_site_and_url_to_api(monkeypatch):
    mock_service = MagicMock()
    mock_service.urlInspection().index().inspect().execute.return_value = {
        "inspectionResult": {"indexStatusResult": {"verdict": "PASS"}},
    }
    monkeypatch.setattr(gsc_admin, "_get_service", lambda write=False: mock_service)
    out = gsc_admin.inspect_url("example.com", "https://example.com/foo")
    assert out["inspectionResult"]["indexStatusResult"]["verdict"] == "PASS"
