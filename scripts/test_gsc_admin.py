"""Tests for the GSC sites / sitemaps / URL inspection adapter."""

from unittest.mock import MagicMock

import gsc_admin
import pytest


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
    monkeypatch.setattr("builtins.input", lambda: "y")

    def fake_get_service(write=False):
        called_with["write"] = write
        return MagicMock()

    monkeypatch.setattr(gsc_admin, "_get_service", fake_get_service)
    out = gsc_admin.submit_sitemap("example.com", "https://example.com/sitemap.xml")
    assert called_with["write"] is True
    assert out["status"] == "submitted"


def test_delete_sitemap_uses_write_service(monkeypatch):
    called_with = {}
    monkeypatch.setattr("builtins.input", lambda: "y")

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


WRITES = [
    ("add_site", "sites", "add", None),
    ("delete_site", "sites", "delete", None),
    ("submit_sitemap", "sitemaps", "submit", "https://example.com/sitemap.xml"),
    ("delete_sitemap", "sitemaps", "delete", "https://example.com/sitemap.xml"),
]


@pytest.mark.parametrize("function,resource,method,feedpath", WRITES)
@pytest.mark.parametrize("answer", ["", "n", "yes", "unexpected", EOFError, KeyboardInterrupt])
def test_write_refusal_never_builds_service(monkeypatch, capsys, function, resource,
                                          method, feedpath, answer):
    service = MagicMock()
    monkeypatch.setattr(gsc_admin, "_get_service", service)

    def respond():
        shown = capsys.readouterr().err
        assert "sc-domain:example.com" in shown
        assert "[y/N]" in shown
        if feedpath:
            assert feedpath in shown
        if isinstance(answer, type):
            raise answer()
        return answer

    monkeypatch.setattr("builtins.input", respond)
    args = ["example.com"] + ([feedpath] if feedpath else [])
    assert getattr(gsc_admin, function)(*args)["status"] == "cancelled"
    service.assert_not_called()


@pytest.mark.parametrize("function,resource,method,feedpath", WRITES)
def test_confirmed_write_executes_exactly_once(monkeypatch, capsys, function, resource,
                                             method, feedpath):
    service = MagicMock()
    factory = MagicMock(return_value=service)
    monkeypatch.setattr(gsc_admin, "_get_service", factory)

    def respond():
        shown = capsys.readouterr()
        assert not shown.out
        assert "sc-domain:example.com" in shown.err
        assert "[y/N]" in shown.err
        if feedpath:
            assert feedpath in shown.err
        factory.assert_not_called()
        return "Y"

    monkeypatch.setattr("builtins.input", respond)
    args = ["example.com"] + ([feedpath] if feedpath else [])
    getattr(gsc_admin, function)(*args)
    factory.assert_called_once_with(write=True)
    endpoint = getattr(getattr(service, resource)(), method)
    kwargs = {"siteUrl": "sc-domain:example.com"}
    if feedpath:
        kwargs["feedpath"] = feedpath
    endpoint.assert_called_once_with(**kwargs)
    endpoint().execute.assert_called_once_with()


@pytest.mark.parametrize("feedpath", [None, "", "/sitemap.xml", "file:///sitemap.xml"])
def test_invalid_sitemap_target_does_not_prompt_or_write(monkeypatch, feedpath):
    factory = MagicMock()
    prompt = MagicMock()
    monkeypatch.setattr(gsc_admin, "_get_service", factory)
    monkeypatch.setattr("builtins.input", prompt)
    with pytest.raises(ValueError):
        gsc_admin.submit_sitemap("example.com", feedpath)
    factory.assert_not_called()
    prompt.assert_not_called()


def test_inspection_cache_avoids_a_second_quota_call(monkeypatch):
    service = MagicMock()
    service.urlInspection().index().inspect().execute.return_value = {"inspectionResult": {}}
    monkeypatch.setattr(gsc_admin, "_get_service", lambda: service)
    first = gsc_admin.inspect_url("example.com", "https://example.com/a", "en-US")
    assert gsc_admin.inspect_url("example.com", "https://example.com/a", "en-US") == first
    service.urlInspection().index().inspect().execute.assert_called_once_with()
