# Setup

The default auth path uses Google's own ADC flow through gcloud. You do
not need to create a Cloud OAuth client of your own. The fallback path
(client-secret JSON) is only there for environments where gcloud cannot
be installed.

## 1. Install gcloud

[Cloud SDK install docs](https://cloud.google.com/sdk/docs/install). On
macOS via Homebrew: `brew install --cask google-cloud-sdk`. On Windows:
download the installer from the Cloud SDK page.

Verify:

```
gcloud --version
```

## 2. Enable APIs on any Cloud project you have access to

The project doesn't need to be dedicated to this plugin. User ADC
needs a "quota project" to bill API calls against.

```
gcloud config set project <PROJECT_ID>
gcloud services enable searchconsole.googleapis.com \
                       pagespeedonline.googleapis.com \
                       chromeuxreport.googleapis.com
```

## 3. Authenticate (default path: gcloud ADC)

For read-only analysis:

```
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/webmasters.readonly,\
https://www.googleapis.com/auth/cloud-platform
```

For sitemap and site CRUD, include the `webmasters` write scope:

```
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/webmasters,\
https://www.googleapis.com/auth/cloud-platform
```

Set the quota project:

```
gcloud auth application-default set-quota-project <PROJECT_ID>
```

Verify the plugin can resolve credentials:

```
python scripts/gsc_auth.py --check
python scripts/gsc_auth.py --sites
```

If you forget the gcloud command, the plugin can print it:

```
python scripts/gsc_auth.py --adc          # read scope
python scripts/gsc_auth.py --adc --write  # write scope
```

The same ADC token works against PageSpeed Insights and the Chrome UX
Report API — no separate API keys.

## 4. Confirm property ownership

GSC's API only returns data for properties the authenticated Google
account has at least Restricted access to. Add yourself as a user in
the Search Console UI (Settings → Users and permissions) before
running the audit.

## 5. Try a single command

```
python scripts/gsc_data.py --site example.com --queries --days 7 --rows 25 --json
```

If queries come back, you're set.

## 6. Run the full audit

From any runtime (Codex, Gemini CLI, plain shell):

```
python scripts/gsc_audit.py --site example.com --output audit.md
```

The driver runs context → search analytics → CTR-curve → sitemap
health → Core Web Vitals (CrUX) in parallel, then renders a markdown
report (`--format md`, default) with benchmark verdicts attached to
quantified findings. Pass `--format html` or `--format pdf` for the
other renderings.

From inside Claude Code:

```
/gsc audit example.com
```

This goes through the LLM-powered specialist agents and produces a
richer report. The mechanical driver above is the same shape but
deterministic, useful in CI or under runtimes without subagent support.

## 7. Inspect benchmarks

```
python scripts/gsc_benchmarks.py --list
python scripts/gsc_benchmarks.py --compare lcp_p75_ms 3200
python scripts/gsc_benchmarks.py --ctr-curve
python scripts/gsc_benchmarks.py --compare ctr_position 3.1 --observed 0.048 --impressions 8200
```

CWV thresholds match Google's official Core Web Vitals report bands.
The CTR-by-position curve is a 2024 composite (FirstPageSage, Backlinko,
Sistrix) — treat it as directional. Treatments such as AI overviews,
featured snippets, and image packs distort the curve at the top of the
SERP.

## Fallback: BYO OAuth client

If you cannot install gcloud (CI without sudo, locked-down workstation),
register your own Cloud OAuth client and feed it to the plugin:

1. Open [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project, or pick an existing one
3. APIs & Services → Library: enable the Search Console API,
   PageSpeed Insights API, and Chrome UX Report API
4. APIs & Services → Credentials → Create Credentials → OAuth client ID
5. Configure the OAuth consent screen (External or Internal). Add
   yourself as a test user.
6. Application type: Desktop app
7. Download the JSON credentials file
8. Authenticate the plugin:

```
python scripts/gsc_auth.py --oauth --client-secret-file /path/to/client_secret_xxx.json
```

For write scope, add `--write`:

```
python scripts/gsc_auth.py --oauth --write --client-secret-file /path/to/client_secret_xxx.json
```

Credentials stored at `~/.claude/gsc-credentials.json` with file mode
0600 on POSIX. Refresh tokens expire after 6 months of inactivity or
if revoked.

## Troubleshooting

**`403 Forbidden` from Search Console API**

The authenticated account does not have access to the property.
Verify in Search Console UI → Settings → Users and permissions.

**`403 PERMISSION_DENIED: User does not have serviceusage.services.use`**

Quota project not set or the account lacks permission on it. Run
`gcloud auth application-default set-quota-project <PROJECT_ID>`
against a project you own.

**CrUX returns `no_data`**

The origin or URL has insufficient Chrome traffic. CrUX is
field-aggregated; small or new sites are below the inclusion threshold.
For per-URL synthetic data on those pages use PageSpeed Insights
instead.

**PSI takes 30+ seconds per URL**

Normal. Each call is a fresh Lighthouse run on Google's infrastructure.
Cache to disk between repeated invocations — the script does this
automatically with a 15-minute TTL.

**Quota exceeded on URL inspection**

URL Inspection is the heaviest GSC endpoint: 2,000 calls/day,
600/minute per property. Use the audit driver for breadth and reserve
URL inspection for targeted single-URL diagnostics.
