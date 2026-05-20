"""Tests for gsc_auth helpers (no network)."""

import pytest

import gsc_auth


def test_scopes_for_read():
    assert gsc_auth.scopes_for(write=False) == ["https://www.googleapis.com/auth/webmasters.readonly"]


def test_scopes_for_write():
    assert gsc_auth.scopes_for(write=True) == ["https://www.googleapis.com/auth/webmasters"]


def test_adc_command_read_path():
    cmd = gsc_auth.adc_command(write=False)
    assert cmd.startswith("gcloud auth application-default login")
    assert "webmasters.readonly" in cmd
    assert "cloud-platform" in cmd
    # The literal write scope should NOT appear when write=False (the readonly
    # scope contains the substring 'webmasters' so we have to test the full
    # write scope string).
    assert "https://www.googleapis.com/auth/webmasters," not in cmd


def test_adc_command_write_path():
    cmd = gsc_auth.adc_command(write=True)
    assert "https://www.googleapis.com/auth/webmasters," in cmd
    assert "webmasters.readonly" not in cmd


def test_auth_required_error_carries_hint():
    err = gsc_auth.AuthRequiredError("hint text")
    assert err.hint == "hint text"
    assert str(err) == "hint text"


def test_get_credentials_falls_back_when_no_adc(monkeypatch, fake_creds):
    """When google.auth.default raises and a legacy file exists, we use it."""
    import google.auth.exceptions

    def _raise(**_):
        raise google.auth.exceptions.DefaultCredentialsError("no adc in test env")

    monkeypatch.setattr("google.auth.default", _raise)
    monkeypatch.setattr(gsc_auth, "refresh_if_needed", lambda cd: cd)

    creds = gsc_auth.get_credentials(write=False)
    assert gsc_auth.credentials_source(creds) == "legacy_oauth"


def test_get_credentials_raises_when_nothing_resolves(monkeypatch, tmp_cache_dir):
    import google.auth.exceptions

    def _raise(**_):
        raise google.auth.exceptions.DefaultCredentialsError("no adc")

    monkeypatch.setattr("google.auth.default", _raise)
    with pytest.raises(gsc_auth.AuthRequiredError) as excinfo:
        gsc_auth.get_credentials()
    assert "gcloud auth application-default login" in excinfo.value.hint
