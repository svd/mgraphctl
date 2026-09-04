# mgraphctl

Microsoft 365 access from Claude Code through the Microsoft Graph API: Outlook mail and
calendar, Teams chats and channel messages, presence, meetings and transcripts, SharePoint,
OneDrive, OneNote, Planner, Microsoft To Do, AI meeting insights, contacts, and the org chart.

The plugin ships a single skill, `mgraphctl`. It is a Python re-implementation of the `msgraph`
skill, run with `uv`, with a noun-verb command line (`mail list`, `calendar create`, `chats dm`,
…) instead of Node's flag-driven modes. It is an original design for this repository — not a
port of, and not tracking, any upstream project — and it extends the Node skill's coverage with
mail triage, mailbox settings and automatic replies, scheduling (`getSchedule`,
`findMeetingTimes`), find-or-create Teams DMs, presence, SharePoint lists and uploads, OneDrive
writes and sharing links, a unified `search` command, and a raw `api` escape hatch. Every write
verb supports `--dry-run`, and no data command ever opens a browser.

## Install

```bash
claude plugin marketplace add svd/mgraphctl
claude plugin install mgraphctl@mgraphctl
```

## Prerequisite: uv

The only prerequisite is [`uv`](https://docs.astral.sh/uv/). On first use in a given environment,
the plugin's shim script creates a Python virtual environment and installs the CLI's dependencies
automatically — this takes about 10-40 seconds once; every run after that starts immediately.
Nothing else needs to be installed by hand.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh          # macOS / Linux
brew install uv                                            # macOS, via Homebrew
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows
```

## First run and login

Check status first — it never opens a browser and always says what to do next:

```bash
${CLAUDE_PLUGIN_ROOT}/mgraphctl status
```

Signing in is interactive, so run it yourself in your own terminal rather than asking Claude to
run it for you:

```bash
${CLAUDE_PLUGIN_ROOT}/mgraphctl login
```

By default `login` opens your system browser for a Microsoft sign-in page. On a host with no
browser (for example over SSH), use the device-code flow instead, which prints a URL and a code
to enter on another device:

```bash
${CLAUDE_PLUGIN_ROOT}/mgraphctl login --device-code
```

On Windows, or wherever the bash shim cannot run, invoke `uv` directly:

```bat
set UV_PROJECT_ENVIRONMENT=%LOCALAPPDATA%\mgraphctl\venv
uv run --project <plugin> --frozen --no-dev mgraphctl login
```

Every other command reads the cached sign-in silently and never opens a browser or a device-code
prompt — a missing or expired token fails with an actionable hint instead.

## Where things live

- Virtual environment: under `${CLAUDE_PLUGIN_DATA}` when Claude Code sets it, otherwise
  `~/.cache/mgraphctl/venv` (`$XDG_CACHE_HOME/mgraphctl/venv` when that variable is set).
  Persistent across plugin updates; safe to delete, it is rebuilt on the next run.
- Token cache: `~/.mgraphctl/token_cache.json`, mode `0600`, in a `0700` directory. Plaintext
  msal JSON — there is no keychain integration.
- Config file: `~/.mgraphctl/config.toml`, optional (`--config PATH` or `MGRAPHCTL_CONFIG` to
  point elsewhere). Every `MGRAPHCTL_*` setting can go there as the name without the prefix,
  lower-cased; a flag beats an environment variable, which beats the file. `mgraphctl config init`
  writes a commented template, `mgraphctl config set tz Europe/Warsaw` edits one key, and
  `mgraphctl config show` prints where each value came from.

  ```toml
  tenant_id = "contoso.onmicrosoft.com"
  scopes    = "extended"
  tz        = "Europe/Warsaw"
  ```

## Scopes

Two named scope sets cover almost everything:

- `default` — the 23 scopes the Node `msgraph` skill has always requested: mail read/send,
  calendars, files, sites, chats, channel messages, meeting transcripts, people, contacts, notes,
  tasks, and group membership. This is what `login` requests unless told otherwise.
- `extended` — `default` plus write access to mail and mailbox settings, presence, directory
  user lookup, shared calendars, chat creation, and team/channel listing. Request it with
  `login --scopes extended`; running it again on an already-consented account adds the new scopes
  with one more consent prompt, no re-login needed.

A handful of scopes are on-demand only, requested with `--scope <name>` on the command that needs
them (`meetings recordings`, `org manager|reports|chain` for another user, `presence get USER`) —
they are never in `default` or `extended`.

Some tenants require an administrator to grant consent once for the app registration. If a
command fails with `error[CONSENT_REQUIRED]`, the error prints the admin-consent URL to send to
your Microsoft 365 administrator:

```
https://login.microsoftonline.com/<tenant>/adminconsent?client_id=<client id>
```

## Differences from `msgraph`

What differs from the Node `msgraph` skill:

- Commands are noun-verb (`mail list`, `calendar create`, `chats send`) instead of Node's
  flag-driven modes (`--emails`, `--calendar --create`, `--send`).
- `mail list` defaults to the Inbox; `msgraph`'s `emails` mode listed the whole mailbox. Pass
  `--folder all` for the old behaviour.
- Exit codes differ: this CLI uses 0 (success), 1 (runtime error), 2 (usage error), 3 (auth or
  permission problem), 4 (not found) — `msgraph` was less consistent, including exiting 0 when
  not logged in.

## Troubleshooting

- **`mgraphctl: 'uv' is not installed`** — install `uv` (see **Prerequisite** above) and try
  again.
- **First run is slow** — the shim is building the virtual environment (10-40 seconds); it prints
  a notice to stderr while doing so, and every later run is fast.
- **`error[CONSENT_REQUIRED]`** — an administrator must grant consent once; the error prints the
  admin-consent URL (see **Scopes** above).
- **`error[NOT_LOGGED_IN]`** — run `login` yourself in your own terminal; data commands never open
  a browser on their own.
- **`error[MISSING_SCOPE]`** — the cached sign-in doesn't cover this command; run
  `login --scopes extended`, or `login --scope <name>` for an on-demand scope.
- **`claims` exits 3 on a stale or missing cache** — it decodes the cached token locally and never
  makes a network call, so it cannot refresh an expired token; run `login` (or `status`, which
  does refresh silently) first.
- **Device-code login is blocked** — some tenants apply Conditional Access policies that require
  a compliant, registered device; the device-code flow cannot satisfy those and interactive
  browser login is the only option.
- **Behind a proxy** — set `HTTPS_PROXY` (and `HTTP_PROXY` if needed); the CLI honours the
  standard proxy environment variables.
- **Times look wrong** — the CLI detects your local IANA time zone automatically; override it with
  `MGRAPHCTL_TZ=Europe/Warsaw` or the global `--tz` option if detection picks the wrong zone.

## Development

```bash
uv sync
uv run pytest
uv run ruff check src tests
uv run ruff format src tests
```

The test suite runs entirely offline against recorded fixtures — no Microsoft 365 account or
network access is needed to run it.

CI (`.github/workflows/ci.yml`) runs the suite on Python 3.11–3.13, ruff, `uv lock --check` and a
credential scan on every push. Releases are annotated `mgraphctl--vX.Y.Z` tags on `main`, cut with
`claude plugin tag`; see `VERSIONING.md`.

## Provenance and licence

`mgraphctl` is original to this repository: an independent Python re-implementation of the
`msgraph` skill's feature set, not a port and not tracking any upstream project. Licensed under
the MIT licence; see `LICENSE`.
