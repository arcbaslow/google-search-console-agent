# CLAUDE.md

Instructions for Claude Code working with `google-search-console-agent`.
Most of the universal guidance lives in [AGENTS.md](AGENTS.md); this
file covers Claude Code-specific notes only.

## Skills and subagents

Claude Code loads `skills/gsc/SKILL.md` as the top-level router. It
exposes `/gsc <command>` and routes to:

- read skills: `gsc-audit`, `gsc-search-analytics`, `gsc-ctr-curve`,
  `gsc-url-inspect`, `gsc-core-web-vitals`, `gsc-pagespeed`,
  `gsc-sitemaps`
- write surfaces (sitemap CRUD, site CRUD): also `gsc-sitemaps`

The `gsc-audit` skill calls `scripts/gsc_audit.py` directly — it's a
deterministic mechanical orchestrator. For richer LLM-driven analysis
on any single dimension, spawn the matching specialist subagent
defined under `agents/`.

## When to use Bash vs the Skills

Skills are sugar for the same Python adapters. If a user invokes `/gsc
audit`, use the skill. If a user asks a one-off question that maps to
a single script flag (e.g. "list sitemaps on example.com"), call the
script directly via the Bash tool:

```
python scripts/gsc_admin.py --site example.com --list-sitemaps --json
```

## Confirmation before writes

For every write (sitemap submit / delete, site add / delete), the
subagent (or you, if invoking directly) must show the resolved URL,
ask `y/N`, then run the command. Skill bodies wire this in; don't
bypass.

## Auth

Default path is gcloud Application Default Credentials. The same
token works against GSC, PSI, and CrUX:

```
python scripts/gsc_auth.py --check
python scripts/gsc_auth.py --adc            # prints the gcloud command
python scripts/gsc_auth.py --adc --write    # with webmasters write scope
```

Run the printed command, then `--check` again.

## Reports and benchmarks

Audit output defaults to markdown (no emoji) via
`scripts/gsc_audit.py --format md` or the lower-level
`scripts/gsc_report.py --format md`. The report attaches the site
context (permission level, sitemap inventory, homepage probe), the
data-confidence label, and benchmark verdicts to every finding that
carries a `metric` / `metric_value` pair. Benchmarks live in
`scripts/gsc_benchmarks.py` (CWV thresholds + position-CTR curve).
Pass `--format html` or `--format pdf` when the user wants those.

## Style for commits and output

- No marketing copy. Plain factual statements.
- No `feat:` / `fix:` / `chore:` Conventional Commits prefixes.
- No `Co-Authored-By:` trailers, no `Generated with...` footers, no emoji.
- Commit message style: short imperative sentence, sentence-case acceptable.
