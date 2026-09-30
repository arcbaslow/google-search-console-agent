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

## 3. Install Python deps

The fastest path is [`uv`](https://github.com/astral-sh/uv):

```
uv venv
uv pip install -r scripts/requirements.txt
```

Or plain `pip`:

```
python -m venv .venv
source .venv/bin/activate              # or .venv\Scripts\Activate.ps1 on Windows
pip install -r scripts/requirements.txt
```

For PDF report rendering (optional — markdown is the default):

```
pip install -e ".[pdf]"
```

For development (running tests, lint):

```
pip install -e ".[dev]"
```

## 4. Authenticate (default path: gcloud ADC)

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

## 5. Confirm property ownership

GSC's API only returns data for properties the authenticated Google
account has at least Restricted access to. Add yourself as a user in
the Search Console UI (Settings → Users and permissions) before
running the audit.

## 6. Try a single command

```
python scripts/gsc_data.py --site example.com --queries --days 7 --rows 25 --json
```

If queries come back, you're set.

## 7. Run the full audit

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

This invokes the same deterministic driver. Specialist agents can interpret
individual outputs separately; the audit skill does not delegate them.

## 8. Inspect benchmarks

```
python scripts/gsc_benchmarks.py --list
python scripts/gsc_benchmarks.py --compare lcp_p75_ms 3200
python scripts/gsc_benchmarks.py --ctr-curve
python scripts/gsc_benchmarks.py --compare ctr_position 3.1 --observed 0.048 --impressions 8200
```

CWV thresholds match Google's official Core Web Vitals report bands.
FCP and TTFB are diagnostics, listed separately from the three Core Web
Vitals. The CTR curve is a legacy heuristic with unverified composite
provenance, not a forecast. Comparisons include `benchmark_basis`. Review
SERP features, intent, device and brand mix before proposing a rewrite.
The raw `--ctr-curve` table keeps its existing shape and numeric values.

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

## Confirming writes

Direct CLI and Python sitemap/site writes print resolved targets to stderr
and ask `Apply? [y/N]`. Only `y` executes the request. No answer cancels;
there is no `--yes` option. Agent users must answer the same prompt.

## Observatory API

The page-experience adapter uses the synchronous Mozilla Observatory v2
[scan endpoint](https://developer.mozilla.org/en-US/observatory/docs/faq).
It makes one POST and does not poll. Results are public, and the service
returns cached scans within its cooldown. Header grades describe security
posture and do not prove a ranking effect.

## SSL Labs use and timeouts

SSL Labs requests send the host to Qualys servers. Use only with the site
owner's permission. Commercial use requires Qualys permission; see the
[API terms](https://www.ssllabs.com/downloads/Qualys_SSL_Labs_Terms_of_Use.pdf).
The adapter displays these terms and `info` messages before assessment.

Polling is scheduled within 120 seconds using a monotonic clock and socket
timeouts capped to the remaining budget. urllib timeouts are socket-level,
so a slowly streaming response may exceed the wall-clock budget. Incomplete
scans return an explicit timeout error, not a grade. 429/503/529 responses
return retry hints without automatic retries. `--no-cache` starts one fresh
scan in single or combined mode. A failing source does not discard the
other results.

## Partial audit output

An unexpected adapter failure is recorded under that source while successful
workers are retained. Security-source errors appear as unavailable findings.
The driver still omits URL Inspection. Confidence drops to low for a failed
search worker; other existing confidence rules are unchanged.

Sitemap error and warning counts are compared numerically, including Google API string values such as `"0"`; a zero count does not produce a finding.

For URL-prefix properties, the audit derives CrUX origins from scheme and authority only. Domain-rank comparisons use the exact hostname, not the property path or a suffix match. Search Console requests keep the original property.

Use `--history --periods 40` for the maximum history; default remains 25.
Periods are overlapping 28-day aggregates sampled weekly. `ALL_FORM_FACTORS`
omits the wire filter. Missing p75 values are null, not zeros. Only LCP,
INP and CLS determine the Core Web Vitals pass; FCP/TTFB are diagnostics.

## Structured-data report limits

The local JSON-LD check reports `unchecked` for unknown or contextual types
and `unsupported` for retired FAQPage/HowTo rich results. It cannot guarantee
Google eligibility. `urls_analyzed` counts successful fetches; compare that
with `urls_attempted` and `fetch_failures` before interpreting coverage.
Invalid JSON remains visible in the block verdict rollup. See the
[structured-data skill](../skills/gsc-structured-data/SKILL.md).
