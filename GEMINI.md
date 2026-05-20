# GEMINI.md

Instructions for Gemini CLI working with `google-search-console-agent`.
Most of the universal guidance lives in [AGENTS.md](AGENTS.md); this
file covers Gemini-specific notes only.

## Tool-name mapping

Gemini CLI's built-in tool names differ from Claude Code's. When a
skill or instruction mentions a Claude tool, use the Gemini equivalent:

| Claude Code tool | Gemini equivalent |
|------------------|--------------------|
| `Bash` | `run_shell_command` |
| `Read` | `read_file` |
| `Edit` | `replace` |
| `Write` | `write_file` |
| `Grep` | `search_file_content` |
| `Glob` | `glob` |

The Python CLI under `scripts/` is the same on both runtimes.

## Skill activation

Gemini CLI activates skills via the `activate_skill` tool. The
`skills/gsc/SKILL.md` description triggers on GSC- and SEO-related
prompts. Once activated, follow the routing table in that file.

## How to invoke the toolkit

```
# Ask the user which property if not given
python scripts/gsc_auth.py --check
python scripts/gsc_auth.py --sites

# One-command full audit
python scripts/gsc_audit.py --site example.com --output audit.md

# Or call individual adapters
python scripts/gsc_data.py --site example.com --queries --days 28 --json
python scripts/gsc_crux.py --origin https://example.com --json
python scripts/gsc_psi.py --url https://example.com/products/foo --json

# Free open-data signals — no API keys (Tranco) or one free key (Open PageRank)
python scripts/gsc_backlinks.py --compare example.com,competitor.com --json
python scripts/gsc_page_experience.py --host example.com --json
python scripts/gsc_structured_data.py --site example.com --sample 25 --json
```

For the full command list, see [AGENTS.md](AGENTS.md).

## Confirmation before writes

For every write (sitemap submit / delete, site add / delete), show the
resolved URL, ask `y/N`, then execute. Never batch writes without
confirmation.

## Auth

The default auth path is gcloud Application Default Credentials. The
same token works against the GSC, PageSpeed Insights, and Chrome UX
Report APIs:

```
python scripts/gsc_auth.py --adc            # prints the gcloud command
python scripts/gsc_auth.py --adc --write    # with webmasters write scope
```

## Benchmark-aware findings

When emitting an analysis finding with a Core Web Vital, include both
`metric` and `metric_value` keys on the finding object. The markdown
reporter calls `gsc_benchmarks.compare_cwv()` against Google's
official thresholds and appends a verdict phrase to the finding line.
