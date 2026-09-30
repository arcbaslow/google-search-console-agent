"""Pytest fixtures for GSC plugin tests."""

import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def tmp_cache_dir(monkeypatch, tmp_path):
    """Redirect cache and credentials to a temp dir for every test."""
    cache_dir = tmp_path / "gsc-cache"
    creds_path = tmp_path / "gsc-credentials.json"
    import gsc_auth
    import gsc_utils
    monkeypatch.setattr(gsc_utils, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(gsc_auth, "CREDENTIALS_PATH", creds_path)
    return tmp_path


@pytest.fixture
def fake_creds(monkeypatch, tmp_cache_dir):
    """Supply synthetic legacy auth without writing a credentials file."""
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
    monkeypatch.setattr(gsc_auth, "_load_credentials", lambda: creds.copy())
    return creds


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    """Unmocked network and real credential discovery are test failures."""
    import google.auth

    def blocked(*args, **kwargs):
        raise AssertionError("Mock network and credential discovery in tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(google.auth, "default", blocked)
