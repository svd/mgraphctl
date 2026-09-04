---
name: releasing-a-version
description: Use when releasing, cutting, tagging, or shipping a new version of the mgraphctl plugin - bumping the five version strings, rolling the CHANGELOG [Unreleased] block into a dated header, opening the dev->main pull request, and cutting the mgraphctl--vX.Y.Z tag with `claude plugin tag`. Specific to the mgraphctl repo.
---

# Releasing a version

One artifact ships from this repo, in one tag form. No PyPI, no archive. The tag is the
distribution: the marketplace installs the repo at that ref. Rules live in `VERSIONING.md`.

| Artifact | Version files | Tag form | Tag branch |
|---|---|---|---|
| mgraphctl plugin | `pyproject.toml`, `src/mgraphctl/__init__.py`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` (`plugins[name=mgraphctl].version`), `skills/mgraphctl/SKILL.md` (`metadata.version`) | `mgraphctl--vX.Y.Z` (annotated, via `claude plugin tag`) | `main` only |

`marketplace.json` top-level `version` is the catalog's own version — leave it alone.

Single worktree, both `dev` and `main` local. GitHub: use `gh`. No `-SNAPSHOT`, no `.devN`:
the version stays at the last release between releases and `tests/test_version.py` rejects
suffixes. Pending work accumulates under `## [Unreleased]` in `CHANGELOG.md`.

Pushing the tag runs `.github/workflows/release.yml`, which re-checks the tag against the
version files, runs the suite, and publishes a GitHub Release whose notes are the CHANGELOG
section for that version. **The release is finished when that workflow is green.**

---

## Step 1 - Decide the bump

```bash
git checkout dev && git pull
git describe --tags --abbrev=0 --match 'mgraphctl--v*'   # last release; errors if none yet
git log <last-tag>..HEAD --oneline                        # commits in this release
```

Apply the bump table in `VERSIONING.md`. The `## [Unreleased]` bullets in `CHANGELOG.md` are the
source of truth for both the bump and the notes; if they lag the commit range, fix the changelog
first as its own commit.

## Step 2 - Precheck

```bash
git status                       # clean
gh run list --branch dev -L 3    # CI green on the tip of dev
uv lock --check                  # lockfile matches pyproject.toml (the shim runs --frozen)
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
python3 scripts/scan_secrets.py
claude plugin validate .         # CI cannot run this; here is the only place it happens
```

**Dependency refresh (optional, decide explicitly).** `pyproject.toml` pins
`[tool.uv] exclude-newer` to a date; nothing published after it can enter `uv.lock`. To take
newer dependencies into this release, advance the date, run `uv lock`, run the suite, and
commit that alone:

```bash
# edit [tool.uv] exclude-newer = "<today>T00:00:00Z"
uv lock && uv run pytest -q
git add pyproject.toml uv.lock && git commit -m "chore(deps): refresh lock to <today>"
```

Skipping it is a valid choice, but say so in the release notes if a known fix is left out.

## Step 3 - Release commit on `dev`

Set the version in all five files. `uv version` handles the first and keeps `uv.lock` in step;
the rest are direct edits:

```bash
uv version X.Y.Z                                   # pyproject.toml + uv.lock
# src/mgraphctl/__init__.py            __version__ = "X.Y.Z"
# .claude-plugin/plugin.json           "version": "X.Y.Z"
# .claude-plugin/marketplace.json      plugins[0].version = "X.Y.Z"   (not the top-level one)
# skills/mgraphctl/SKILL.md            metadata.version: "X.Y.Z"
```

`CHANGELOG.md`: rename `## [Unreleased]` to `## [X.Y.Z] — YYYY-MM-DD` (`date +%F`, em dash as
in the existing headers). Do not add a fresh `[Unreleased]` yet — it appears with the first
post-release change, so the file never carries an empty section.

`VERSIONING.md`: add a row to the version-history table.

```bash
uv run pytest tests/test_version.py tests/test_docs.py -q     # the five strings agree
git add pyproject.toml uv.lock src/mgraphctl/__init__.py .claude-plugin/ skills/mgraphctl/SKILL.md CHANGELOG.md VERSIONING.md
git commit -m "$(cat <<'EOF'
chore(release): vX.Y.Z

- bullet one (from the CHANGELOG entry)
- bullet two
EOF
)"
git push origin dev
```

The commit contains the release edits and nothing else.

## Step 4 - Pull request `dev` -> `main`

```bash
gh pr create --base main --head dev --title "chore(release): vX.Y.Z" --body-file <(scripts/extract-changelog.sh X.Y.Z)
gh pr checks --watch
gh pr merge --merge          # merge commit, never squash: the release commit is what the tag points at
```

## Step 5 - Tag on `main`

**Irreversible. Never move a published tag.**

`claude plugin tag` tags HEAD of the current checkout, so be on `main` with the merge pulled:

```bash
git checkout main && git pull
grep '"version"' .claude-plugin/plugin.json          # bare X.Y.Z

claude plugin tag --dry-run .                        # read the Tag: line back: mgraphctl--vX.Y.Z
claude plugin tag --push .
```

The command reads `plugin.json`, checks it against the marketplace entry, refuses a dirty tree
or an existing tag, and creates an annotated tag. Never pass `-f`; never hand-roll `git tag`.

## Step 6 - Verify the release workflow

```bash
gh run watch                                          # the Release workflow for the tag
gh release view mgraphctl--vX.Y.Z
```

Red workflow means the tag exists but nothing was published. Fix on `dev`, release again as a
PATCH; do not move the tag.

## Step 7 - Sync `dev` and update the marketplace pointer

```bash
git checkout dev && git merge main && git push origin dev
```

If the plugin is listed in `~/src/agent-skills` (`svd-agent-skills` marketplace), bump that
entry's `source.ref` to `mgraphctl--vX.Y.Z` there and release that repo per its own skill.

---

## Common mistakes

| Mistake | Effect |
|---|---|
| Bumped some of the five version files | `test_version.py` fails; `claude plugin tag` refuses if the two manifests disagree |
| Touched `marketplace.json` top-level `version` | That is the catalog's version, unrelated to the plugin |
| Left `[Unreleased]` undated | Release workflow fails: no CHANGELOG section for the version |
| Ran `claude plugin tag` on `dev` | Tags HEAD wherever you are; consumers pin a commit that may never reach `main` |
| Hand-rolled `git tag vX.Y.Z` | Wrong tag form for the Release workflow; skips the manifest check; may be lightweight |
| Squashed the release PR | The tag lands on a synthetic commit whose message is not the release commit |
| Passed `-f` to `claude plugin tag` | Skips the dirty-tree and tag-exists checks that stop a published tag from moving |
| Advanced `exclude-newer` inside the release commit | Dependency changes hide in a version bump; make it its own commit |
| Skipped `claude plugin validate .` because CI is green | CI has no Claude Code CLI; local is the only run |
| Moved a published tag | Consumers pinned to it break — never do this |
