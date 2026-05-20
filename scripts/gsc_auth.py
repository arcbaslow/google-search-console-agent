"""
GSC authentication.

Three resolution paths, tried in order:

  1. GOOGLE_APPLICATION_CREDENTIALS env var (service account / external account)
  2. gcloud user ADC at the well-known path (default for end users)
  3. Legacy OAuth installed-app flow with ~/.claude/gsc-credentials.json

Most users only need (2): install gcloud, then run

    gcloud auth application-default login \
        --scopes=https://www.googleapis.com/auth/webmasters.readonly,\
https://www.googleapis.com/auth/cloud-platform

Add `webmasters` (without the .readonly suffix) for write features
(sitemap submit/delete).

The same ADC token also works against the PageSpeed Insights and Chrome
UX Report APIs, so this module is the single auth entrypoint for the
whole toolkit.

Usage:
  python scripts/gsc_auth.py --check
  python scripts/gsc_auth.py --adc                # print the gcloud command
  python scripts/gsc_auth.py --quota-project ID   # set ADC quota project
  python scripts/gsc_auth.py --sites
  python scripts/gsc_auth.py --oauth --client-secret-file <path>   # fallback
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

SCOPES_READ = ["https://www.googleapis.com/auth/webmasters.readonly"]
SCOPES_WRITE = ["https://www.googleapis.com/auth/webmasters"]
CLOUD_PLATFORM = "https://www.googleapis.com/auth/cloud-platform"

CREDENTIALS_PATH = Path.home() / ".claude" / "gsc-credentials.json"
TOKEN_REFRESH_BUFFER_SECONDS = 300


class AuthRequiredError(RuntimeError):
    """Raised when no credential path resolves. Carries a hint string for the CLI."""

    def __init__(self, hint: str):
        super().__init__(hint)
        self.hint = hint


def scopes_for(write: bool) -> list[str]:
    return SCOPES_WRITE if write else SCOPES_READ


def adc_command(write: bool) -> str:
    """Exact gcloud command the user needs to run for the requested scopes."""
    scopes = scopes_for(write) + [CLOUD_PLATFORM]
    return "gcloud auth application-default login --scopes=" + ",".join(scopes)


# ---------- legacy OAuth installed-app flow ----------

def _ensure_creds_dir() -> None:
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)


def _save_credentials(creds: dict[str, Any]) -> None:
    _ensure_creds_dir()
    with open(CREDENTIALS_PATH, "w") as f:
        json.dump(creds, f, indent=2)
    try:
        os.chmod(CREDENTIALS_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except (PermissionError, OSError):
        pass


def _load_credentials() -> dict[str, Any] | None:
    if not CREDENTIALS_PATH.exists():
        return None
    with open(CREDENTIALS_PATH) as f:
        return json.load(f)


def _expiring_soon(expiry_iso: str | None) -> bool:
    if not expiry_iso:
        return True
    from datetime import datetime, timezone

    expiry = datetime.fromisoformat(expiry_iso)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    seconds_left = (expiry - datetime.now(timezone.utc)).total_seconds()
    return seconds_left < TOKEN_REFRESH_BUFFER_SECONDS


def refresh_if_needed(creds_dict: dict[str, Any]) -> dict[str, Any]:
    """Refresh the legacy-OAuth access token if it's near expiry."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials(
        token=creds_dict["token"],
        refresh_token=creds_dict["refresh_token"],
        token_uri=creds_dict["token_uri"],
        client_id=creds_dict["client_id"],
        client_secret=creds_dict["client_secret"],
        scopes=creds_dict["scopes"],
    )
    if creds.expired or _expiring_soon(creds_dict.get("expiry")):
        creds.refresh(Request())
        creds_dict["token"] = creds.token
        creds_dict["expiry"] = creds.expiry.isoformat() if creds.expiry else None
        _save_credentials(creds_dict)
    return creds_dict


