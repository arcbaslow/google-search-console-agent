"""Tests for gsc_utils."""

import gsc_utils
import pytest


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


@pytest.mark.parametrize(
    "value",
    [
        "77012345678",       # KZ mobile, bare
        "4111111111111111",  # card number
        "123456789",         # national-ID shaped
    ],
)
def test_scrub_pii_redacts_bare_digit_runs(value):
    """A numeric short-circuit used to return these unchanged.

    Search queries genuinely contain phone numbers, card numbers and national
    IDs, and the scrubbed value is what gets written to the on-disk cache.
    """
    assert gsc_utils.scrub_pii(value) == "[phone-redacted]"


def test_scrub_pii_redacts_dot_separated_phone():
    assert gsc_utils.scrub_pii("call +7.701.234.5678 now") == "call [phone-redacted] now"


def test_scrub_pii_redacts_percent_encoded_email():
    """GSC returns page dimensions percent-encoded."""
    out = gsc_utils.scrub_pii("/contact?to=john%40gmail.com")
    assert "john" not in out
    assert "[email-redacted]" in out


def test_scrub_pii_leaves_real_metrics_alone():
    """Metrics arrive as int/float, not strings, and must not be touched."""
    payload = {"clicks": 1234567890, "impressions": 42, "position": 3.7, "ctr": 0.0512}
    assert gsc_utils.scrub_pii(payload) == payload


def test_scrub_pii_leaves_short_numbers_and_dates_alone():
    """`date` dimension values must survive.

    `2026-08-14` matched PHONE_RE on length alone, so every date in a cached
    time series came back as the redaction marker.
    """
    assert gsc_utils.scrub_pii("2026-08-14") == "2026-08-14"
    assert gsc_utils.scrub_pii("20260814") == "20260814"
    assert gsc_utils.scrub_pii("42") == "42"
    assert gsc_utils.scrub_pii("2026-08-14T00:00:00") == "2026-08-14T00:00:00"


def test_scrub_pii_preserves_a_date_keyed_time_series():
    rows = [
        {"keys": ["2026-08-12"], "clicks": 120, "impressions": 4300},
        {"keys": ["2026-08-13"], "clicks": 98, "impressions": 3900},
    ]
    assert gsc_utils.scrub_pii(rows) == rows


def test_cache_set_get_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(gsc_utils, "CACHE_DIR", tmp_path / "cache")
    gsc_utils.cache_set({"v": 1}, "k1", "k2")
    assert gsc_utils.cache_get("k1", "k2") == {"v": 1}


def test_cache_miss_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(gsc_utils, "CACHE_DIR", tmp_path / "cache")
    assert gsc_utils.cache_get("never", "set") is None

@pytest.mark.parametrize("value,expected", [
    ("plain@example.com and encoded%40example.com", "[email-redacted] and [email-redacted]"),
    ("+1 555 123 4567 and encoded%40example.com", "[phone-redacted] and [email-redacted]"),
    ("plain@example.com and %2B1%20555%20987%206543", "[email-redacted] and [phone-redacted]"),
    ("[email-redacted] and encoded%40example.com", "[email-redacted] and [email-redacted]"),
])
def test_mixed_literal_and_encoded_identifiers_are_all_redacted(value, expected):
    assert gsc_utils.scrub_pii(value) == expected


def test_redaction_preserves_encoding_when_decoding_finds_no_more_identifiers():
    assert gsc_utils.scrub_pii("/hello%20world plain@example.com") == "/hello%20world [email-redacted]"
    assert gsc_utils.scrub_pii("/hello%20world?x=%2Fpath") == "/hello%20world?x=%2Fpath"

@pytest.mark.parametrize("raw", [b'{"rows":', b"\xff\xfeinvalid", b""])
def test_corrupt_cache_is_a_miss_and_can_be_replaced(tmp_cache_dir, raw):
    gsc_utils.CACHE_DIR.mkdir(parents=True)
    path = gsc_utils.CACHE_DIR / f"{gsc_utils._cache_key('broken')}.json"
    path.write_bytes(raw)
    assert gsc_utils.cache_get("broken") is None
    gsc_utils.cache_set({"rows": []}, "broken")
    assert gsc_utils.cache_get("broken") == {"rows": []}


def test_failed_serialization_preserves_previous_cache_and_cleans_temporary_file(monkeypatch):
    gsc_utils.cache_set({"rows": ["old"]}, "same")

    def interrupted_dump(value, stream, **kwargs):
        stream.write('{"rows":')
        raise OSError("simulated interrupted write")

    monkeypatch.setattr(gsc_utils.json, "dump", interrupted_dump)
    with pytest.raises(OSError, match="interrupted"):
        gsc_utils.cache_set({"rows": ["new"]}, "same")
    assert gsc_utils.cache_get("same") == {"rows": ["old"]}
    assert len(list(gsc_utils.CACHE_DIR.iterdir())) == 1


