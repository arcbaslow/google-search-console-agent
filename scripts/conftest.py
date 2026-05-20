"""Pytest fixtures for GSC plugin tests."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def tmp_cache_dir(monkeypatch, tmp_path):
    """Redirect cache and credentials to a temp dir for every test."""
    cache_dir = tmp_path / "gsc-cache"
    creds_path = tmp_path / "gsc-credentials.json"
    import gsc_utils
    import gsc_auth
    monkeypatch.setattr(gsc_utils, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(gsc_auth, "CREDENTIALS_PATH", creds_path)
    return tmp_path


@pytest.fixture
def fake_creds(tmp_cache_dir):
    """Plant a fake credentials file so scripts pass auth checks."""
    import json as _json
    creds = {
        "token": "fake-token",
        "refresh_token": "fake-refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "fake-client-id",
        "client_secret": "fake-secret",
        "scopes": ["https://www.googleapis.com/auth/webmasters.readonly"],
        "expiry": "2099-01-01T00:00:00",
    }
    import gsc_auth
    gsc_auth.CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    gsc_auth.CREDENTIALS_PATH.write_text(_json.dumps(creds))
    return creds
