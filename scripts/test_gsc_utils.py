"""Tests for gsc_utils."""



import gsc_utils


def test_normalize_bare_domain_to_sc_domain():
    assert gsc_utils.normalize_site_url("example.com") == "sc-domain:example.com"


def test_normalize_passes_through_sc_domain():
    assert gsc_utils.normalize_site_url("sc-domain:example.com") == "sc-domain:example.com"


def test_normalize_passes_through_url_prefix():
    assert gsc_utils.normalize_site_url("https://example.com/") == "https://example.com/"


def test_normalize_url_with_path_stays_url():
    assert gsc_utils.normalize_site_url("https://example.com/path") == "https://example.com/path"


def test_slug_handles_capitals_and_spaces():
    assert gsc_utils.slug("Acme Pro") == "acme-pro"
    assert gsc_utils.slug("") == "unnamed"


def test_date_range_default_window_ends_three_days_back():
    from datetime import date, timedelta

    start, end = gsc_utils.date_range(28)
    today = date.today()
    end_date = date.fromisoformat(end)
    # End should be exactly 3 days before today.
    assert (today - end_date) == timedelta(days=3)
    start_date = date.fromisoformat(start)
    assert (end_date - start_date) == timedelta(days=27)


def test_scrub_pii_drops_deny_keys_and_redacts_emails_and_phones():
    payload = {
        "email": "user@example.com",
        "query": "contact me at hello@example.com or +1 555 123 4567",
        "ip": "10.0.0.1",
        "nested": {"phone": "1234567"},
        "list": ["hello@example.com", "ok"],
    }
    out = gsc_utils.scrub_pii(payload)
    assert "email" not in out
    assert "ip" not in out
    assert "phone" not in out["nested"]
    assert "[email-redacted]" in out["query"]
    assert "[phone-redacted]" in out["query"]
    assert out["list"][0] == "[email-redacted]"
    assert out["list"][1] == "ok"


def test_cache_set_get_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(gsc_utils, "CACHE_DIR", tmp_path / "cache")
    gsc_utils.cache_set({"v": 1}, "k1", "k2")
    assert gsc_utils.cache_get("k1", "k2") == {"v": 1}


def test_cache_miss_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(gsc_utils, "CACHE_DIR", tmp_path / "cache")
    assert gsc_utils.cache_get("never", "set") is None