def test_reader_sees_complete_old_value_until_replacement(monkeypatch):
    import os

    gsc_utils.cache_set({"rows": ["old"]}, "same")
    original_replace = os.replace
    observed = []

    def replace_after_read(source, destination):
        observed.append(gsc_utils.cache_get("same"))
        return original_replace(source, destination)

    monkeypatch.setattr(os, "replace", replace_after_read)
    gsc_utils.cache_set({"rows": ["new"]}, "same")
    assert observed == [{"rows": ["old"]}]
    assert gsc_utils.cache_get("same") == {"rows": ["new"]}
    assert len(list(gsc_utils.CACHE_DIR.iterdir())) == 1


def test_failed_replacement_preserves_previous_cache(monkeypatch):
    import os
    from unittest.mock import MagicMock

    gsc_utils.cache_set({"rows": ["old"]}, "same")
    monkeypatch.setattr(os, "replace", MagicMock(side_effect=PermissionError("locked target")))
    with pytest.raises(PermissionError):
        gsc_utils.cache_set({"rows": ["new"]}, "same")
    assert gsc_utils.cache_get("same") == {"rows": ["old"]}
    assert len(list(gsc_utils.CACHE_DIR.iterdir())) == 1


def test_expired_cache_remains_a_miss(monkeypatch):
    import os

    gsc_utils.cache_set({"rows": []}, "expired")
    path = gsc_utils.CACHE_DIR / f"{gsc_utils._cache_key('expired')}.json"
    os.utime(path, (1000, 1000))
    monkeypatch.setattr(gsc_utils.time, "time", lambda: 1000 + gsc_utils.CACHE_TTL_SECONDS + 1)
    assert gsc_utils.cache_get("expired") is None


def test_cache_roundtrip_preserves_unicode_and_empty_list():
    gsc_utils.cache_set([{"query": "Алматы"}], "unicode")
    gsc_utils.cache_set([], "empty")
    assert gsc_utils.cache_get("unicode") == [{"query": "Алматы"}]
    assert gsc_utils.cache_get("empty") == []

@pytest.mark.parametrize("status,reason,hint,calls,category", [
    (403, "forbidden", None, 1, "access_denied"),
    (403, "dailyLimitExceeded", None, 1, "quota_exhausted"),
    (403, "userRateLimitExceeded", "2", 2, "rate_or_quota_limit"),
    (429, "", "900", 1, "rate_or_quota_limit"),
    (429, "", "invalid", 1, "rate_or_quota_limit"),
    (503, "", None, 2, "service_unavailable"),
])
def test_read_retry_policy_and_diagnostics(monkeypatch, status, reason, hint, calls, category):
    import json
    from unittest.mock import MagicMock

    import gsc_utils
    import httplib2
    from googleapiclient.errors import HttpError
    resp = httplib2.Response({"status": str(status), **({"retry-after": hint} if hint else {})})
    error = HttpError(resp, json.dumps({"error": {"errors": [{"reason": reason}]}}).encode())
    request = MagicMock()
    request.execute.side_effect = error
    sleep = MagicMock()
    monkeypatch.setattr(gsc_utils.time, "sleep", sleep)
    with pytest.raises(gsc_utils.ApiReadError) as caught:
        gsc_utils.execute_read(request)
    assert request.execute.call_count == calls
    assert sleep.call_count == calls - 1
    assert caught.value.details["category"] == category
    assert caught.value.details["retry_after"] == hint


def test_inspection_read_is_not_retried(monkeypatch):
    from unittest.mock import MagicMock

    import gsc_admin
    import httplib2
    from googleapiclient.errors import HttpError
    service = MagicMock()
    execute = service.urlInspection().index().inspect().execute
    execute.side_effect = HttpError(httplib2.Response({"status": "429"}), b'{}')
    monkeypatch.setattr(gsc_admin, "_get_service", lambda: service)
    with pytest.raises(RuntimeError, match="rate_or_quota_limit"):
        gsc_admin.inspect_url("example.com", "https://example.com/a")
    execute.assert_called_once_with()


def test_google_transport_has_timeout_and_disables_replay(monkeypatch):
    from unittest.mock import MagicMock

    import gsc_utils
    build = MagicMock()
    auth = MagicMock()
    http = MagicMock()
    monkeypatch.setattr("googleapiclient.discovery.build", build)
    monkeypatch.setattr("google_auth_httplib2.AuthorizedHttp", auth)
    monkeypatch.setattr("httplib2.Http", http)
    creds = object()
    gsc_utils.build_search_service(creds)
    http.assert_called_once_with(timeout=60)
    auth.assert_called_once_with(creds, http=http.return_value, max_refresh_attempts=0)
    assert build.call_args.kwargs["http"] is auth.return_value
