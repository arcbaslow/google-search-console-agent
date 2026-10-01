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

@pytest.mark.parametrize("resource,call", [
    ("sites", lambda: gsc_admin.list_sites()),
    ("sitemaps", lambda: gsc_admin.list_sitemaps("example.com")),
])
def test_empty_inventory_is_a_cache_hit(monkeypatch, resource, call):
    service = MagicMock()
    execute = getattr(service, resource).return_value.list.return_value.execute
    execute.return_value = {}
    monkeypatch.setattr(gsc_admin, "_get_service", lambda **kw: service)
    assert call() == []
    assert call() == []
    execute.assert_called_once_with()


@pytest.mark.parametrize("function,resource,method,feedpath", WRITES)
@pytest.mark.parametrize("outcome", ["success", "cancelled", "failed"])
def test_write_invalidates_only_related_inventory_after_success(
        monkeypatch, function, resource, method, feedpath, outcome):
    import gsc_utils

    site = "sc-domain:example.com"
    old_sites = [{"site_url": site}]
    old_sitemaps = [{"path": "https://example.com/old.xml"}]
    inspection_key = ("inspect", site, "https://example.com/a", None)
    gsc_utils.cache_set(old_sites, "sites")
    gsc_utils.cache_set(old_sitemaps, "sitemaps", site)
    gsc_utils.cache_set([{"path": "unrelated"}], "sitemaps", "sc-domain:other.example")
    gsc_utils.cache_set({"inspectionResult": {}}, *inspection_key)
    service = MagicMock()
    execute = getattr(getattr(service, resource).return_value, method).return_value.execute
    if outcome == "failed":
        execute.side_effect = RuntimeError("API failed")
    factory = MagicMock(return_value=service)
    monkeypatch.setattr(gsc_admin, "_get_service", factory)
    monkeypatch.setattr("builtins.input", lambda: "n" if outcome == "cancelled" else "y")
    args = ["example.com"] + ([feedpath] if feedpath else [])
    if outcome == "failed":
        with pytest.raises(RuntimeError, match="API failed"):
            getattr(gsc_admin, function)(*args)
    else:
        result = getattr(gsc_admin, function)(*args)
        assert "cache_warning" not in result
    assert gsc_utils.cache_get("sitemaps", site) == (None if outcome == "success" else old_sitemaps)
    assert gsc_utils.cache_get("sites") == (None if outcome == "success" and resource == "sites" else old_sites)
    assert gsc_utils.cache_get("sitemaps", "sc-domain:other.example") == [{"path": "unrelated"}]
    assert gsc_utils.cache_get(*inspection_key) == {"inspectionResult": {}}
    if outcome == "cancelled":
        factory.assert_not_called()
        execute.assert_not_called()
    else:
        execute.assert_called_once_with()


def test_cache_invalidation_failure_does_not_repeat_successful_write(monkeypatch):
    service = MagicMock()
    monkeypatch.setattr(gsc_admin, "_get_service", lambda **kw: service)
    monkeypatch.setattr("builtins.input", lambda: "y")
    delete = MagicMock(side_effect=[PermissionError("locked cache"), None])
    monkeypatch.setattr(gsc_admin, "cache_delete", delete)
    result = gsc_admin.add_site("example.com")
    assert result["status"] == "added"
    assert "cache_warning" in result
    assert "do not repeat" in result["cache_warning"].lower()
    assert delete.call_count == 2  # Still invalidate the other related entry.
    service.sites.return_value.add.return_value.execute.assert_called_once_with()


def test_successful_sitemap_write_refetches_inventory_on_next_read(monkeypatch):
    service = MagicMock()
    read = service.sitemaps.return_value.list.return_value.execute
    read.side_effect = [{"sitemap": []}, {"sitemap": [{"path": "https://example.com/sitemap.xml"}]}]
    monkeypatch.setattr(gsc_admin, "_get_service", lambda **kw: service)
    monkeypatch.setattr("builtins.input", lambda: "y")
    assert gsc_admin.list_sitemaps("example.com") == []
    gsc_admin.submit_sitemap("example.com", "https://example.com/sitemap.xml")
    assert gsc_admin.list_sitemaps("example.com") == [{"path": "https://example.com/sitemap.xml"}]
    assert read.call_count == 2

def test_confirmed_write_http_error_is_never_retried(monkeypatch):
    import httplib2
    import pytest
    from googleapiclient.errors import HttpError
    service = MagicMock()
    execute = service.sites().add().execute
    execute.side_effect = HttpError(httplib2.Response({"status": "429"}), b'{}')
    monkeypatch.setattr(gsc_admin, "_get_service", lambda **kw: service)
    monkeypatch.setattr("builtins.input", lambda: "y")
    with pytest.raises(HttpError):
        gsc_admin.add_site("example.com")
    execute.assert_called_once_with()
