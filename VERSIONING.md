# Versioning

One artifact ships from this repo: the `mgraphctl` Claude Code plugin, installed straight from
a git ref. There is no PyPI package and no archive. A release is a commit on `main` carrying a
bare `X.Y.Z` version, plus the annotated tag `mgraphctl--vX.Y.Z` that `claude plugin tag`
creates on it. The tag is the distribution: the marketplace entry points at it.

## Bump rules

Semantic versioning, `MAJOR.MINOR.PATCH`, judged against what the skill and CLI expose.

| Bump | Trigger |
|------|---------|
| MAJOR | A verb, flag or `MGRAPHCTL_*` setting removed or renamed; a `--json` field removed or renamed; an exit code changes meaning; the config file or token cache layout changes so an existing install breaks |
| MINOR | New verb, flag, config key or Microsoft 365 surface; additive `--json` field; new eval or skill section that changes how the skill is triggered |
| PATCH | Bug fix, docs, refactor, test-only change, dependency refresh with no behaviour change |

Choose the highest bump the range since the last tag warrants.

## Conventions

- The version is one string held in five places, all bare `X.Y.Z`: `pyproject.toml`,
  `src/mgraphctl/__init__.py`, `.claude-plugin/plugin.json`, the `mgraphctl` entry in
  `.claude-plugin/marketplace.json`, and `metadata.version` in `skills/mgraphctl/SKILL.md`.
  `tests/test_version.py` fails if any two disagree, and rejects `-SNAPSHOT` / `.devN` suffixes.
- Between releases the version stays at the last released value. Pending work accumulates under
  `## [Unreleased]` in `CHANGELOG.md`; a release renames that heading to `## [X.Y.Z] — YYYY-MM-DD`.
- Tags are created only with `claude plugin tag`, only on `main`, and are always annotated.
  Never hand-roll `git tag`, never pass `--force`, never move a published tag.
- `main` receives only merge commits from `dev` via pull request. `dev` is where work lands.
- `[tool.uv] exclude-newer` in `pyproject.toml` freezes dependency resolution at a date. It is
  advanced deliberately, as its own commit, when a release wants newer dependencies.

## Release procedure

`.claude/skills/releasing-a-version/SKILL.md` is the step-by-step procedure. `CLAUDE.md`
summarises it.

## Version history

| Tag | Date | Summary |
|-----|------|---------|
| — | — | No release yet. `0.1.0` is pending on `dev`. |
