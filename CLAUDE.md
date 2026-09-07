# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Commands

```bash
uv sync --dev                     # once
uv run pytest                     # whole suite, offline (recorded fixtures under tests/fixtures/)
uv run pytest tests/test_cli_mail.py -k search
uv run ruff check . && uv run ruff format --check .   # same as CI; `ruff format .` to fix
uv lock --check                   # lockfile matches pyproject.toml; the shim runs --frozen
python3 scripts/scan_secrets.py   # credential scan over tracked files; CI runs it
claude plugin validate .          # manifest check; CI cannot run it

./mgraphctl mail list --json      # run the CLI from the clone through the shim
claude --plugin-dir ~/src/mgraphctl   # try the skill without installing the plugin
```

## What this repo is

A Claude Code and Codex plugin with one shared skill, `mgraphctl`, backed by a Python CLI of the same name.
The root `mgraphctl` shim runs `uv run --project <repo> --frozen --no-dev mgraphctl`, creating
the venv on first use. The marketplace installs the repo at a tag; the same tag publishes the CLI to PyPI as `mgraphctl`.

## Layout

```
mgraphctl                      # bash shim the skill calls (${CLAUDE_PLUGIN_ROOT}/mgraphctl)
src/mgraphctl/
  cli.py                       # root typer app, global options, @graph_command decorator
  commands/<noun>.py           # one module per noun: mail, calendar, chats, teams, ...
  graph/<noun>.py              # Graph API calls per noun; no rendering, no typer
  auth.py http.py odata.py     # msal sign-in and scope gate; httpx client with retries/paging
  render.py html.py resolve.py # output, HTML<->Markdown, name-vs-id resolution
  config.py errors.py fixtures.py
skills/mgraphctl/
  SKILL.md                     # the skill (<=400 lines; every verb via the shim)
  reference/commands.md        # shared conventions + index of the per-noun files
  reference/commands/<noun>.md # one `### noun verb` heading per registered verb
  evals/evals.json
tests/                         # test_cli_<noun>.py per noun; @covers ties tests to verbs
.claude-plugin/                # Claude plugin.json + marketplace.json
.codex-plugin/                 # Codex plugin.json
.agents/plugins/               # Codex marketplace.json
.claude/skills/releasing-a-version/
docs/{specs,plans,research}/   # design history; ruff excludes docs/
scripts/                       # stdlib-only helpers CI runs: scan_secrets.py, extract-changelog.sh
```

## Invariants the tests enforce

- Every registered verb has a `@covers` test, a `--json` flag, and a heading in some
  `reference/commands/<noun>.md`, which `reference/commands.md` links (`test_surface.py`,
  `test_docs.py`).
- The six version strings agree and are bare `X.Y.Z` (`test_version.py`).
- SKILL.md frontmatter follows the Agent Skills rules: name pattern, description <= 1024 chars,
  no XML-shaped tags (`test_docs.py`).

## Comments

Comments describe the code as it stands, not the changes that produced it. Write what constrains
the current implementation and leave history to git. Revise an existing comment instead of
appending a paragraph per fix.

## Branches, CI and releases

`dev` is where work lands. `main` receives merge commits from `dev` via pull request and is the
release surface. `.github/workflows/ci.yml` runs tests on Python 3.10-3.13, ruff, `uv lock
--check` and the secret scan on every push and PR.

| Artifact | Version source | Tag | Made with |
|---|---|---|---|
| mgraphctl plugin | `plugin.json` (+ five mirrors, see VERSIONING.md) | `mgraphctl--vX.Y.Z` on `main` | `claude plugin tag --push .` |
| mgraphctl on PyPI | `pyproject.toml` (same version) | same tag | the tag's Release workflow, Trusted Publishing |

Pushing the tag runs `.github/workflows/release.yml`: annotated-tag and version checks, the
suite, `uv build` + `twine check`, `uv publish` to PyPI, then a GitHub Release with notes from
the CHANGELOG section. Procedure:
`.claude/skills/releasing-a-version/SKILL.md`. Rules: `VERSIONING.md`.

`[tool.uv] exclude-newer` in `pyproject.toml` freezes resolution at a date. Dependency refreshes
are deliberate: advance the date, `uv lock`, test, commit alone.