def run_oauth_flow(client_secret_file: str, write: bool = False) -> dict[str, Any]:
    """Fallback path. Runs an OAuth installed-app flow against the user-
    supplied Cloud OAuth client and saves the resulting refresh token under
    ~/.claude/gsc-credentials.json."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, scopes_for(write))
    creds = flow.run_local_server(port=0)
    payload = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }
    _save_credentials(payload)
    return payload


# ---------- unified resolver ----------

def _legacy_credentials(write: bool):
    from google.oauth2.credentials import Credentials

    cd = _load_credentials()
    if not cd:
        return None
    cd["scopes"] = sorted(set(cd.get("scopes", []) + scopes_for(write)))
    refresh_if_needed(cd)
    return Credentials(
        token=cd["token"],
        refresh_token=cd["refresh_token"],
        token_uri=cd["token_uri"],
        client_id=cd["client_id"],
        client_secret=cd["client_secret"],
        scopes=cd["scopes"],
    )


def get_credentials(write: bool = False):
    """Resolve Google credentials. Returns a google-auth Credentials object.
    Raises AuthRequiredError with an actionable hint if nothing resolves."""
    scopes = scopes_for(write)
    source = None

    try:
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError

        try:
            creds, _project = google.auth.default(scopes=scopes)
            if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
                source = "env_GOOGLE_APPLICATION_CREDENTIALS"
            else:
                source = "gcloud_adc"
            return _tagged(creds, source)
        except DefaultCredentialsError:
            pass
    except ImportError:
        pass

    legacy = _legacy_credentials(write)
    if legacy is not None:
        return _tagged(legacy, "legacy_oauth")

    raise AuthRequiredError(
        "No credentials found. Run:\n  "
        + adc_command(write)
        + "\nOr use the OAuth fallback:\n  python scripts/gsc_auth.py --oauth "
        + "--client-secret-file <path>"
    )


def _tagged(creds, source: str):
    try:
        creds._gsc_source = source
    except Exception:
        pass
    return creds


def credentials_source(creds) -> str:
    return getattr(creds, "_gsc_source", "unknown")


# ---------- ADC quota project ----------

def set_quota_project(project_id: str) -> dict[str, Any]:
    cmd = ["gcloud", "auth", "application-default", "set-quota-project", project_id]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return {"status": "gcloud_not_found", "hint": "Install Google Cloud SDK first."}
    if result.returncode != 0:
        return {"status": "error", "stderr": result.stderr.strip()}
    return {"status": "ok", "project": project_id}


# ---------- CLI ----------

def check_auth() -> bool:
    try:
        creds = get_credentials(write=False)
    except AuthRequiredError as e:
        print(json.dumps({"status": "no_credentials", "hint": e.hint}))
        return False
    except Exception as e:
        print(json.dumps({"status": "error", "type": type(e).__name__, "error": str(e)}))
        return False

    info = {"status": "ok", "source": credentials_source(creds)}
    expiry = getattr(creds, "expiry", None)
    if expiry:
        info["expiry"] = expiry.isoformat()
    print(json.dumps(info))
    return True


def list_sites() -> list[dict[str, Any]]:
    """List Search Console properties accessible to the authenticated user."""
    creds = get_credentials(write=False)
    from googleapiclient.discovery import build

    service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    resp = service.sites().list().execute()
    out = []
    for s in resp.get("siteEntry", []):
        out.append({
            "site_url": s.get("siteUrl"),
            "permission_level": s.get("permissionLevel"),
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="GSC authentication")
    parser.add_argument("--check", action="store_true", help="Verify resolved credentials")
    parser.add_argument("--adc", action="store_true", help="Print the gcloud command to run")
    parser.add_argument("--write", action="store_true", help="Include webmasters (write) scope")
    parser.add_argument("--quota-project", help="Set ADC quota project")
    parser.add_argument("--sites", action="store_true", help="List Search Console properties")
    parser.add_argument("--oauth", action="store_true", help="Fallback OAuth installed-app flow")
    parser.add_argument("--client-secret-file", help="Path to OAuth client_secret JSON (with --oauth)")
    args = parser.parse_args()

    if args.adc:
        print(adc_command(args.write))
        return 0

    if args.quota_project:
        print(json.dumps(set_quota_project(args.quota_project)))
        return 0

    if args.oauth:
        if not args.client_secret_file:
            print("ERROR: --client-secret-file required with --oauth", file=sys.stderr)
            return 1
        run_oauth_flow(args.client_secret_file, write=args.write)
        print(json.dumps({"status": "authenticated", "source": "legacy_oauth"}))
        return 0

    if args.check:
        return 0 if check_auth() else 1

    if args.sites:
        try:
            sites = list_sites()
        except AuthRequiredError as e:
            print(json.dumps({"error": "no_credentials", "hint": e.hint}), file=sys.stderr)
            return 1
        print(json.dumps(sites, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
