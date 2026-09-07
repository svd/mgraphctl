# Versioning

Three artifacts ship from this repo at one shared version: the `mgraphctl` Claude Code and Codex plugins,
installed straight from a git ref, and the `mgraphctl` Python package on PyPI, for the CLI on
its own. A release is a commit on `main` carrying a bare `X.Y.Z` version, plus the annotated
tag `mgraphctl--vX.Y.Z` that `claude plugin tag` creates on it. The tag is the distribution:
Claude installs that tag; Codex installs its configured ref. Pushing the tag publishes to PyPI.

| Artifact | Channel | Consumer command |
|---|---|---|
| Claude Code plugin | git tag via marketplace | `claude plugin install mgraphctl@mgraphctl` |
| Codex plugin | git ref via marketplace | `codex plugin add mgraphctl@mgraphctl` |
| package | PyPI | `uv tool install mgraphctl` |

One shared version, because the skill calls the CLI through the shim from the same checkout:
a skill change and a CLI change are always released together, so nothing needs to drift.

Codex follows the ref configured with `codex plugin marketplace add svd/mgraphctl --ref main`.
To pin a release, use `--ref mgraphctl--vX.Y.Z`. Its marketplace entry points at the repository
root and has no separate version field; the Codex plugin manifest carries the version.

## Bump rules

Semantic versioning, `MAJOR.MINOR.PATCH`, judged against what the skill and CLI expose.

| Bump | Trigger |
|------|---------|
| MAJOR | A verb, flag or `MGRAPHCTL_*` setting removed or renamed; a `--json` field removed or renamed; an exit code changes meaning; the config file or token cache layout changes so an existing install breaks |
| MINOR | New verb, flag, config key or Microsoft 365 surface; additive `--json` field; new eval or skill section that changes how the skill is triggered |
| PATCH | Bug fix, docs, refactor, test-only change, dependency refresh with no behaviour change |

Choose the highest bump the range since the last tag warrants.

## Conventions

- The version is one string held in six places, all bare `X.Y.Z`: `pyproject.toml`,
  `src/mgraphctl/__init__.py`, `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, the `mgraphctl` entry in
  `.claude-plugin/marketplace.json`, and `metadata.version` in `skills/mgraphctl/SKILL.md`.
  `tests/test_version.py` fails if any two disagree, and rejects `-SNAPSHOT` / `.devN` suffixes.
- Between releases the version stays at the last released value. Pending work accumulates under
  `## [Unreleased]` in `CHANGELOG.md`; a release renames that heading to `## [X.Y.Z] — YYYY-MM-DD`.
- Tags are created only with `claude plugin tag`, only on `main`, and are always annotated.
  Never hand-roll `git tag`, never pass `--force`, never move a published tag.
- `main` receives only merge commits from `dev` via pull request. `dev` is where work lands.
- `[tool.uv] exclude-newer` in `pyproject.toml` freezes dependency resolution at a date. It is
  advanced deliberately, as its own commit, when a release wants newer dependencies.

## Repository protections

Two GitHub rulesets enforce the conventions server-side. Neither has a bypass actor, so they
bind the owner too. Inspect with `gh api repos/svd/mgraphctl/rulesets`.

| Ruleset | Applies to | Rules | Consequence |
|---|---|---|---|
| `main: PR + green CI only` | `refs/heads/main` | no deletion, no force push, pull request required, merge-commit only, required checks `test (3.10/3.11/3.12/3.13)`, `lint`, `secrets` (strict: branch must be current) | `git push origin main` is rejected for everyone; a release reaches `main` only through a PR whose CI is green; squash and rebase merges are refused |
| `release tags are immutable` | `refs/tags/mgraphctl--v*` | no deletion, no force push, no update | A published tag cannot be moved or removed, by anyone. Tag creation is unrestricted, so `claude plugin tag --push` works normally |

Adding a CI job means adding its name to the required checks, or the ruleset silently stops
gating it. A tag that must go away needs the ruleset edited first, which is the intended cost.

## PyPI publishing

`.github/workflows/release.yml` publishes with uv Trusted Publishing (OIDC), so no API token is
stored anywhere. One-time setup on PyPI, Publishing → "Add a new pending publisher": project
`mgraphctl`, owner `svd`, repository `mgraphctl`, workflow `release.yml`, environment `pypi`. The
matching GitHub environment `pypi` must exist in the repo settings. A PyPI release cannot be
replaced or re-uploaded; a broken release is followed by a PATCH, never by a re-push of the tag.

## Release procedure

`.claude/skills/releasing-a-version/SKILL.md` is the step-by-step procedure. `CLAUDE.md`
summarises it.

## Version history

| Tag | Date | Summary |
|-----|------|---------|
| `mgraphctl--v0.1.0` | 2026-09-05 | Initial release: parity with `msgraph`, config file, keychain token storage, client id guard. |
| `mgraphctl--v0.2.0` | 2026-09-06 | Python floor drops to 3.10, so the plugin runs under the Claude desktop app. |
| `mgraphctl--v0.2.1` | 2026-09-06 | Command reference split into one file per noun. |
