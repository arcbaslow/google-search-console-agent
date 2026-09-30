# Release verification — v0.2.2

Date: 2026-09-08. Local environment: Windows, Python 3.12.14; Node.js 24 for GTM Diff.

129 tests passed. Ruff passed.

| Check | Command | Result |
| --- | --- | --- |
| Tests | `python -m pytest scripts/ -q` | Passed |
| Ruff | `python -m ruff check scripts/` | Passed |

## Documentation and examples

- Executed the offline example commands from README against committed synthetic fixtures.
- Captured the generated output in a browser. Screenshots are output previews, not live dashboards.
- Checked local README links, SVG syntax, image presence, release versions and whitespace.
- Built the release artifacts before publishing. Source archives contain only tracked repository files.

## Scope

The test results above are a dated local run, not a claim that every test was run locally on every CI platform. API responses are mocked where tests require them. Live authentication, account mutations, external-service behavior and paid AI calls were not exercised. The CI badge links to the actual workflow rather than a static passing label.

## Build artifacts

Source distribution and wheel built successfully; `twine check` passed. The offline report/extraction example also passed after loading the module from the extracted wheel, outside the repository.

## Roadmap work verification — 2026-09-30

Branch: `roadmap-work`, created from clean `master` at `5251dd6`. Package
version remains 0.2.2. No remote push, PR, tag or release was made.

Installed `.[dev]` into `.venv` per CONTRIBUTING.md with Python 3.12.14 on
Windows. Ruff 0.16.9 and pytest 9.1.1. The first restricted package download
failed; the approved installation succeeded. Build tooling was installed
locally for the release workflow's non-publishing checks.

| Check | Baseline | Final |
| --- | --- | --- |
| `python -m ruff check scripts/` | Passed | Passed |
| `python -m pytest scripts/ -q` | 129 passed | 265 passed |
| `python scripts/check_release_version.py v0.2.2` | Passed | Passed |
| `python -m build --no-isolation --outdir .venv/check-dist` | Passed | Passed |
| `python -m twine check .venv/check-dist/*` | Passed | Passed |
| `git diff --check` | Passed | Passed |

The baseline test run used an external pytest hook to replace only the
file-writing `fake_creds` fixture with an equivalent in-memory object.
Production code and test assertions were unchanged. N1 makes that fixture
change permanent and blocks unmocked sockets and Google ADC discovery.
No credential file was read, created or staged. All API/service tests use
synthetic fixtures and mocked transports. No remote assessment was triggered.

These checks follow `.github/workflows/tests.yml` and the non-publishing
checks in `release.yml`. Build isolation was disabled to use the already
installed local build tooling. The Ubuntu Python 3.10/3.11/3.13 matrix and
GitHub Actions were not run here. Each local commit passed lint, tests,
version consistency, build, artifact validation and whitespace checks before
being committed.

A coverage diagnostic after the feature commits (264 tests, before the final
header-failure regression) measured PSI 97%, CrUX 75%, admin 60% and audit 70%,
up from 0%, 17%, 44% and 66% respectively. Auth remained 38%; interactive and
live authentication were deliberately not exercised. Coverage is supporting
evidence, not proof of correctness. The final suite has one additional test.

### Commit record

| Commit | Change | Tests passing before commit |
| --- | --- | --- |
| `404f63a` | Document the evidence and scoped roadmap | 129 |
| `852406b` | Keep test authentication in memory and block network access | 129 |
| `b13e7fc` | Require confirmation at every Search Console write boundary | 162 |
| `07dba00` | Use the synchronous Observatory scan endpoint | 166 |
| `39b9952` | Bound SSL polling and retain independent security results | 174 |
| `7da3a6d` | Retain partial audits when a source fails | 182 |
| `9d18d4a` | Compare sitemap error counts numerically | 187 |
| `653597c` | Resolve origins and domains from URL-prefix properties | 190 |
| `e1196c6` | Correct CrUX aggregate requests and history values | 211 |
| `310bc05` | Limit structured data verdicts to supported checks | 222 |
| `0b88860` | Disclose CTR heuristic limits and fix position twenty | 228 |
| `1330183` | Honor domain lookup keys and reject oversized requests | 231 |
| `bf60e33` | Keep independent domain source results in audits | 236 |
| `240cb2a` | Expose full PageSpeed diagnostics on request | 249 |
| `cd2132b` | Expose explicit Search Analytics result offsets | 264 |
| `7707936` | Align runtime guidance with verified adapter limits | 264 |
| `cbda76c` | Avoid duplicate header failure findings | 265 |

The completion-record commit adds this final verification result without
changing runtime behavior. See [ROADMAP.md](ROADMAP.md) for source URLs,
Next/Later work, rejected ideas, effort, risk and unverified upstream behavior.

### Review limits

The source review and mocked tests establish local request construction,
error handling, cache use and parsing behavior. They do not establish service
uptime, real-account access, project quota availability or legal permission
for a particular commercial use. HTTP socket timeouts bound blocking calls,
not total slow-stream duration. No blanket retry policy was added.

The roadmap retains the larger Open PageRank migration, context-aware schema
rules, date/hourly queries, quota-aware transport, cache privacy/consistency,
XML/trend fixes, expanded CrUX metrics and report parity as proposals. MCP,
storage/export, learned CTR references and GA4 integration remain Later.
Uncertain PSI units/authentication and ambiguous audit policies were left
unchanged. No bulk inspection or new write surface was added.
