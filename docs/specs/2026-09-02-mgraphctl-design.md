# mgraphctl — design specification

Date: 2026-09-02. Status: approved design, input to the implementation plan.

Inputs (read in full; this document does not restate them):

- `docs/research/2026-09-02-msgraph-node-feature-inventory.md` — the Node.js `msgraph` skill; §5 modes and §11 quirks are the parity baseline.
- `docs/research/2026-09-02-msgraph-api-research.md` — Graph surface, scopes, gotchas, stack choices.
- Repo rules: `CONTRIBUTING.md`, `CLAUDE.md`, `.claude-plugin/marketplace.json`, `plugins/msgraph/*` (house style).

## 1. Goals and non-goals

| Goal | Measure |
|---|---|
| Feature parity with the Node `msgraph` skill | every §5 mode of the inventory maps to a `mgraphctl` command or to a documented recipe (§9); the two recipe cases are `org` summary (composed from `org manager` + `org reports` + `people search`) and `transcripts --insights` resolved by date/subject (`meetings list --resolve` then `meetings insights`) |
| Safe for non-interactive use by Claude | data commands never open a browser; every write supports `--dry-run`; stable exit codes |
| Correct where Node was wrong | all 21 §11 quirks have an explicit decision (§10); default is fix |
| Extended coverage | mail triage, mailbox/OOF, scheduling (`getSchedule`, `findMeetingTimes`), chats (find-or-create DM), presence, unified search, raw `api` |
| Zero-setup on a fresh machine | only `uv` is required; the shim installs Python and packages on first run outside the plugin dir |
| Testable offline | pytest + respx for every verb, driven by JSON response files under `tests/fixtures/<noun>/`; the record/replay transport (§5.8) is a developer tool exercised only by its own round-trip test |

Non-goals: MCP server, delta/sync state, change notifications, consumer (MSA) accounts, keychain-backed token storage, admin/tenant APIs, reuse of Node snapshots or fixtures, Windows shim (raw `uv run` documented instead).

## 2. Naming, layout, packaging

### 2.1 Names

| Thing | Value |
|---|---|
| Plugin | `mgraphctl` at `plugins/mgraphctl/` (`.claude-plugin/plugin.json` name `mgraphctl`, version `0.1.0`, author Sviatoslav Sviridov <sviridov@gmail.com>, keywords `microsoft-365 graph-api outlook teams sharepoint onedrive python uv`) |
| Skill | `mgraphctl` at `plugins/mgraphctl/skills/mgraphctl/SKILL.md` |
| Python distribution / import package / console script | `mgraphctl` / `mgraphctl` / `mgraphctl` |
| Bash shim | `plugins/mgraphctl/mgraphctl` (mode 0755) |
| Marketplace entry | `{"name":"mgraphctl","source":"./plugins/mgraphctl","category":"productivity","description":"Work with Microsoft 365 — Outlook mail and calendar, Teams chats and channels, presence, meetings and transcripts, SharePoint, OneDrive, OneNote, Planner, To Do, people and org chart — through the Microsoft Graph API (Python CLI run with uv)."}` appended after the `msgraph` entry |
| CHANGELOG | `plugins/mgraphctl/CHANGELOG.md` starting with `## [Unreleased]` (house style: bullet list, no sub-headings) |
| Env var prefix | `MGRAPHCTL_` |
| User state dir | `~/.mgraphctl/` (mode 0700) |

### 2.2 Directory layout

```
plugins/mgraphctl/
  .claude-plugin/plugin.json
  CHANGELOG.md
  README.md
  skills/mgraphctl/
    SKILL.md                         # <= 400 lines (§12)
    reference/commands.md            # full per-verb reference generated from §8
    scripts/
      mgraphctl                     # bash shim (§2.4)
      pyproject.toml
      uv.lock                        # committed
      .python-version                # "3.11"
      src/mgraphctl/                # §7.1
      tests/                         # §11
```

Everything the skill needs lives under `scripts/`; the directory is a self-contained uv project that can be copied anywhere. Nothing is ever written inside it at runtime: no venv, no cache, no logs, and the shim exports `PYTHONDONTWRITEBYTECODE=1` so no `__pycache__` appears either.

### 2.3 `pyproject.toml`

| Key | Value | Why |
|---|---|---|
| `project.name` / `version` | `mgraphctl` / `0.1.0` | mirrors `plugin.json`; a test asserts `mgraphctl.__version__ == importlib.metadata.version("mgraphctl") == plugin.json version` |
| `requires-python` | `>=3.11,<3.14` | `zoneinfo`, `datetime.UTC`, `tomllib` |
| `dependencies` | `msal>=1.38,<2`, `httpx>=0.28,<1`, `typer>=0.27,<1`, `markdownify>=1.2,<2`, `tzdata; sys_platform == 'win32'` | `tzdata` is the one addition: `zoneinfo` has no system database on Windows, and `Prefer: outlook.timezone` needs an IANA name |
| `project.scripts` | `mgraphctl = "mgraphctl.cli:main"` | |
| `dependency-groups.dev` | `pytest>=8`, `respx>=0.23`, `ruff>=0.13` | nothing else |
| `build-system` | `requires = ["uv_build>=0.8,<1"]`, `build-backend = "uv_build"` | src layout, module `mgraphctl` |
| `[tool.uv]` | `exclude-newer = "2026-09-01T00:00:00Z"` | reproducible re-locks |
| `[tool.ruff]` | `line-length = 100`, `target-version = "py311"`, `lint.select = ["E","F","I","UP","B","SIM"]` | `ruff check` and `ruff format --check` must pass |
| `[tool.pytest.ini_options]` | `testpaths = ["tests"]`, `addopts = "-q"` | |

### 2.4 Shim (`scripts/mgraphctl`)

```bash
#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v uv >/dev/null 2>&1; then
  echo "mgraphctl: 'uv' is not installed. Install it: curl -LsSf https://astral.sh/uv/install.sh | sh  (macOS: brew install uv)" >&2
  exit 1
fi
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-${CLAUDE_PLUGIN_DATA:-${XDG_CACHE_HOME:-$HOME/.cache}/mgraphctl}/venv}"
export UV_NO_PROGRESS=1
export PYTHONDONTWRITEBYTECODE=1
[ -d "$UV_PROJECT_ENVIRONMENT" ] || echo "mgraphctl: first run, installing Python environment (10-40 s)..." >&2
exec uv run --project "$here" --frozen --no-dev mgraphctl "$@"
```

Rules: the venv lives under `${CLAUDE_PLUGIN_DATA}` (`~/.claude/plugins/data/<id>/`, persistent across plugin updates); when Claude Code does not export `CLAUDE_PLUGIN_DATA` at runtime it lands in `~/.cache/mgraphctl/venv` (or `$XDG_CACHE_HOME/mgraphctl/venv`), which is equally persistent and acceptable; `--frozen` means `uv.lock` is authoritative and never rewritten; `--no-dev` keeps pytest/respx/ruff out of the runtime env; all shim diagnostics go to stderr so stdout stays a single CLI document.

### 2.5 Invocation

| Context | Command |
|---|---|
| Canonical (SKILL.md, all examples) | `${CLAUDE_PLUGIN_ROOT}/mgraphctl <noun> <verb> [args]` |
| Skill frontmatter | `allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/mgraphctl *)` |
| Windows / no bash | `set UV_PROJECT_ENVIRONMENT=%LOCALAPPDATA%\mgraphctl\venv` then `uv run --project <plugin> --frozen --no-dev mgraphctl <noun> <verb>` |
| Developer | `cd plugins/mgraphctl/skills/mgraphctl/scripts && uv sync && uv run mgraphctl ...` — developers do **not** set `UV_PROJECT_ENVIRONMENT`; the dev environment is `scripts/.venv` (gitignored) with the `dev` group installed |

`${CLAUDE_SKILL_DIR}` is not used anywhere (documented only for personal/project skills, not plugin skills).

## 3. Configuration

All configuration is environment-based; there is no config file. `config.py` reads these once at startup.

| Variable | Default | Effect |
|---|---|---|
| `MGRAPHCTL_CLIENT_ID` | `00000000-0000-0000-0000-000000000000` (Node's registration) | public client id |
| `MGRAPHCTL_TENANT_ID` | `common` | authority `https://login.microsoftonline.com/<tenant>` |
| `MGRAPHCTL_SCOPES` | `default` | `default`, `extended`, or a space/comma-separated scope list; `login --scopes` overrides |
| `MGRAPHCTL_TOKEN_CACHE` | `~/.mgraphctl/token_cache.json` | msal cache file (0600) |
| `MGRAPHCTL_TZ` | detected local zone (§6.3) | IANA zone for `Prefer: outlook.timezone`, naive input, and rendering; `--tz` overrides |
| `MGRAPHCTL_DEBUG` | unset | `1` = same as `--debug` |
| `MGRAPHCTL_FIXTURE_DIR` | unset | replay recorded responses, bypass auth (§5.8) |
| `MGRAPHCTL_RECORD` | unset | `1` with `MGRAPHCTL_FIXTURE_DIR` = live calls, record responses |
| `NO_COLOR`, `COLUMNS` | — | honoured by the text renderer |
| `HTTPS_PROXY` / `HTTP_PROXY` | — | honoured by httpx (`trust_env=True`); Node had no proxy support |

Paths: `~/.mgraphctl/token_cache.json`.

## 4. Authentication (`auth.py`)

### 4.1 Scope sets

| Set | Scopes |
|---|---|
| `default` (Node's 23, verbatim) | `User.Read Mail.Read Mail.Send Calendars.Read Calendars.ReadWrite Files.Read Files.ReadWrite Sites.Read.All Sites.ReadWrite.All Chat.Read Chat.ReadWrite ChannelMessage.Read.All ChannelMessage.Send OnlineMeetingTranscript.Read.All OnlineMeetings.Read People.Read Contacts.Read offline_access Notes.Read Notes.ReadWrite OnlineMeetingAiInsight.Read.All Tasks.ReadWrite Group.Read.All` |
| `extended` | `default` + `Mail.ReadWrite MailboxSettings.ReadWrite Presence.Read Presence.ReadWrite User.ReadBasic.All Calendars.Read.Shared Chat.Create Team.ReadBasic.All Channel.ReadBasic.All TeamMember.Read.All` |
| on-demand (never in a set; `--scope X`) | `OnlineMeetingRecording.Read.All` (`meetings recordings`), `User.Read.All` (`org manager|reports|chain` for another user), `Presence.Read.All` (`presence get USER`) |

`offline_access` stays in the list for documentation and `status` output but is stripped before every msal call (msal adds the reserved scopes `openid profile offline_access` itself and warns if they are passed).

`login` resolves the requested list as: `--scopes default|extended` (else `MGRAPHCTL_SCOPES`, else `default`) ∪ every `--scope X`. The resolved list is what is sent to Entra; msal merges consent server-side, so re-running `login --scopes extended` on an already-consented account adds the new scopes with one consent prompt and no re-login. Every other command (`status`, all data commands) resolves the set the same way from `MGRAPHCTL_SCOPES` (else `default`) and uses it for silent acquisition, so a user who exports `MGRAPHCTL_SCOPES=extended` gets one consistent scope list everywhere.

### 4.2 Flows

| Step | Behaviour |
|---|---|
| App | one `msal.PublicClientApplication(client_id, authority, token_cache=cache)` per process (module-level lazy singleton) |
| Silent (every command) | `accounts = app.get_accounts()`; none → NOT_LOGGED_IN. Else `app.acquire_token_silent_with_error(scopes, account=accounts[0])` — the `_with_error` variant because plain `acquire_token_silent` hides the error dict, collapsing every refresh failure into `None` and making the CONSENT_REQUIRED and correlation-id branches of §4.5 unreachable — where `scopes` = the resolved configured set of §4.1 (`MGRAPHCTL_SCOPES`, else `default` — the same list `login` sends); msal returns a cached/refreshed token whose `scp` carries everything consented. `None` or a result with `error` → §4.5 (consent signals → CONSENT_REQUIRED; anything else → NOT_LOGGED_IN with the `login` hint) |
| `login` (interactive, default) | after silent fails or `--force`: `app.acquire_token_interactive(scopes, prompt="select_account" ("login" with `--force`), port=None, timeout=300, auth_uri_callback=<writes the authorization URL to stderr>)` with msal's default success/error HTML templates; msal opens the system browser and listens on `http://localhost:<random>`; the `auth_uri_callback` line lets a user on a headless host paste the URL elsewhere; timeout → `error[LOGIN_TIMEOUT]` exit 3 |
| `login --device-code` | `flow = app.initiate_device_flow(scopes)`; print `flow["message"]` to stderr; `app.acquire_token_by_device_flow(flow)`; use when no browser (SSH) — may be blocked by Conditional Access, documented |
| Post-login | `GET /me?$select=id,displayName,userPrincipalName` → stdout `Logged in as: <displayName> <<upn>>`, `Scopes: <set-name or "custom"> (<n>)`, `Cache: <path>`; `--json` → `{"account","displayName","userId","scopes":[...],"scopeSet","cache"}` |
| Already logged in | `login` without `--force` and silent succeeds → prints `Already logged in as: <upn>` + `Use --force to re-authenticate, --scopes extended to add permissions.` exit 0. If `--scopes/--scope` request scopes not in the current `scp`, proceed to interactive instead |
| Data commands | NEVER call `acquire_token_interactive` or the device flow. No token → stderr `error[NOT_LOGGED_IN]: no cached sign-in` + `hint: run '<shim> login' in your own terminal (opens a browser)`, exit 3 |

### 4.3 Token cache

- `msal.SerializableTokenCache`; loaded from `MGRAPHCTL_TOKEN_CACHE` at startup, written back on exit only if `cache.has_state_changed`, via temp file + `os.replace`, file mode 0600, directory 0700. Plaintext JSON (msal format); no `msal-extensions`, no keychain.
- `logout` deletes our cache file; prints `Logged out. Cache removed: <path>` or `No cached credentials found.`; exit 0 in both cases.

### 4.4 Scope gate (local, before any Graph call)

Every command declares `scopes: list[str]`; an entry `"A|B"` means any-of. `auth.require_scopes(token, declared)` decodes the JWT payload (no signature check), splits `scp`, and expands it with the implication table below. A declared scope is satisfied if it, or any scope that implies it, is present. Missing → `error[MISSING_SCOPE]: this command needs <X>; the current token has <closest or none>` + `hint: run '<shim> login --scopes extended'` (or `--scope X` for on-demand scopes), exit 3, no request sent. Commands whose scope need depends on the path taken (e.g. `mail send` with large attachments, `chats dm` that must create a chat) declare the base scope statically and call `require_scopes` again at the branch, before the extra request.

| Implies | Implied |
|---|---|
| `Mail.ReadWrite` | `Mail.Read`, `Mail.ReadBasic` |
| `Calendars.ReadWrite` | `Calendars.Read`, `Calendars.ReadBasic` |
| `Files.ReadWrite` / `Files.ReadWrite.All` | `Files.Read` / `Files.Read.All` |
| `Sites.ReadWrite.All` | `Sites.Read.All` |
| `Chat.ReadWrite` | `Chat.Read`, `Chat.ReadBasic`, `ChatMessage.Send` |
| `Tasks.ReadWrite`, `Notes.ReadWrite`, `Contacts.ReadWrite`, `Presence.ReadWrite`, `MailboxSettings.ReadWrite`, `TeamMember.ReadWrite.All`, `Group.ReadWrite.All` | the matching `.Read` scope |
| `User.Read.All` | `User.ReadBasic.All` |

Fixture mode (§5.8) substitutes a synthetic token whose `scp` is the union of every scope declared by any command, so the gate never fires in replay.

### 4.5 Consent and auth error handling

| Signal | Output (stderr) | Exit |
|---|---|---|
| msal result `error == "consent_required"`, or `error_description` containing `AADSTS65001`, `AADSTS650052`, or `Need admin approval` | `error[CONSENT_REQUIRED]: <error_description first line>` + `hint: an admin must grant consent once: https://login.microsoftonline.com/<tenant>/adminconsent?client_id=<client id>` (tenant = `tid` of the last cached token, else `MGRAPHCTL_TENANT_ID`) | 3 |
| any other msal failure (silent returns `None`; `error` is `invalid_grant`, `interaction_required`, user cancelled the browser, …) | `error[NOT_LOGGED_IN]: <error_description first line, or "no cached sign-in">` + `correlation-id` when present + `hint: run '<shim> login' in your own terminal` (`login --force` when the failure happened inside `login`) | 3 |
| Graph 401 after one forced silent refresh | `error[UNAUTHORIZED]: ...` + hint `login --force` | 3 |
| Graph 403 | `error[<Graph error.code>]: <message>` + hint naming the declared scope(s) and `login --scopes extended` / admin consent URL | 3 (except `meetings insights`, §8) |

### 4.6 `status` and `claims`

- `status`: silent acquisition (may refresh). Logged in → stdout `Logged in as: <upn>`, `Token expires: <ISO with offset>`, `Scopes: <set-name|custom> (<n>)`, `Cache: <path>`, exit 0. Not → stderr `error[NOT_LOGGED_IN]: …` + hint, exit 3. `--json` → stdout `{"loggedIn":bool,"account","expiresAt","scopeSet","scopes":[...],"cache"}` in both states (`{"loggedIn": false, "account": null, …}` when logged out, still with the `error[NOT_LOGGED_IN]` line on stderr and exit 3), so a caller can parse stdout without checking the exit code first. Fixture mode → `fixture-user@example.com`.
- `claims`: decodes the cached access token for the account (no network). Text: sections IDENTITY (`upn`/`unique_name`, `oid`, `tid`, `iat`, `exp` + `expires in Nm`/`EXPIRED`), DEVICE (`deviceid` present/absent with the Conditional-Access note, `join_type`), AUTH METHODS (`amr`), SCOPES (`scp` sorted, one per line). `--json` → the raw payload dict. No token → exit 3.

## 5. HTTP layer (`http.py`, `odata.py`, `errors.py`, `fixtures.py`)

### 5.1 `GraphClient` interface

```python
class GraphClient:
    def __init__(self, token_provider: Callable[[bool], str], *, tz: str, beta: bool = False,
                 debug: bool = False, transport: httpx.BaseTransport | None = None) -> None: ...
    def request(self, method: str, path: str, *, params: Mapping | None = None, json: Any = None,
                content: bytes | Iterable[bytes] | None = None, headers: Mapping | None = None,
                beta: bool | None = None, outlook_tz: bool = False, text_body: bool = False,
                expect: Literal["json", "bytes", "text", "none", "response"] = "json") -> Any: ...
    def get/post/patch/put/delete(...)           # thin wrappers over request
    def paginate(self, path: str, *, params=None, beta=None, outlook_tz=False, limit: int | None,
                 all_: bool, cap: int, page_size: int | None) -> PageResult: ...
    def batch(self, requests: list[BatchRequest], *, beta=None) -> list[BatchResponse]: ...
    def download(self, path_or_url: str, dest: Path, *, beta=None) -> DownloadResult: ...
    def upload_session(self, create_path: str, create_body: dict, file: Path, *, chunk_size: int,
                       beta=None) -> dict: ...
    def search(self, entity_types: list[str], query: str, *, size: int, limit: int, fields=None,
               enable_top_results=False) -> SearchResult: ...
    def execute(self, planned: PlannedRequest) -> Any: ...   # runs a dry-run-able request (§6.4)
```

`path` is already URL-encoded (built with `odata.p()`), may be absolute (`https://graph.microsoft.com/...`, used for `@odata.nextLink`) or relative (`/me/messages`); relative paths are prefixed with `https://graph.microsoft.com/v1.0` or `/beta` (`beta=True` per call, or the global `--beta`). `token_provider(force_refresh)` comes from `auth`. `PageResult = (items: list[dict], truncated: bool, pages: int)`; `DownloadResult = (path, bytes, content_type)`; `BatchRequest = (id, method, url, headers, body)`; `BatchResponse = (id, status, headers, body, error: GraphError | None)` (`error` is set for any sub-status ≥ 400); `SearchResult = (hits: list[dict], total: int | None, more: bool)` where `hits` are the flattened `hitsContainers[].hits[]` entries (each with `hitId`, `rank`, `summary`, `resource`).

Default headers: `Authorization: Bearer <token>`, `Accept: application/json`, `User-Agent: mgraphctl/<version>`, `client-request-id: <uuid4>` (logged with `--debug`). `outlook_tz=True` adds `Prefer: outlook.timezone="<tz>"`; `text_body=True` adds `Prefer: outlook.body-content-type="text"` (multiple `Prefer` values are comma-joined into one header). Service functions set these explicitly; the client never infers them from the path.

### 5.2 Retry, timeouts, 401

| Concern | Rule |
|---|---|
| Timeout | `httpx.Timeout(connect=10, read=60, write=60, pool=10)`; downloads/uploads use read/write 300 |
| Retry statuses | 429, 503, 504 for any method (Graph guidance); transport errors (`ConnectError`, `ReadTimeout`) for GET only |
| Schedule | max 5 attempts; sleep = `Retry-After` seconds if present (capped at 300, honoured for HTTP-date too) else `min(2**n, 30) + uniform(0, 1)`; each retry logged at debug level |
| 401 | once per request: `token_provider(force_refresh=True)`; if a new token arrives, retry once; else raise `AuthError` (exit 3) |
| 412 (Planner) | not retried here; `graph/planner.py` re-reads the etag once and retries |
| Redirects | `follow_redirects=False` on the API client; only `download()` follows (§5.4) |

### 5.3 Paging

`paginate` sends `$top=page_size` (omitted when `page_size is None`: `/me/joinedTeams`; Planner collections are not paged at all and are sliced client-side), follows `@odata.nextLink` verbatim (never rebuilds `$skip`), stops when `len(items) >= limit` (or `>= cap` with `--all`), slices to that bound, and sets `truncated=True` when a `nextLink` was still pending. Text mode prints `(more results available — rerun with --all)` or `(hit the <cap>-item cap — narrow the query)` to stderr; JSON carries `truncated`.

| Noun / call | `page_size` | default `--limit` | `--all` cap |
|---|---|---|---|
| mail list (search mode) / (filter mode) | 25 / 50 | 10 | 500 |
| calendar list (calendarView) | 50 | 50 | 200 |
| chats list, chat messages, channel messages, channel replies | 50 (Graph max) | 20 | 200 |
| chats search, `search` (message/event) | 25 (Search API max) | 25 | 200 |
| `search` (driveItem/site/list/person/chatMessage) | 25 | 25 | 200 |
| onedrive/sharepoint ls | 200 | 50 | 1000 |
| sharepoint items | 200 | 50 | 500 |
| people search, contacts | 50 | 20 | 250 |
| people users, groups list/members | 100 | 20 | 999 |
| todo tasks, onenote pages (max 100) | 100 | 50 | 500 |
| mail folders, calendars, drives, lists | 100 | all (no `--limit`) | 500 |
| teams list (`/me/joinedTeams`, no OData params) | none | all (no `--limit`) | all |

### 5.4 Batch, upload, download

- `batch`: chunks of 20, ids `"1".."20"`, `POST /$batch`, responses re-ordered by id; sub-request `Content-Type: application/json` set whenever a body is present; a sub-response with status ≥ 400 becomes a `GraphError` inside `BatchResponse.error` (callers decide whether to fail or skip); sub-429s are retried by re-submitting only the failed ids after `Retry-After`. Used by exactly the §8 verbs that say `$batch`: `mail mark ID...` (more than one id), `meetings list --resolve` (one `onlineMeetings` filter per event), `planner plans` (one `/groups/{id}/planner/plans` per unified group), `planner tasks --my` (plan titles). Binary `$value`/`/content` requests never go through `$batch`.
- `upload_session`: `POST create_path` → `uploadUrl`; PUT chunks with `Content-Range: bytes s-e/total`, **no Authorization header**, sequential, honouring `nextExpectedRanges`; 5xx/429 on a chunk → retry that chunk (§5.2); 404 → session lost → `error[UPLOAD_SESSION_LOST]` exit 1. Chunk sizes: OneDrive/SharePoint 10,485,760 (32 × 320 KiB); Outlook attachments 3,932,160 (12 × 320 KiB, < 4 MB).
- `download`: `GET path` with `follow_redirects=False`; on 302/303/307 read `Location` and stream it with a *separate* unauthenticated `httpx.Client(follow_redirects=True, max_redirects=5)`; on 200 stream the body directly. Writes to `<dest>.part` then `os.replace`; parent directories are created; an existing file is overwritten. Returns bytes written and content type.

### 5.5 Encoding (`odata.py`)

| Helper | Contract |
|---|---|
| `p(*segments) -> str` | `"/" + "/".join(quote(s, safe="") for s in segments)`; every user-supplied id, UPN, folder name, and drive-item id goes through it |
| `site_ref(...) -> str` | site references are skeleton-literal with only the variable parts quoted: `sites/{quote(host)}:/sites/{quote(name)}`, `sites/{quote(host)}:/teams/{quote(name)}`, `sites/{quote(host)}:/personal/{quote(name)}`, root site `sites/{quote(host)}`, composite id `sites/{quote(id, safe=",")}` (commas stay literal); a user-supplied `host:/a/b` form is split at the first `:/`, the host quoted, each path segment quoted, and the `:/` skeleton re-inserted literally. The `:/…:` drive-path skeleton in `root:/{drive_path}:/children` is likewise literal |
| `drive_path(path) -> str` | splits on `/`, quotes each segment with `safe=""`, rejoins; used inside `root:/<drive_path>:/children` and `:/content` templates |
| `query(params: Mapping) -> str` | keys verbatim (`$select`, `startDateTime`), values `quote(str(v), safe="")` → `%20` never `+`; `True/False` → `true/false`; `None` dropped; order preserved (fixture keys depend on it) |
| `kql(*terms) -> str` | joins with ` AND ` and wraps in double quotes: `"from:x AND received>=2026-08-01"`; callers pass the result as `$search` |
| `odata_str(s) -> str` | `'` → `''` for `$filter` literals and `search(q='...')` |
| `share_id(url) -> str` | `"u!" + base64url(url).rstrip("=")` |

### 5.6 Errors (`errors.py`)

```
MsgraphError(code, message, hint=None, exit_code=1)
  ├─ UsageError(exit 2)             # semantic argument errors raised inside commands
  ├─ AuthError(exit 3)              # NOT_LOGGED_IN, MISSING_SCOPE, CONSENT_REQUIRED, LOGIN_TIMEOUT, UNAUTHORIZED
  ├─ NotFoundError(exit 4)          # 404 and failed name resolution
  ├─ AmbiguousError(exit 2)         # name resolution with >1 candidate; candidates listed on stderr
  └─ GraphError(status, code, message, request_id, url, body)   # exit 3 for 401/403, 4 for 404, else 1
```

Graph JSON bodies (`error.code`, `error.message`, `error.innerError.request-id`/`date`) are parsed; non-JSON bodies keep `code="HTTP_<status>"` and the first 500 chars. `cli.py` maps exceptions to the stderr format in §6.5.

### 5.7 Debug logging

`--debug` (or `MGRAPHCTL_DEBUG=1`) logs to stderr one line per attempt: `DEBUG <METHOD> <url> -> <status> <ms>ms [attempt n] [request-id]`, plus retry sleeps, token acquisition source (`cache`/`refresh`/`interactive`/`fixture`), and the `Prefer` headers sent. Never logs `Authorization`, refresh tokens, `uploadUrl` query strings, or response bodies (bodies only with `--debug --debug`, truncated to 2 KB, still redacting `access_token`/`refresh_token` keys).

### 5.8 Fixture record/replay (`fixtures.py`)

- `FixtureTransport(dir, record: bool, inner: httpx.HTTPTransport | None)` is an `httpx.BaseTransport` installed on both the API client and the download client when `MGRAPHCTL_FIXTURE_DIR` is set; `MGRAPHCTL_RECORD=1` makes it pass-through-and-record.
- Key = `"<METHOD> <path>?<query>"` for API-client requests (host-agnostic, query as sent). Requests made by the unauthenticated download client (302 targets, `uploadUrl` PUTs) are keyed as `"<METHOD> <path>"` with the query string stripped, on both record and replay, because pre-authenticated URLs carry per-request tokens in the query. File = `<dir>/<sha256(key).hexdigest()[:16]>.json` containing `{"key": "...", "responses": [{"status", "headers", "body" | "body_b64" | "body_text"}]}`; `body` for JSON, `body_text` for `text/*`, `body_b64` for everything else.
- Replay: entries consumed sequentially per key within one process; exhausted → `error[FIXTURE_EXHAUSTED]`, missing → `error[FIXTURE_MISSING]: no fixture for <key> (expected <file>)`, exit 1. Recorded `Authorization` and `Set-Cookie` headers are dropped and any `Location` header has its query string stripped. The token endpoint (`login.microsoftonline.com`) never appears in fixtures: msal performs its own HTTP with `requests`, which bypasses the httpx transport entirely, and the transport additionally refuses (raises) if it ever sees that host.
- Auth bypass: in replay mode `auth.get_access_token()` returns a synthetic unsigned JWT (`{"upn":"fixture-user@example.com","oid":"00000000-0000-0000-0000-000000000001","tid":"00000000-0000-0000-0000-000000000002","scp":"<all declared scopes>","exp":now+3600}`) so `status`, `claims`, and the scope gate all work offline.
- Downloads are covered because the download client shares the transport; 302 targets are keyed by their own path with the query stripped (above).

## 6. CLI conventions (`cli.py`, `render.py`)

### 6.1 Global options (root callback, before the noun)

| Option | Default | Effect |
|---|---|---|
| `--debug` | off | §5.7 |
| `--tz IANA` | `MGRAPHCTL_TZ` → detected local zone | `Prefer: outlook.timezone`, naive datetime input, rendering |
| `--beta` | off | every relative path uses `/beta` |
| `--version` | — | prints `mgraphctl <version>` and exits 0 |
| `--help` | — | typer help at every level. No-args at the root or at a noun prints that level's help and exits 0 (parity), implemented explicitly: every `Typer(...)` is created with `invoke_without_command=True` and its callback checks `ctx.invoked_subcommand is None` → `typer.echo(ctx.get_help())`, `raise typer.Exit(0)`; `no_args_is_help` is not used because Click exits 2 through it |

Per-command options present on every verb: `--json`; on write verbs additionally `--dry-run`. `--limit N` must be ≥ 1 (else usage error, exit 2 — fixes quirk 13); `--all` and `--limit` are mutually exclusive.

### 6.2 Output modes

| Mode | Rule |
|---|---|
| JSON (`--json`) | exactly one pretty-printed (`indent=2`, `ensure_ascii=False`, sorted keys off) document on stdout. Lists: `{"items":[...],"count":N,"truncated":bool}`. Single objects: the Graph object as returned (fields restricted by `$select`, never renamed). Writes: the created/updated Graph object, or `{"status":"sent"}` / `{"status":"deleted","id":...}` / `{"status":"accepted"}` when Graph returns no body; multi-id writes (`mail mark ID...`) use the list envelope. Dry run: `{"dryRun":true,"requests":[{"method","url","headers","body"}]}`. Errors never go to stdout. |
| Text (default) | compact aligned tables via `rich.table.Table(box=None, show_edge=False, pad_edge=False, padding=(0,2))` on a `Console(width=int(COLUMNS or 200), force_terminal=False, no_color=NO_COLOR set, soft_wrap=True)` so nothing wraps at 80 columns when piped. Ids are always printed in full (Outlook ids are ~150 chars; Node truncated them to 36). Free-text columns cap at 60 chars with `…`; `--full` lifts body truncation. Object views are `Label : value` lines. No emoji; markers are ASCII (`*` unread, `A` attachment, `T` Teams meeting, `X` cancelled). |
| stderr | diagnostics only: pagination notes, first-run notice, debug, errors |

Text mode converts HTML bodies (Teams, OneNote, mail with `--html` absent when the server did not honour `Prefer`) to Markdown via `html.to_markdown(html, mode)`: `<at id>` → `@Name`, `<attachment id="…">` → `[attachment: <name>]`, `<img src=".../hostedContents/<id>/$value">` → `[image: hostedContents/<id>]`, `<systemEventMessage/>` → `[system event]`, `<style>`/`<script>` dropped, entities decoded, blank lines collapsed (fixes quirk 7). JSON mode never converts.

### 6.3 Date and time

- Local zone detection (no `tzlocal`): `MGRAPHCTL_TZ` → `TZ` env if it is a valid IANA key → `os.readlink("/etc/localtime")` suffix after `zoneinfo/` → on Windows `time.tzname` mapped through the small Windows→IANA table shipped in `render.py` (the ~140 CLDR primary mappings, generated once, committed) → `UTC` with a one-time stderr warning.
- Input (`--start`, `--end`, `--after`, `--before`, `--due`, `--reminder`, `--expires`, `--propose-start/--propose-end`): `YYYY-MM-DD`, `YYYY-MM-DDTHH:MM[:SS]`, either with optional `Z`/`±HH:MM`; naive values are in `--tz`; date-only is start of day, except range-end options (`--end`, `--before`) which become end of day (`23:59:59`). Keywords: `now`, `today`, `tomorrow`, `yesterday`, `+Nd`/`-Nd`/`+Nh`. Durations only (`--duration`, `--expiration`): `30m`, `2h`, `1d`, or ISO 8601 `PT30M`; a datetime is rejected there (exit 2).
- Graph `dateTimeTimeZone` `{dateTime, timeZone}`: fractional seconds truncated to 6 digits, `timeZone` `UTC` or an IANA key → aware datetime → converted to `--tz`; a Windows zone name (only possible when we did not send `Prefer`) → rendered verbatim as `<dateTime> (<timeZone>)`, never guessed. Plain `Z` strings (`receivedDateTime`, Planner) → aware → `--tz`. This fixes quirk 1.
- Rendering: `YYYY-MM-DDTHH:MM±HH:MM`; all-day events `YYYY-MM-DD (all day)`; `N/A` for null. KQL dates (`received>=`) are day-granular: rendered as `YYYY-MM-DD` in `--tz`.
- Request bodies: `start/end` sent as `{"dateTime": "YYYY-MM-DDTHH:MM:SS", "timeZone": "<tz>"}` in `--tz`; `calendarView` `startDateTime/endDateTime` sent as ISO with offset.

### 6.4 Write commands and `--dry-run`

Every verb that issues a non-GET request accepts `--dry-run`. The service layer produces a `Plan = list[PlannedRequest(method, url, headers, body, note)]` first; with `--dry-run` the plan is rendered and nothing is sent; otherwise `client.execute` runs each step. Multi-step writes (draft → attachments → send; find-or-create DM → send; Planner GET-etag → PATCH) list every step; ids produced by earlier steps appear as `{draftId}`, `{chatId}`, `{etag}` placeholders. File contents are shown as `{"$file": "<path>", "bytes": N, "contentType": "..."}`. Text form:

```
DRY RUN — nothing sent
1. POST https://graph.microsoft.com/v1.0/me/sendMail
   Content-Type: application/json
   { ...pretty JSON body... }
```

Write verbs never prompt for confirmation; confirmation is the skill's responsibility (§12 guardrails). The CLI never reads stdin except `--body-file -`.

### 6.5 Exit codes and error lines

| Exit | Meaning | Sources |
|---|---|---|
| 0 | success | includes `meetings insights` 403 soft path, empty lists |
| 1 | runtime error | GraphError other than 401/403/404, local I/O, fixture errors, upload failures |
| 2 | usage | Click parse errors, `UsageError` (bad datetime, `--limit 0`, missing required combination), `AmbiguousError` (a name matched ≥ 2 resources; candidates listed on stderr) |
| 3 | auth / permission | `NOT_LOGGED_IN`, refresh failed, `MISSING_SCOPE`, `CONSENT_REQUIRED`, `LOGIN_TIMEOUT`, HTTP 401/403 |
| 4 | not found | HTTP 404, name resolution with zero candidates |

stderr format (one error per run):

```
error[<CODE>]: <message>
  request-id: <id>          (when Graph returned one)
  hint: <one actionable sentence>
```

`<CODE>` is the Graph `error.code` (`ErrorItemNotFound`, `InefficientFilter`, `Forbidden`…) or an internal code (`NOT_LOGGED_IN`, `MISSING_SCOPE`, `CONSENT_REQUIRED`, `AMBIGUOUS`, `NOT_FOUND`, `USAGE`, `FIXTURE_MISSING`, `UPLOAD_SESSION_LOST`). Hint table (`errors.HINTS`): 401/NOT_LOGGED_IN → `login`; 403/MISSING_SCOPE → `login --scopes extended` or admin consent URL; 404 → "check the id; ids from `mail move` change"; 429 exhausted → "throttled; wait and retry with a smaller --limit"; `InefficientFilter` → "use --search (KQL) instead of date filters with this ordering"; `ErrorAttachmentSizeShouldNotBeLessThanMinimumSize` → internal, never expected.

### 6.6 Argument resolution (names vs ids)

Positional resource arguments accept an id or a human name; resolution is deterministic and documented per noun. A zero-candidate name → `NotFoundError`, exit 4; ≥ 2 candidates → `AmbiguousError`, exit 2, with the candidates (id and name) listed on stderr. `id:<value>` forces id; `/`-prefix forces path (drives). The generic machinery lives in `resolve.py` (`looks_like_id(value, kind)` and `pick_unique(candidates, key, needle) -> match` raising `AmbiguousError`/`NotFoundError`); each noun's `graph/<noun>.py` owns the `resolve_<thing>(client, value)` function that fetches candidates and calls `pick_unique`.

| Argument | Id detection | Name lookup |
|---|---|---|
| mail `--folder` | `all` → `/me/messages` (whole mailbox, Node's default); well-known name (case-insensitive: inbox, drafts, sentitems, deleteditems, junkemail, archive, outbox, clutter, conversationhistory, msgfolderroot) or `len ≥ 40 and no spaces` | exact `displayName` among `GET /me/mailFolders?$top=200` then one level of `childFolders` |
| `TEAM` | GUID regex | case-insensitive `displayName` in `/me/joinedTeams` |
| `CHANNEL` | starts with `19:` | `displayName` in `/teams/{t}/channels` |
| `CHAT` | starts with `19:` | contains `@` → the 1:1 chat with that UPN (§8 chats dm lookup) |
| `USER`/`UPN` | GUID → `/users/{id}`; contains `@` → `/users/{upn}`; `me` → `/me` | otherwise `people users` search when `User.ReadBasic.All` is held, else exit 2 |
| `SITE` | `https://…` URL → `sites/{quote(host)}:/{sites\|teams\|personal}/{quote(name)}` (root-site URL → `sites/{quote(host)}`); `host:/a/b` → host and each segment quoted, `:/` skeleton literal; contains `,` → composite id, quoted with `safe=","` (§5.5 `site_ref`) | `GET /sites?search=<name>`, unique `displayName` match |
| `--drive` | id (`b!…`) | `name` in `/sites/{id}/drives` |
| `--calendar` | `len ≥ 40 and no spaces` | `name` in `/me/calendars` (case-insensitive) |
| drive `ID|PATH` | `id:` prefix or `^[A-Za-z0-9!]{20,}$` without `.` or `/` | otherwise treated as a path |
| `NOTEBOOK`/`SECTION`/`PAGE` | contains `!` or matches `^\d-` | `displayName`/`title` among the parent listing |
| `PLAN`/`BUCKET` | Planner ids (`^[A-Za-z0-9_-]{28}$`) | `title`/`name` among plans / plan buckets |
| todo `LIST` | `AQMk…`/`AAMk…` prefix or `len ≥ 40` | well-known `defaultList`/`flaggedEmails` or `displayName` in `/me/todo/lists` |
| `GROUP` | GUID | `displayName` in `/me/memberOf` groups |
| `MEETING` | onlineMeeting id positional; `--join-url URL` → `$filter=JoinWebUrl eq '<url>'`; `--event ID` → event's `onlineMeeting.joinUrl` then the same filter | — |

## 7. Architecture

### 7.1 Module map (`src/mgraphctl/`)

| Module | Responsibility |
|---|---|
| `__init__.py` | `__version__ = "0.1.0"` |
| `__main__.py` | `from .cli import main; main()` |
| `cli.py` | root `typer.Typer`, global options, registers noun sub-apps, the `@graph_command(scopes=[...])` decorator (performs the scope gate, constructs the `GraphClient`, injects it into the command), the explicit no-args help callback, single `main()` that maps exceptions → stderr format + exit code, flushes the token cache |
| `config.py` | env parsing, paths, `DEFAULT_SCOPES`, `EXTENDED_SCOPES`, `SCOPE_IMPLIES`, constants (chunk sizes, caps) |
| `auth.py` | msal app singleton, cache load/save, `get_access_token(force_refresh)`, `login_interactive`, `login_device_code`, `require_scopes`, `decode_jwt` |
| `http.py` | `GraphClient` (§5.1–5.4), `PageResult`, `PlannedRequest`, `Plan` |
| `odata.py` | §5.5 helpers |
| `render.py` | `emit(result, json_mode)`, table/object renderers, `fmt_dt`, `fmt_dtz`, `fmt_size`, `fmt_person`, `parse_dt`, `parse_duration`, `local_tz()`, Windows→IANA table |
| `html.py` | `to_markdown(html, mode: "teams"|"onenote"|"mail")`, `text_to_html(text)` (escape + `<p>`/`<br>`), `vtt_to_text(vtt)` |
| `errors.py` | §5.6 hierarchy and `HINTS` |
| `fixtures.py` | `FixtureTransport`, synthetic token (§5.8) |
| `resolve.py` | generic resolution machinery only: `looks_like_id(value, kind)` (the id-shape rules of §6.6) and `pick_unique(candidates, key, needle)`; no Graph calls |
| `graph/<noun>.py` | reusable Graph operations, one module per noun, each also owning its `resolve_<thing>()` functions (built on `resolve.pick_unique`); plus `graph/files.py` (drive-item ops parametrised by drive base path, shared by `onedrive` and `sharepoint`) and `graph/users.py` (`get_me`, `get_user`, `search_users`, `list_unified_groups` — the `ConsistencyLevel: eventual` + `$count=true` memberOf query used by `planner plans` and `groups list`) |
| `commands/<noun>.py` | one `typer.Typer` sub-app per noun; parse → resolve → call `graph/` → `render.emit` |

### 7.2 Layering contract

- `commands/*` contain no HTTP and no JSON shaping beyond choosing columns; every function is ≤ ~40 lines: build params, call one or two `graph/` functions, hand a `Result` to `render.emit`.
- `graph/*` functions are pure with respect to process state: signature `fn(client: GraphClient, *, ...typed params..., tz: str) -> dict | PageResult | Plan`; they never print, never `sys.exit`, never read env, and raise only `errors.*`. Read operations return Graph dicts unchanged. Write operations come in pairs: `plan_<op>(...) -> Plan` (no network, may stat local files) and `run_<op>(client, plan | params) -> dict`; commands call `plan_` then either render (dry run) or `run_`.
- Composition examples that this split enables: `chats.dm` = `users.get_user` + `chats.find_one_on_one` + `chats.plan_create` + `chats.plan_send`; `todo.from_mail` = `mail.get_message` + `todo.plan_create`; `mailbox.focused` = `mail.list_messages(classification=...)`; `meetings.*` = `calendar.calendar_view` + `meetings.resolve`.
- The Phase 0 modules (`http`, `render`, `errors`, `resolve`, `graph/users.py`, `graph/files.py`) are the contract that parallel implementation agents code against (§14); their signatures are fixed in Phase 0 and only extended afterwards. Noun modules added in Phase 1 may import each other only through the `graph/` functions listed in §14.

### 7.3 `render` contract

```python
@dataclass class Column: header: str; path: str | Callable[[dict], Any]; width: int | None = None
@dataclass class ListResult: items: list[dict]; columns: list[Column]; truncated: bool = False; empty_text: str = "No results."
@dataclass class ObjectResult: obj: dict; fields: list[tuple[str, str | Callable]]; body: str | None = None
@dataclass class TextResult: text: str; json_obj: Any            # e.g. transcript text, page markdown
@dataclass class WriteResult: obj: dict | None; message: str     # message → stdout in text mode
@dataclass class DryRunResult: plan: Plan
@dataclass class FileResult: path: Path; bytes: int; meta: dict; message: str
def emit(result, *, json_mode: bool) -> None
```

`path` strings are dotted (`from.emailAddress.name`, `start`); `fmt_*` helpers are applied by column callables, never inside `graph/`. `emit` is the only function that writes to stdout.

## 8. Command surface

Legend. **Tier**: P0 = Node parity; P1 = works with the `default` scope set, new; P2 = needs `extended` (or an on-demand) scope. **Parity** = inventory §5 mode. Every verb has `--json`; verbs marked `W` in Notes are writes and have `--dry-run`. Paths are shown unencoded; `{x}` is a resolved id passed through `odata.p()`. `tz` = `Prefer: outlook.timezone`; `text` = `Prefer: outlook.body-content-type="text"`.

### 8.1 Top-level

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `login` | — | `--scopes default\|extended` (env/`default`), `--scope X` (repeat), `--force`, `--device-code` | token endpoint via msal; `GET /me?$select=id,displayName,userPrincipalName` | — | 5.1 login | P0 | §4.2; only command that opens a browser |
| `logout` | — | — | none | — | 5.1 logout | P0 | deletes our cache file only |
| `status` | — | — | silent token only | — | 5.1 status | P0 | exit 0 / 3 (§4.6) |
| `claims` | — | — | none | — | 5.1 claims | P0 | local JWT decode; exit 3 when no token |
| `me` | — | `--photo PATH` | `GET /me?$select=id,displayName,userPrincipalName,mail,jobTitle,department,officeLocation,businessPhones,mobilePhone,preferredLanguage`; `--photo`: `GET /me/photo/$value` (stream) | `User.Read` | 5.2 | P0 | photo 404 → exit 4 |
| `version` | — | — | none | — | — | P1 | `mgraphctl 0.1.0 (python 3.11.x, msal a.b.c, httpx x.y.z)`; JSON object of the same |

### 8.2 `mail`

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `list` | — | `--folder NAME\|ID\|all` (inbox), `--unread`, `--from ADDR` (repeat), `--to ADDR` (repeat), `--search KQL`, `--after DT`, `--before DT`, `--limit 10`, `--all` (cap 500), `--select a,b` | `GET /me/mailFolders/{folder}/messages` (`--folder all` → `GET /me/messages`, the whole mailbox as Node listed it); **search mode** (any of `--search/--from/--to`): `$search=kql(q, from:a, to:b, received>=d, received<=d)`, `$top=25`, no `$orderby`, `--unread` filtered client-side; **filter mode**: `$filter=receivedDateTime ge/le … [and isRead eq false]`, `$orderby=receivedDateTime desc`, `$top=50`; `$select=id,subject,from,toRecipients,ccRecipients,receivedDateTime,isRead,hasAttachments,importance,bodyPreview,conversationId,webLink,inferenceClassification`; tz | `Mail.Read` | 5.3 list | P0 | columns: id, received, flags (`*`/`A`/`!`), from, subject |
| `read` | `ID` | `--html`, `--full` (else 4000 chars + stderr note), `--headers`, `--output FILE`, `--save-attachments DIR` | `GET /me/messages/{id}?$select=…list fields…,body,uniqueBody,replyTo,internetMessageHeaders(if --headers)`; tz; text unless `--html`; `--save-attachments`: list + `GET …/attachments/{aid}/$value` per fileAttachment | `Mail.Read` | 5.3 read | P0 | `--output` writes the full body; non-file attachments skipped with a stderr note |
| `attachments` | `ID` | `--download ATTID --output FILE`, `--all-attachments --output-dir DIR` | `GET /me/messages/{id}/attachments?$select=id,name,contentType,size,isInline` (the `@odata.type` annotation is always returned and distinguishes file/item/reference attachments); download: `GET …/attachments/{aid}/$value` (stream) | `Mail.Read` | 5.3 read --attachments / --attachment-id | P0 | itemAttachment/referenceAttachment → cannot download (exit 1 single, skipped with a stderr note under `--all-attachments`) |
| `send` | — | `--to` (repeat/comma, ≥1), `--cc`, `--bcc`, `--subject` (`(no subject)`), `--body TEXT` \| `--body-file FILE\|-`, `--html`, `--attach FILE` (repeat, ≤150 MB each), `--importance low\|normal\|high`, `--save-to-sent/--no-save-to-sent` (on) | **inline path** when the sum of raw attachment sizes ≤ 2.5 MiB (2,621,440 bytes; base64 inflation keeps the request under Graph's 4 MB cap): `POST /me/sendMail {message:{subject, body:{contentType,content}, toRecipients, ccRecipients, bccRecipients, importance, attachments:[fileAttachment contentBytes]}, saveToSentItems}`; **draft path** otherwise: `POST /me/messages` → per attachment: raw size < 3 MiB (3,145,728) → `POST …/attachments` (fileAttachment), ≥ 3 MiB → `POST …/attachments/createUploadSession` + 3,932,160-byte chunks → `POST /me/messages/{id}/send` | `Mail.Send`; draft path additionally `Mail.ReadWrite` (gated before the first request) | 5.3 send | P0 (draft path P2) | W; JSON `{"status":"sent"}` (+ `"draftId"` on the draft path); MIME type from `mimetypes`; dry run names the path chosen |
| `reply` | `ID` | `--body TEXT`/`--body-file`, `--html`, `--reply-all`, `--to ADDR` (repeat, extra recipients) | `POST /me/messages/{id}/reply\|replyAll` (`--reply-all`) with `{comment}` (text) or `{message:{body:{contentType:"HTML"}}}` (`--html`), plus `message.toRecipients` for `--to` | `Mail.Send` | — | P1 | W; JSON `{"status":"sent"}` |
| `forward` | `ID` | `--to` (≥1), `--body`, `--html` | `POST /me/messages/{id}/forward {toRecipients, comment}` | `Mail.Send` | — | P1 | W |
| `folders` | — | `--depth 2`, `--hidden` | `GET /me/mailFolders?$top=100&$select=id,displayName,parentFolderId,childFolderCount,unreadItemCount,totalItemCount[&includeHiddenFolders=true]` then `…/{id}/childFolders` for `childFolderCount>0` to `--depth` | `Mail.Read` | — | P1 | tree indented by 2 spaces; JSON nested `children` |
| `mark` | `ID...` | `--read`/`--unread`, `--flag`/`--unflag`/`--flag-complete`, `--category X` (repeat), `--clear-categories`, `--importance` | `PATCH /me/messages/{id} {isRead, flag:{flagStatus}, categories, importance}`; >1 id → `$batch` | `Mail.ReadWrite` | — | P2 | W; JSON = list envelope `{"items":[updated messages],"count":N,"truncated":false}` even for one id |
| `move` | `ID` | `--folder NAME\|ID` (required) | `POST /me/messages/{id}/move {destinationId}` | `Mail.ReadWrite` | — | P2 | W; returns the **new** message (id changes) |
| `delete` | `ID` | — | `DELETE /me/messages/{id}` | `Mail.ReadWrite` | — | P2 | W; soft delete; JSON `{"status":"deleted","id"}` |
| `drafts list` | — | `--limit 20`, `--all` | `GET /me/mailFolders/drafts/messages?$select=…list fields…&$orderby=lastModifiedDateTime desc` | `Mail.Read` | — | P1 | |
| `drafts create` | — | same as `send` minus `--save-to-sent` | `POST /me/messages {subject, body, toRecipients,…}` (+ attachment steps as in `send`) | `Mail.ReadWrite` | — | P2 | W; returns the draft |
| `drafts send` | `ID` | — | `POST /me/messages/{id}/send` | `Mail.ReadWrite`, `Mail.Send` | — | P2 | W |
| `rules list` | — | — | `GET /me/mailFolders/inbox/messageRules` | `MailboxSettings.Read` | — | P2 | columns: id, sequence, enabled, name, actions summary |
| `categories` | — | — | `GET /me/outlook/masterCategories` | `MailboxSettings.Read` | — | P2 | |

### 8.3 `mailbox`

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `settings` | — | — | `GET /me/mailboxSettings` | `MailboxSettings.Read` | — | P2 | shows timeZone, language, workingHours, automaticReplies status |
| `oof get` | — | — | `GET /me/mailboxSettings/automaticRepliesSetting` | `MailboxSettings.Read` | — | P2 | |
| `oof set` | — | `--message TEXT` (internal, required unless `--clear`), `--external-message TEXT` (= internal), `--start DT`, `--end DT` (both → `scheduled`, else `alwaysEnabled`), `--external all\|contacts\|none` (all), `--internal-only` (= `none`), `--clear` (→ `disabled`) | `PATCH /me/mailboxSettings {automaticRepliesSetting:{status, externalAudience, scheduledStartDateTime, scheduledEndDateTime, internalReplyMessage, externalReplyMessage}}`; `externalAudience` mapping: `--external all` → `"all"`, `--external contacts` → `"contactsOnly"`, `--external none` / `--internal-only` → `"none"` | `MailboxSettings.ReadWrite` | — | P2 | W; messages sent as HTML via `text_to_html` |
| `focused` | — | `--other`, `--after DT` (`-30d`), `--limit 25`, `--all` | `GET /me/mailFolders/inbox/messages?$filter=receivedDateTime ge {after} and inferenceClassification eq 'focused\|other'&$orderby=receivedDateTime desc` (+ list `$select`, tz) | `Mail.Read` | — | P1 | receivedDateTime leads the filter so `$orderby` is efficient |

### 8.4 `calendar`

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `list` | — | `--start DT`/`--end DT` or `--days N` (7 from now), `--calendar NAME\|ID`, `--search KW` (client-side on subject/organizer/attendees), `--limit 50`, `--all` (cap 200) | `GET /me/calendarView` (or `/me/calendars/{id}/calendarView`) `?startDateTime&endDateTime&$select=id,subject,start,end,location,organizer,attendees,isOnlineMeeting,onlineMeeting,isCancelled,isAllDay,showAs,responseStatus,seriesMasterId,bodyPreview,webLink&$orderby=start/dateTime&$top=50`; tz | `Calendars.Read` | 5.4 list | P0 | recurring series expanded; columns: start, end, `T`/`X` markers, subject, organizer, location, id |
| `calendars` | — | — | `GET /me/calendars?$select=id,name,isDefaultCalendar,canEdit,owner,color` | `Calendars.Read` | — | P1 | |
| `get` | `ID` | `--html` | `GET /me/events/{id}` (full object); tz; text unless `--html` | `Calendars.Read` | — | P1 | shows attendees with response status, joinUrl |
| `create` | — | `--subject` (required), `--start DT` (required), `--end DT` \| `--duration` (30m), `--all-day`, `--attendees ADDR` (repeat), `--optional ADDR` (repeat), `--body`, `--html`, `--location`, `--teams`, `--reminder MIN`, `--show-as free\|tentative\|busy\|oof\|workingElsewhere`, `--category` (repeat), `--calendar`, `--transaction-id` (uuid4 generated) | `POST /me/events` (or `/me/calendars/{id}/events`) `{subject, start, end, isAllDay, attendees:[{emailAddress,type}], body, location:{displayName}, isOnlineMeeting, onlineMeetingProvider:"teamsForBusiness", reminderMinutesBeforeStart, showAs, categories, transactionId}`; tz | `Calendars.ReadWrite` | 5.4 create | P0 | W; returns the event incl. `onlineMeeting.joinUrl`; `--all-day` end defaults to start+1d at midnight |
| `update` | `ID` | any `create` option, all optional | `PATCH /me/events/{id}` with only the given fields; tz | `Calendars.ReadWrite` | — | P1 | W; updating a series master updates the series (documented) |
| `delete` | `ID` | — | `DELETE /me/events/{id}` | `Calendars.ReadWrite` | — | P1 | W; Graph sends cancellations when organizer |
| `respond` | `ID accept\|decline\|tentative` | `--comment`, `--no-send`, `--propose-start DT --propose-end DT` (decline/tentative only) | `POST /me/events/{id}/accept\|decline\|tentativelyAccept {comment, sendResponse, proposedNewTime}` | `Calendars.ReadWrite` | — | P1 | W; JSON `{"status":"accepted"\|"declined"\|"tentativelyAccepted"}` |
| `availability` | — | `--users ADDR` (repeat; default: me), `--start DT` (now, floored to interval), `--end DT` (end of today), `--interval 30` (5–1440) | one `GET /me?$select=mail,userPrincipalName` when default; `POST /me/calendar/getSchedule {schedules, startTime, endTime, availabilityViewInterval}`; tz | `Calendars.Read` | 5.4 availability | P0 | text: per user, list of busy/tentative/oof/workingElsewhere blocks **and** computed free windows from `availabilityView`; fixes quirk 12 |
| `find-times` | — | `--attendees ADDR` (repeat, ≥1), `--duration` (30m), `--start DT` (now), `--end DT` (+7d), `--max 5`, `--domain work\|personal\|unrestricted` (work) | `POST /me/findMeetingTimes {attendees, timeConstraint:{activityDomain, timeSlots}, meetingDuration (ISO), maxCandidates, returnSuggestionReasons:true}`; tz | `Calendars.Read.Shared` | — | P2 | text: suggestions with confidence and per-attendee availability; `emptySuggestionsReason` surfaced |

### 8.5 `people`

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `search` | `Q` | `--limit 20`, `--all` | `GET /me/people?$search="Q"&$top=50&$select=id,displayName,scoredEmailAddresses,jobTitle,department,companyName,personType,userPrincipalName` | `People.Read` | 5.9 people | P0 | `/me/people` in maintenance mode; documented alternative `search Q --type person` |
| `contacts` | — | `--search Q`, `--limit 20`, `--all` | `GET /me/contacts?$top=50&$select=id,displayName,emailAddresses,mobilePhone,businessPhones,jobTitle,companyName[&$search="Q"]`; on 400 for `$search` → fetch ≤ 250 and match client-side | `Contacts.Read` | 5.9 contacts | P0 | |
| `contact` | `ID` | — | `GET /me/contacts/{id}` | `Contacts.Read` | — | P1 | |
| `users` | `Q` | `--limit 20`, `--all` | `GET /users?$search="displayName:Q" OR "mail:Q"&$count=true&$top=100&$select=id,displayName,userPrincipalName,mail,jobTitle,department,officeLocation` + `ConsistencyLevel: eventual` | `User.ReadBasic.All` | — | P2 | directory search; `$search` is tokenised, not substring |
| `user` | `UPN\|ID` | — | `GET /users/{x}?$select=id,displayName,userPrincipalName,mail,jobTitle,department,officeLocation,businessPhones,mobilePhone` | `User.Read` (basic profile of org users; `User.ReadBasic.All` widens fields) | 5.6 lookup-user | P0 | |
| `photo` | `[UPN]` | `--output FILE` (`<upn>.jpg`), `--size 96x96` | `GET /me/photo/$value` or `/users/{upn}/photos/{size}/$value` (stream) | `User.Read` self; `User.ReadBasic.All` others | — | P1 (P2 for others) | 404 → exit 4 |

### 8.6 `org`

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `manager` | `[UPN]` | — | `GET /me/manager` or `/users/{upn}/manager` `?$select=id,displayName,userPrincipalName,mail,jobTitle,department` | `User.Read` self; `User.Read.All` (on-demand) others | 5.10 manager | P0 (P2 others) | 404 → `No manager found`, exit 4 |
| `reports` | `[UPN]` | — | `GET /me/directReports` or `/users/{upn}/directReports` `?$select=…` | same | 5.10 reports | P0 (P2 others) | |
| `chain` | `[UPN]` | `--max 10` | `GET /me?$expand=manager($levels=max;$select=id,displayName,userPrincipalName,jobTitle)&$count=true` with `ConsistencyLevel: eventual`; on 400/403 fall back to iterative `/users/{id}/manager` up to `--max` | `User.Read`; iterative fallback needs `User.Read.All` | 5.10 summary (partial) | P1 | text: one line per level from self upward |

### 8.7 `teams`

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `list` | — | — | `GET /me/joinedTeams` (no OData params) | `Team.ReadBasic.All\|Group.Read.All` | 5.6 teams-list | P0 | |
| `get` | `TEAM` | — | `GET /teams/{t}` | `Team.ReadBasic.All\|Group.Read.All` | — | P1 | |
| `members` | `TEAM` | `--limit 100`, `--all` | `GET /teams/{t}/members` | `TeamMember.Read.All` | — | P2 | |
| `channels` | `TEAM` | — | `GET /teams/{t}/channels?$select=id,displayName,description,membershipType` | `Channel.ReadBasic.All\|Group.Read.All` | 5.7 list | P0 | |
| `channel get` | `TEAM CHANNEL` | — | `GET /teams/{t}/channels/{c}` | `Channel.ReadBasic.All\|Group.Read.All` | — | P1 | |
| `channel messages` | `TEAM CHANNEL` | `--limit 20`, `--all` (cap 200), `--full`, `--with-replies`, `--replies MSGID` | `GET /teams/{t}/channels/{c}/messages?$top=50[&$expand=replies]`; `--replies`: `GET …/messages/{m}/replies?$top=50` (paged, `--limit` honoured — fixes quirk 8); `messageType=unknownFutureValue` and deleted messages dropped | `ChannelMessage.Read.All` | 5.7 messages / replies | P0 | text chronological (oldest first) with Markdown bodies, 300 chars unless `--full`; JSON = Graph order (newest first) |
| `channel send` | `TEAM CHANNEL` | `--body TEXT`/`--body-file`, `--html`, `--subject`, `--reply-to MSGID` | `POST /teams/{t}/channels/{c}/messages` or `…/messages/{m}/replies` `{subject?, body:{contentType:"text"\|"html", content}}` | `ChannelMessage.Send` | 5.7 send | P0 | W; plain text is sent as `contentType:"text"` (no escaping needed — fixes quirk 9); thread replies supported |

### 8.8 `chats`

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `list` | — | `--unread`, `--type oneOnOne\|group\|meeting`, `--limit 20`, `--all` (cap 200) | `GET /me/chats?$top=50&$expand=members,lastMessagePreview&$orderby=lastMessagePreview/createdDateTime desc&$select=id,topic,chatType,lastUpdatedDateTime,viewpoint,webUrl`; unread = `viewpoint.lastMessageReadDateTime < lastMessagePreview.createdDateTime` (client-side, adds `_unread` in text only) | `Chat.Read` | 5.6 chats | P0 | topic for 1:1 = other member's displayName |
| `get` | `CHAT` | — | `GET /chats/{id}?$expand=members` | `Chat.Read` | — | P1 | |
| `members` | `CHAT` | — | `GET /chats/{id}/members` | `Chat.Read` | — | P1 | |
| `messages` | `CHAT` | `--limit 20`, `--all` (cap 200), `--full`, `--after DT` | `GET /chats/{id}/messages?$top=50&$orderby=createdDateTime desc[&$filter=createdDateTime gt {after}]` | `Chat.Read` | 5.6 messages | P0 | text chronological, Markdown bodies, `[image: hostedContents/<id>]` markers; JSON Graph order (documented in SKILL) |
| `send` | `CHAT` | `--body`/`--body-file`, `--html` | `POST /chats/{id}/messages {body:{contentType:"text"\|"html", content}}` | `ChatMessage.Send` (implied by `Chat.ReadWrite`) | 5.6 send | P0 | W |
| `dm` | `USER` | `--body`/`--body-file`, `--html` | `GET /users/{upn}?$select=id,displayName`; page `GET /me/chats?$filter=chatType eq 'oneOnOne'&$expand=members&$top=50` (cap 500) until a chat whose members include that `userId`; none → `POST /chats {chatType:"oneOnOne", members:[me, user] (aadUserConversationMember, roles:["owner"], user@odata.bind)}`; then `POST /chats/{id}/messages` | `Chat.Read`, `ChatMessage.Send`; creation branch `Chat.Create` (gated before the POST) | 5.6 dm | P0 (create P2) | W; fixes quirk 10; dry run shows both possible steps |
| `create` | — | `--members UPN` (repeat, ≥1), `--topic` | `POST /chats {chatType: oneOnOne (1 member, no topic) \| group, topic, members:[me + members]}` | `Chat.Create` | — | P2 | W |
| `search` | `Q` | `--after DT`, `--before DT`, `--limit 25`, `--all` (cap 200) | `POST /search/query {requests:[{entityTypes:["chatMessage"], query:{queryString}, from, size:25}]}` paging on `moreResultsAvailable`; date filter client-side on `createdDateTime` | `Chat.Read` (chats), `ChannelMessage.Read.All` (channel hits) | 5.6 search | P0 | each hit rendered with `chat:<id>` or `channel:<teamId>/<channelId>` (fixes quirk 16); body = `summary` snippet (documented) |
| `hosted-content` | `CHAT MSGID HCID` or `URL` | `--output FILE` (`teams_hosted_<hcid[:8]>.<ext>`) | `GET /chats/{c}/messages/{m}/hostedContents/{h}/$value` (stream); a `graph.microsoft.com` URL containing `/hostedContents/` (chat or channel form) is used verbatim | `Chat.Read` / `ChannelMessage.Read.All` | 5.6 hosted-content | P0 | extension sniffed from magic bytes (png/jpg/gif/webp/pdf/svg/bin) |

### 8.9 `presence`

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `get` | `[USER...]` | — | `GET /me/presence`; users → `POST /communications/getPresencesByUserId {ids}` after resolving UPNs | `Presence.Read` self; `Presence.Read.All` (on-demand) others | — | P2 | |
| `set` | `available\|busy\|dnd\|brb\|away\|offline` | `--expiration` (1h), `--message TEXT` | `POST /users/{my-oid}/presence/setUserPreferredPresence {availability, activity, expirationDuration}` (pairs: Available/Available, Busy/Busy, DoNotDisturb/DoNotDisturb, BeRightBack/BeRightBack, Away/Away, Offline/OffWork); `--message` → `POST …/presence/setStatusMessage` | `Presence.ReadWrite` | — | P2 | W; my oid from the token's `oid` claim (no `/me` call) |
| `clear` | — | — | `POST /users/{my-oid}/presence/clearUserPreferredPresence` | `Presence.ReadWrite` | — | P2 | W |

### 8.10 `meetings`

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `list` | — | `--start DT` (today−7d), `--end DT` (end of today), `--subject KW`, `--resolve`, `--with-transcripts`, `--limit 50` | `GET /me/calendarView?…&$select=id,subject,start,end,organizer,isOnlineMeeting,onlineMeeting&$top=50` (tz), keep `isOnlineMeeting && onlineMeeting.joinUrl`; `--resolve`: `$batch` of `GET /me/onlineMeetings?$filter=JoinWebUrl eq '{url}'`; `--with-transcripts`: `GET /me/onlineMeetings/{id}/transcripts` per resolved meeting | `Calendars.Read`; `--resolve` `OnlineMeetings.Read`; `--with-transcripts` `OnlineMeetingTranscript.Read.All` | 5.14 list / list --subject | P0 | default window is the last 7 days (fixes quirk 2); columns: start, subject, event id, meeting id (when resolved), transcript ids |
| `get` | `[MEETING]` | `--join-url URL` \| `--event ID` | `GET /me/onlineMeetings/{id}` or `GET /me/onlineMeetings?$filter=JoinWebUrl eq '{url}'` | `OnlineMeetings.Read` | — | P1 | exactly one of the three selectors |
| `transcripts` | `[MEETING]` | `--join-url` \| `--event` | `GET /me/onlineMeetings/{id}/transcripts` | `OnlineMeetingTranscript.Read.All` | 5.14 --meeting | P0 | |
| `transcript` | `[MEETING] TRANSCRIPT_ID` | `--join-url` \| `--event`, `--format text\|vtt` (text), `--output FILE` | `GET /me/onlineMeetings/{m}/transcripts/{t}/content?$format=text/vtt` (stream); `text` = local `vtt_to_text` (`[HH:MM:SS] Speaker: line`); 403 `SpeakerAttributionNotAllowed` → retry with `Accept: application/vnd.microsoft.graph.transcript+text` | `OnlineMeetingTranscript.Read.All` | 5.14 --transcript | P0 | JSON `{"meetingId","transcriptId","format","text"}` |
| `insights` | `[MEETING]` | `--join-url` \| `--event` | `GET /copilot/users/{oid}/onlineMeetings/{m}/aiInsights` on v1.0 first; on 404 the same path on `/beta` (Node's behaviour); then `GET …/aiInsights/{id}` per item on whichever base answered (errors → list item kept) | `OnlineMeetingAiInsight.Read.All` | 5.14 --insights | P0 | 403 → stdout `AI insights require a Microsoft 365 Copilot license…`, **exit 0**; 404/empty → soft messages, exit 0; JSON `{"items":[], "note": "..."}` in those cases |
| `recordings` | `[MEETING]` | `--join-url` \| `--event`, `--download RID --output FILE` | `GET /me/onlineMeetings/{id}/recordings`; download `…/recordings/{rid}/content` (stream) | `OnlineMeetingRecording.Read.All` (on-demand) | — | P2 | hint names `login --scope OnlineMeetingRecording.Read.All` |

### 8.11 `onedrive` (all verbs accept `--drive DRIVE_ID` to target another drive; base = `/me/drive` or `/drives/{id}`)

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `ls` | `[PATH]` | `--limit 50`, `--all` (cap 1000) | `GET {base}/root/children` or `{base}/root:/{drive_path}:/children` `?$top=200&$select=id,name,size,lastModifiedDateTime,file,folder,webUrl,parentReference&$orderby=name` | `Files.Read` | 5.8 list | P0 | columns: type (`d`/`f`), id, size, modified, name |
| `search` | `Q` | `--shared`, `--limit 50` | `GET {base}/root/search(q='{q}')` (own) or `GET {base}/search(q='{q}')` (`--shared`, includes remoteItems) | `Files.Read` | — | P1 | |
| `get` | `ID\|PATH` | — | `GET {base}/items/{id}` or `{base}/root:/{drive_path}` | `Files.Read` | 5.8 info | P0 | |
| `download` | `ID\|PATH` | `--output FILE` (item name) | `GET {base}/items/{id}/content` or `{base}/root:/{drive_path}:/content` (302 → stream) | `Files.Read` | 5.8 download | P0 | prints `Downloaded <name> (<size>) to <path>` |
| `upload` | `FILE` | `--dest PATH` (`/<basename>`; trailing `/` = folder), `--conflict rename\|replace\|fail` (replace) | < 4 MiB: `PUT {base}/root:/{drive_path}:/content?@microsoft.graph.conflictBehavior=…`; else `POST {base}/root:/{drive_path}:/createUploadSession {item:{@microsoft.graph.conflictBehavior, name}}` + 10 MiB chunks | `Files.ReadWrite` | 5.8 upload | P0 | W; fixes quirk 15 |
| `mkdir` | `PATH` | — | `POST {base}/root:/{parent}:/children {name, folder:{}, "@microsoft.graph.conflictBehavior":"fail"}` | `Files.ReadWrite` | — | P1 | W |
| `move` | `ID\|PATH` | `--to FOLDER_PATH\|id:ID` (required), `--name` | `PATCH {base}/items/{id} {parentReference:{id}, name?}` (folder resolved via `GET`) | `Files.ReadWrite` | — | P1 | W |
| `rename` | `ID\|PATH NAME` | — | `PATCH {base}/items/{id} {name}` | `Files.ReadWrite` | — | P1 | W |
| `delete` | `ID\|PATH` | — | `DELETE {base}/items/{id}` (recycle bin) | `Files.ReadWrite` | — | P1 | W |
| `share` | `ID\|PATH` | `--type view\|edit` (view), `--scope organization\|anonymous` (organization), `--expires DT` | `POST {base}/items/{id}/createLink {type, scope, expirationDateTime}` | `Files.ReadWrite` | — | P1 | W; prints `link.webUrl`; anonymous may be policy-blocked (403 → exit 3 with hint) |
| `shared-with-me` | — | `--limit 50` | `GET /me/drive/sharedWithMe` | `Files.Read.All\|Sites.Read.All` | — | P1 | stderr note: endpoint degraded and returns nothing after Nov 2026; items carry `remoteItem` (driveId/id shown) |
| `recent` | — | `--limit 20` | `GET /me/drive/recent` | `Files.Read` | — | P1 | |
| `link` | `URL` | `--download`, `--output FILE` | `GET /shares/{share_id(url)}/driveItem`; `--download` → `…/driveItem/content` | `Files.Read` (+ access) | — | P1 | works for OneDrive and SharePoint sharing links |

### 8.12 `sharepoint`

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `sites` | — | `--search Q`, `--limit 20` | `GET /me/followedSites?$select=id,displayName,webUrl`; `--search` or empty followed list → `GET /sites?search={Q or *}&$top={limit}` | `Sites.Read.All` | 5.5 sites | P0 | |
| `site` | `REF` | — | `GET /sites/{ref}?$select=id,displayName,name,webUrl,description` (§6.6 resolution) | `Sites.Read.All` | 5.5 resolve-site | P0 | |
| `drives` | `SITE` | — | `GET /sites/{id}/drives?$select=id,name,webUrl,driveType` | `Sites.Read.All` | — | P1 | |
| `ls` | `SITE [PATH]` | `--drive NAME\|ID`, `--limit 50`, `--all` | as `onedrive ls` with base `/sites/{id}/drive` or `/drives/{d}` | `Sites.Read.All` | 5.5 site --path | P0 | item ids printed (fixes quirk 3) |
| `search` | `Q` | `--site SITE`, `--limit 25`, `--all` (cap 200) | with `--site`: `GET /sites/{id}/drive/root/search(q='{q}')`; without: `POST /search/query` `entityTypes:["driveItem"]`, size 25 | `Sites.Read.All` | — | P1 | |
| `download` | `SITE ITEM\|PATH` | `--drive`, `--output` | `GET /sites/{id}/drive/items/{item}/content` or `/drives/{d}/root:/{drive_path}:/content` | `Sites.Read.All` | 5.5 download / site-file | P0 | uses the **site** drive (fixes quirk 3) |
| `upload` | `SITE FILE` | `--dest PATH`, `--drive`, `--conflict` | as `onedrive upload` with the site drive base | `Sites.ReadWrite.All` | — | P1 | W |
| `url` | `URL` | `--output FILE` (basename), `--info` | 1) `GET /shares/{share_id(url)}/driveItem`; on 4xx 2) Node's algorithm: parse host + `sites\|teams\|personal` segment (skipping `/:x:/r/` prefixes), `GET /sites/{host}:/{kind}/{name}`, `GET /sites/{id}/drives`, pick the drive whose `webUrl` is the deepest prefix of the file path, `GET /drives/{d}/root:/{rel}:/content`, fallback `GET /sites/{id}/drive/root:/{rel}:/content` with and without the first segment (404 only moves on) | `Sites.Read.All` (`/personal/` needs the owner's share → hint) | 5.5 file-url (+ --dry-run → `--info`) | P0 | `--info` prints resolution (`siteId, driveId, path, item`) without downloading; JSON includes `resolution` |
| `lists` | `SITE` | — | `GET /sites/{id}/lists?$select=id,displayName,webUrl,list` | `Sites.Read.All` | — | P1 | system lists hidden |
| `items` | `SITE LIST` | `--fields a,b` (all), `--filter ODATA`, `--limit 50`, `--all` (cap 500) | `GET /sites/{id}/lists/{l}/items?$expand=fields($select=…)&$top=200[&$filter=fields/…]` (+ `Prefer: HonorNonIndexedQueriesWarningMayFailRandomly` when `--filter`) | `Sites.Read.All` | — | P1 | text: one column per field (first 8) |

### 8.13 `onenote`

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `notebooks` | — | `--limit 50` | `GET /me/onenote/notebooks?$top=100&$select=id,displayName,lastModifiedDateTime,links` | `Notes.Read` | 5.11 notebooks | P0 | |
| `sections` | `[NOTEBOOK]` | `--limit 50` | `GET /me/onenote/notebooks/{id}/sections` or `/me/onenote/sections` `?$top=100&$select=id,displayName,lastModifiedDateTime,parentNotebook` | `Notes.Read` | 5.11 sections | P0 | |
| `pages` | `SECTION` | `--limit 50`, `--all` (cap 500) | `GET /me/onenote/sections/{id}/pages?$top=100&$select=id,title,lastModifiedDateTime,links&$orderby=lastModifiedDateTime desc` | `Notes.Read` | 5.11 pages | P0 | |
| `read` | `PAGE` | `--html`, `--output FILE` | `GET /me/onenote/pages/{id}?$select=id,title,lastModifiedDateTime,links` (title and metadata) + `GET /me/onenote/pages/{id}/content?includeIDs=true` (HTML) → Markdown (`to_markdown(mode="onenote")`) | `Notes.Read` | 5.11 read | P0 | JSON `{"id","title","html","markdown"}` pretty (fixes quirk 14 second half) |
| `create` | — | `--section SECTION` (required), `--title` (required), `--body TEXT`/`--body-file`, `--html` | `POST /me/onenote/sections/{id}/pages` `Content-Type: text/html`, `<!DOCTYPE html><html><head><title>{escaped}</title></head><body>{text_to_html(body) or raw html}</body></html>` | `Notes.ReadWrite` | 5.11 create | P0 | W; escapes title/body unless `--html` (fixes quirk 14) |
| `search` | `Q` | `--limit 50` | `GET /me/onenote/pages?$search={Q}&$top=100&$select=id,title,createdDateTime,parentSection` | `Notes.Read` | 5.11 search | P0 | Graph documents `$search` for consumer notebooks only; a 400/501 is passed through with hint `search Q --type driveItem` |

### 8.14 `planner` (no OData params on Planner paths; slicing is client-side)

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `plans` | — | `--limit 50` | `GET /me/planner/plans` ∪ (`graph.users.list_unified_groups`: `GET /me/memberOf/microsoft.graph.group?$filter=groupTypes/any(c:c eq 'Unified')&$count=true&$select=id,displayName&$top=999` with `ConsistencyLevel: eventual` → `$batch` of `GET /groups/{id}/planner/plans`), deduped by id | `Tasks.ReadWrite`, `Group.Read.All` | 5.12 plans | P0 | text shows owning group name from the memberOf map |
| `plan` | `PLAN` | — | `GET /planner/plans/{id}` + `GET /planner/plans/{id}/details` | `Tasks.ReadWrite` | — | P1 | JSON `{...plan, "details": {...}}` |
| `buckets` | `PLAN` | — | `GET /planner/plans/{id}/buckets` | `Tasks.ReadWrite` | 5.12 buckets | P0 | |
| `tasks` | `[PLAN]` | `--my`, `--bucket NAME\|ID`, `--include-completed`, `--limit 50` | `GET /planner/plans/{id}/tasks` or `GET /me/planner/tasks` (`--my`); `--my` adds `$batch` of `GET /planner/plans/{planId}` (≤ 20 distinct) for titles; buckets fetched for names | `Tasks.ReadWrite` | 5.12 tasks / my-tasks | P0 | hides `percentComplete == 100` unless `--include-completed`; columns: id, %, priority, due, bucket, plan (`--my`), title |
| `task` | `ID` | — | `GET /planner/tasks/{id}` + `/details` (errors on details swallowed) | `Tasks.ReadWrite` | 5.12 task-id | P0 | |
| `create` | — | `--plan PLAN` (required), `--title` (required), `--bucket`, `--due DATE`, `--assign UPN` (repeat), `--priority 0-10`, `--description` | `GET /users/{upn}?$select=id` per assignee; `POST /planner/tasks {planId, bucketId, title, dueDateTime, priority, assignments:{oid:{"@odata.type":"#microsoft.graph.plannerAssignment","orderHint":" !"}}}`; `--description` → `GET …/details` (etag) → `PATCH …/details` `If-Match` | `Tasks.ReadWrite` | 5.12 create | P0 | W |
| `update` | `ID` | `--title`, `--due`, `--percent 0\|50\|100`, `--bucket`, `--priority`, `--assign`, `--unassign`, `--description` | `GET /planner/tasks/{id}` (etag) → `PATCH /planner/tasks/{id}` `If-Match`, `Prefer: return=representation`; 412 → re-read once and retry | `Tasks.ReadWrite` | — | P1 | W |
| `complete` | `ID` | — | `update --percent 100` | `Tasks.ReadWrite` | 5.12 complete | P0 | W |
| `delete` | `ID` | — | `GET` (etag) → `DELETE /planner/tasks/{id}` `If-Match` | `Tasks.ReadWrite` | — | P1 | W |

### 8.15 `todo`

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `lists` | — | — | `GET /me/todo/lists?$top=100` | `Tasks.ReadWrite` | 5.13 lists | P0 | shows `wellknownListName` |
| `tasks` | `LIST` | `--include-completed`, `--limit 50`, `--all` (cap 500) | `GET /me/todo/lists/{l}/tasks?$top=100[&$filter=status ne 'completed']`; tz | `Tasks.ReadWrite` | 5.13 tasks | P0 | columns: id, status, importance, due, title |
| `task` | `LIST ID` | — | `GET /me/todo/lists/{l}/tasks/{t}?$expand=checklistItems,linkedResources`; tz | `Tasks.ReadWrite` | — | P1 | |
| `create` | `LIST` | `--title` (required), `--due DT`, `--body TEXT`, `--importance low\|normal\|high`, `--reminder DT`, `--start DT` | `POST /me/todo/lists/{l}/tasks {title, body:{content,contentType:"text"}, importance, dueDateTime:{dateTime,timeZone:tz}, reminderDateTime + isReminderOn, startDateTime}` | `Tasks.ReadWrite` | 5.13 create | P0 | W |
| `update` | `LIST ID` | any `create` option, `--status notStarted\|inProgress\|completed\|waitingOnOthers\|deferred` | `PATCH /me/todo/lists/{l}/tasks/{t}` | `Tasks.ReadWrite` | — | P1 | W |
| `complete` | `LIST ID` | — | `PATCH … {status:"completed"}` | `Tasks.ReadWrite` | 5.13 complete | P0 | W |
| `delete` | `LIST ID` | — | `DELETE /me/todo/lists/{l}/tasks/{t}` | `Tasks.ReadWrite` | — | P1 | W |
| `from-mail` | `LIST MSGID` | `--title` (message subject), `--due DT`, `--importance` | `GET /me/messages/{id}?$select=subject,webLink,bodyPreview,from,receivedDateTime` → `POST …/tasks {title, body:{content: "From: … \n\n" + bodyPreview}, linkedResources:[{webUrl, applicationName:"Microsoft Outlook", displayName: subject, externalId: msgId}]}` | `Tasks.ReadWrite`, `Mail.Read` | — | P1 | W |

### 8.16 `groups`

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `list` | — | `--unified`, `--limit 20`, `--all` (cap 999) | `GET /me/memberOf/microsoft.graph.group?$select=id,displayName,mail,groupTypes,description&$top=100`; `--unified` adds `&$filter=groupTypes/any(c:c eq 'Unified')&$count=true` plus `ConsistencyLevel: eventual` (via `graph.users.list_unified_groups`) | `User.Read` (self); `Group.Read.All` widens | — | P1 | |
| `members` | `GROUP` | `--limit 20`, `--all` (cap 999) | `GET /groups/{id}/members?$select=id,displayName,userPrincipalName,mail,jobTitle&$top=100` | `Group.Read.All` | — | P1 | |

### 8.17 `search` and `api`

| Verb | Args | Options (default) | Graph call | Scopes | Parity | Tier | Notes |
|---|---|---|---|---|---|---|---|
| `search` | `Q` | `--type message\|event\|driveItem\|site\|list\|chatMessage\|person` (message), `--after DT`, `--before DT`, `--limit 25`, `--all` (cap 200), `--fields a,b` | `POST /search/query {requests:[{entityTypes:[type], query:{queryString}, from, size:25, fields?}]}` paging on `moreResultsAvailable`; `message`: `--after/--before` appended to KQL as `received>=`/`received<=`; other types: client-side on `receivedDateTime`/`start.dateTime`/`lastModifiedDateTime`/`createdDateTime` | per type: `Mail.Read`, `Calendars.Read`, `Sites.Read.All` (driveItem/site/list), `Chat.Read`, `People.Read` | — | P1 | columns per type (id, date, title/subject, from/author, webUrl); `chatMessage` hits are shaped by `graph.chats.shape_chat_hit` (the same function `chats search` uses), so chat/channel ids are labelled identically |
| `api` | `METHOD PATH\|URL` | `--query k=v` (repeat), `--body JSON\|@FILE`, `--header k:v` (repeat), `--beta`, `--all`, `--raw`, `--output FILE`, `--dry-run` | the request as given; relative `PATH` prefixed with the base; `--all` follows `@odata.nextLink` and merges `value`; `--raw` streams bytes to stdout/`--output` (for `/$value`, `/content`) | none declared (gate skipped; Graph decides) | — | P1 | escape hatch; JSON output is the response body as-is (`--json` accepted, no-op); non-JSON bodies printed as text unless `--raw` |

## 9. Parity matrix (Node inventory §5 → `mgraphctl`)

| Node command / mode | `mgraphctl` command | Notes |
|---|---|---|
| `login [--force]` | `login [--force] [--scopes …] [--device-code]` | msal interactive instead of hand-rolled PKCE; same client id/tenant |
| `logout` | `logout` | our cache only |
| `status` | `status` | exit 3 when not logged in (Node: 0) |
| `claims [--json]` | `claims [--json]` | exit 3 when no token (Node: 2) |
| `me [--json]` | `me [--json] [--photo]` | explicit `$select` |
| `emails` list (`--limit --folder --search --from --to --after --before --unread --all`) | `mail list` (same flags; `--from/--to` repeatable) | same search/filter split; `--select` added. Default folder differs: `mail list` defaults to Inbox, Node listed the whole mailbox (`/me/messages`) — pass `--folder all` for Node's behaviour |
| `emails --read ID [--full] [--output]` | `mail read ID [--full] [--output] [--html] [--headers]` | server-side text body |
| `emails --read ID --attachments` | `mail attachments ID` | |
| `emails --read ID --attachment-id AID [--output]` | `mail attachments ID --download AID --output FILE`; `mail read ID --save-attachments DIR` | streams `/$value` |
| `emails --send TO --subject --body` | `mail send --to TO --subject --body` | cc/bcc/html/attachments added |
| `calendar` list (`--limit --after --before --search --all`) | `calendar list [--start --end \| --days] [--search] [--limit --all]` | `--after/--before` accepted as aliases of `--start/--end` |
| `calendar --create TITLE --start --end [--timezone] [--location] [--body] [--attendees]` | `calendar create --subject --start --end …` | `--timezone` replaced by global `--tz`; `--teams`, `--optional`, reminders added |
| `calendar --availability [--start --end]` | `calendar availability [--start --end] [--users] [--interval]` | `getSchedule`, honours `showAs` |
| `sharepoint --file-url URL [--output] [--dry-run] [--json]` | `sharepoint url URL [--output] [--info]` | `--info` = Node's `--dry-run` |
| `sharepoint --resolve-site REF` | `sharepoint site REF` | accepts URLs and ids too |
| `sharepoint --sites` | `sharepoint sites [--search]` | |
| `sharepoint --site ID [--path P]` | `sharepoint ls SITE [PATH] [--drive]` | ids printed |
| `sharepoint --download ITEM_ID` | `sharepoint download SITE ITEM` (site drive) or `onedrive download ID` (what Node actually did) | |
| `sharepoint --site-file SITE --path P` | `sharepoint download SITE PATH` | |
| `teams --hosted-content URL\|ID --chat-id --message-id [--output]` | `chats hosted-content CHAT MSGID HCID \| URL [--output]` | channel URLs accepted in URL form |
| `teams --search Q [--after --before --limit]` | `chats search Q [--after --before --limit --all]` | chat vs channel ids distinguished |
| `teams --chats` | `chats list` | unread flag, member names |
| `teams --lookup-user EMAIL` | `people user UPN` | |
| `teams --dm EMAIL --send MSG` | `chats dm USER --body MSG` | pages all chats; creates the chat with `Chat.Create` |
| `teams --messages CHAT [--full] [--limit]` | `chats messages CHAT [--full] [--limit --all --after]` | |
| `teams --send MSG --chat-id ID` | `chats send CHAT --body MSG [--html]` | text by default |
| `teams --teams-list` | `teams list` | |
| `channels --team-id T --list` | `teams channels TEAM` | names resolve |
| `channels --team-id T --channel-id C --messages [--limit]` | `teams channel messages TEAM CHANNEL [--limit --full --with-replies]` | `--full` added |
| `channels … --replies MSG_ID` | `teams channel messages TEAM CHANNEL --replies MSGID [--limit]` | `--limit` honoured |
| `channels … --send MSG` | `teams channel send TEAM CHANNEL --body MSG [--reply-to]` | thread replies added |
| `onedrive [--path P]` | `onedrive ls [PATH]` | |
| `onedrive --upload FILE [--dest]` | `onedrive upload FILE [--dest] [--conflict]` | upload session > 4 MiB |
| `onedrive --download ID [--output]` | `onedrive download ID\|PATH [--output]` | default name = item name |
| `onedrive --info ID` | `onedrive get ID\|PATH` | |
| `people [--search Q]` | `people search Q` | |
| `people --contacts [--search Q]` | `people contacts [--search Q]` | |
| `org --manager` / `--reports` | `org manager` / `org reports` | `--json` works (Node ignored it) |
| `org` (summary) | dropped; compose `org manager`, `org reports`, `people search` | the 3-call composite had no `--json` and duplicated the parts |
| `onenote --notebooks/--sections/--pages/--read/--search/--create` | `onenote notebooks/sections/pages/read/search/create` | `--create TITLE --section S` → `create --title T --section S` |
| `planner --plans/--buckets/--tasks/--my-tasks/--task-id/--create/--complete` | `planner plans/buckets/tasks PLAN/tasks --my/task ID/create/complete` | `--assign` takes UPNs (Node: oids) |
| `todo --lists/--tasks/--create/--complete` | `todo lists/tasks LIST/create LIST/complete LIST ID` | `--list-id` becomes the positional `LIST` |
| `transcripts [--start --end --subject] [--list]` | `meetings list [--start --end --subject]` | window defaults to the last 7 days |
| `transcripts --subject KW` (with transcript ids) | `meetings list --subject KW --resolve --with-transcripts` | |
| `transcripts --meeting MID` | `meetings transcripts MID` | |
| `transcripts --meeting MID --transcript TID [--vtt] [--output]` | `meetings transcript MID TID [--format vtt] [--output]` | text is speaker-attributed |
| `transcripts --meeting MID --insights` | `meetings insights MID` | v1.0 first, `/beta` on 404, as Node |
| `transcripts --insights [--start --end --subject]` (resolved) | `meetings list --subject … --resolve` then `meetings insights MID` | two steps; SKILL recipe covers it |
| `help` | `--help` at every level | |
| `MSGRAPH_FIXTURE_DIR` / `MSGRAPH_RECORD` | `MGRAPHCTL_FIXTURE_DIR` / `MGRAPHCTL_RECORD` | new key scheme; downloads covered |

## 10. Node quirk decisions (inventory §11)

| # | Quirk | Decision | How |
|---|---|---|---|
| 1 | zone-less datetimes rendered in local time as "UTC" | fix | `Prefer: outlook.timezone` + `dateTimeTimeZone` parsing (§6.3) |
| 2 | transcripts default window = one day a week ago | fix | `meetings list` defaults to today−7d … end of today |
| 3 | `sharepoint --download` used `/me/drive`; site browse hid ids | fix | `sharepoint download` uses the site drive; `ls` prints ids |
| 4 | path segments never URL-encoded | fix | `odata.p()` / `drive_path()` on every segment |
| 5 | no retry / Retry-After / timeouts / proxy | fix | §5.2; httpx `trust_env` proxies |
| 6 | any command may open a browser; `status` exit 0 when logged out | fix | interactive only in `login`; exit 3 |
| 7 | naive `stripHtml` | fix | `markdownify`-based `to_markdown` |
| 8 | ignored/missing flags (`org --json`, `--replies --limit`, `channels --full`, `--download`) | fix | all implemented; typer rejects unknown flags |
| 9 | minimal/inconsistent send paths; unescaped HTML | fix | cc/bcc/attachments; Teams text sent as `contentType:"text"` |
| 10 | `--dm` scans 50 chats, cannot create | fix | pages all 1:1 chats; `POST /chats` with `Chat.Create` |
| 11 | inconsistent output-dir checks and names | fix | one `download()` helper: creates parent dirs, `.part` + rename, `Downloaded <name> (<size>) to <path>` everywhere |
| 12 | `--availability` ignores `showAs`, no `$top`, no `--json` | fix | `getSchedule` |
| 13 | parser limits (`--k=v`, `--limit 0`, bare `--output`) | fix | typer; `--limit` ≥ 1; every option typed |
| 14 | OneNote create injects raw HTML; `--read --json` compact | fix | escape unless `--html`; pretty JSON everywhere |
| 15 | OneDrive upload single PUT, no SharePoint upload | fix | upload sessions; `sharepoint upload` |
| 16 | Teams search: snippet only, channel ids mislabelled, odd `--limit` | fix labels/limit, keep snippet | Search API returns summaries only; documented |
| 17 | messages text reversed vs JSON order | keep | text chronological is right for reading, JSON stays Graph order; documented in SKILL |
| 18 | plaintext cache, unconfigurable client id/tenant | partial | cache stays plaintext 0600 (decision); client id/tenant/cache path via env |
| 19 | fixture replay misses downloads; tests overwrite fixtures; home path in snapshot | fix | §5.8 and §11; fixtures are read-only inputs; no home paths in outputs under test |
| 20 | query encoding must match Node for fixture parity | drop | own fixture corpus; `%20`-style encoding |
| 21 | minor: empty `?`, `{}` on empty bodies, insights 403 exit 0, `me` without `$select`, unread-in-search client-side, `search=*` fallback, `/beta` rewrite, contacts `$search` | fix five, keep four | kept deliberately: insights 403 → soft exit 0; unread-in-search filtered client-side (KQL has no `isRead`); `sharepoint sites` falls back to `GET /sites?search=*` when the followed-sites list is empty; insights v1.0-then-`/beta` probing. Fixed: empty `?` never emitted, empty bodies return `None`, `me` uses `$select`, hosted-content URLs are used verbatim on their own base, contacts `$search` gains a client-side fallback |

## 11. Testing

Run: `uv run --project plugins/mgraphctl/skills/mgraphctl/scripts pytest` (from the repo root; `uv run --project skills/mgraphctl/scripts pytest` from the plugin dir). `uv run --project … ruff check src tests` and `ruff format --check` must be clean. Not wired into `.gitlab-ci.yml` in this release (runners have no `uv`); recorded as an open point.

| Layer | Tool | What is asserted |
|---|---|---|
| `tests/test_http.py` | respx | retry on 429 with `Retry-After` and on 503/504 with backoff (sleep monkeypatched), max 5 attempts; 401 → forced refresh + single retry; `paginate` limit/all/cap/truncated; `batch` chunking (25 requests → 2 calls), id correlation, sub-429 resubmission; `upload_session` chunk boundaries (320 KiB multiples, `Content-Range`, no `Authorization` on `uploadUrl`); `download` follows 302 without bearer, writes `.part` then renames; `Prefer` header assembly |
| `tests/test_odata.py` | plain | `p()` encodes `/`, space, `#`, `'`; `query()` yields `%20` and never `+`; `kql()` quoting; `share_id()` against a known vector |
| `tests/test_auth.py` | monkeypatched `msal.PublicClientApplication` (fake with scripted `get_accounts`/`acquire_token_silent_with_error`/`acquire_token_interactive`) | silent path; NOT_LOGGED_IN without interaction for data commands; `login` reaches interactive only there; scope gate with the implication table; consent error → admin URL; cache file mode 0600 |
| `tests/test_render.py` | plain | `dateTimeTimeZone` parsing for IANA/UTC/Windows names; naive input in `--tz`; keywords/durations; table width when not a TTY; HTML→Markdown for `<at>`, `<attachment>`, hostedContents images, `<style>` |
| `tests/test_fixture_mode.py` | `FixtureTransport` in a tmp dir | record then replay round-trip through `GraphClient` (JSON and binary download); sequential consumption; `FIXTURE_MISSING`/`FIXTURE_EXHAUSTED`; token endpoint rejection; synthetic token satisfies the gate |
| `tests/test_cli_<noun>.py` (one per noun) | `typer.testing.CliRunner` + respx, autouse fixture `fake_auth` (patches `auth.get_access_token` to the synthetic token) | for **every verb**: at least one invocation asserting exit 0, the exact request (method, URL incl. encoded query, headers, JSON body) and the stdout shape in `--json` (envelope keys, item count) and text (header row present, id in full); every write verb: a `--dry-run` case asserting no route was called and the plan JSON; exit-code cases: 404 → 4, 403 → 3, 401-after-refresh → 3, 400 → 1, bad `--limit` → 2 |
| `tests/test_cli_root.py` | CliRunner | `--version`, no-args help exit 0, `--tz` propagation to `Prefer`, `--beta` base switch, error line format on stderr, JSON never on stderr |

Fixtures: CLI tests never use the record/replay transport. They use respx with JSON response files `tests/fixtures/<noun>/<verb>[_<variant>].json` — a list of `{"method","path","query"?,"status","json"|"text"|"b64","headers"?}` entries loaded by `tests/conftest.py::mock_graph(router, name)` which registers respx routes (`path` exact, `query` compared after decoding). The §5.8 record/replay format is exercised only by `tests/test_fixture_mode.py` against a temp directory; no `MGRAPHCTL_FIXTURE_DIR` corpus is committed. All data synthetic: users `@example.com`, tenant `contoso.example` hostnames (`contoso.sharepoint.com` style is acceptable as a Microsoft-owned public pattern), ids like `AAMk-msg-0001`, `19:chat-0001@thread.v2`; no internal hostnames, no real names. `scan_secrets.py` runs over them.

Coverage rule enforced by a test: `tests/test_surface.py` walks the typer app tree and asserts every registered command name appears in at least one `test_cli_*.py` (via a `VERBS_TESTED` registry populated by a `@covers("mail list")` decorator).

## 12. SKILL.md design (≤ 400 lines)

Frontmatter:

```yaml
name: mgraphctl
description: >
  Work with Microsoft 365 through the Microsoft Graph API — Outlook mail and calendar, Teams chats
  and channel messages, presence, online meetings and transcripts (Copilot recap), SharePoint,
  OneDrive, OneNote, Planner, Microsoft To Do, contacts, people search, and the org chart. Use this
  skill whenever the user asks about their emails, inbox, unread messages, meetings, calendar,
  availability, scheduling, Teams messages or chats, channel messages, presence or status,
  SharePoint documents, OneDrive files, OneNote notes, Planner plans or tasks, "my tasks", to-do
  lists, action items, meeting summaries or transcripts, colleagues, manager, direct reports, or
  any personal or organizational Microsoft data. Invoke proactively when the user mentions Outlook,
  Teams, SharePoint, OneDrive, OneNote, Planner, Microsoft To Do, or Microsoft 365. Backed by a
  Python CLI (mgraphctl) run with uv.
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/mgraphctl *)
metadata:
  author: Sviatoslav Sviridov
  version: "0.1.0"
```

Sections, in order, with the rule each must state:

| Section | Content |
|---|---|
| Setup | `uv` is the only prerequisite; first run installs (10–40 s, stderr notice). Every example spells out the full `${CLAUDE_PLUGIN_ROOT}/mgraphctl <noun> <verb>` path — no shell variables or aliases, because `allowed-tools` matches the literal command prefix and environment does not persist between Bash calls |
| Login and status | always run `${CLAUDE_PLUGIN_ROOT}/mgraphctl status` first (exit 3 = not logged in). On `NOT_LOGGED_IN`/`CONSENT_REQUIRED`: tell the user the exact command to run in **their own terminal** (`… mgraphctl login`, or `… login --scopes extended`, or the admin-consent URL), stop, and wait; never run `login` yourself, never retry in a loop; `MISSING_SCOPE` → relay the hint verbatim |
| Command cheat-sheet | one block per noun listing verbs with the 1–2 most common flag combos; links to `reference/commands.md` for the full option tables |
| Recipes | inbox triage (`mail list --unread` → `mail read` → `mail mark --read` / `todo from-mail`); schedule a meeting (`calendar availability --users … --start … --end …` → `calendar create --teams … --dry-run` → confirm → run); find a file (`search Q --type driveItem` or `sharepoint url URL`); DM someone (`chats dm USER --body … --dry-run` → confirm → run); transcript to summary (`meetings list --subject … --resolve --with-transcripts` → `meetings transcript MID TID --output` → summarise; `meetings insights` when Copilot-licensed); to-do from mail; post to a channel (`teams list` → `teams channels TEAM` → `teams channel send`) |
| Guardrails | (1) before **any** write (`send`, `reply`, `forward`, `create`, `update`, `complete`, `delete`, `move`, `mark`, `respond`, `upload`, `mkdir`, `rename`, `share`, `dm`, `from-mail`, `oof set`, `presence set/clear`, `drafts create/send`, non-GET `api`) run the same command with `--dry-run`, show the user the request, and get explicit confirmation before running it without `--dry-run`; (2) never run `login`; (3) prefer `--json` when parsing output, text when showing the user; (4) respect `--limit`/`--all` caps and quote `truncated`; (5) Microsoft 365 only — decline Slack/Google requests; (6) get today's date from the shell (`date`) and the zone from `--tz`/`MGRAPHCTL_TZ` before computing windows; (7) ids from `mail move` change — re-list after moving |
| Output conventions | JSON envelope shapes; text-mode ordering (messages chronological, JSON newest first); datetimes carry offsets; `truncated` note on stderr |
| Exit codes | the §6.5 table verbatim |
| Environment variables | the §3 table (user-facing rows) |
| Scopes and consent | `default` vs `extended`; which verbs need `extended` (the P2 list); admin-consent note (§4.5); on-demand scopes |
| Differences from the `msgraph` (Node) skill | §9 matrix highlights (mode flags → noun verb); `sharepoint --file-url` → `sharepoint url`; `transcripts` → `meetings` |

`reference/commands.md` reproduces §8 (all tables) plus §6.6 resolution rules; SKILL.md links to it rather than repeating.

## 13. Docs and release

| Artifact | Content |
|---|---|
| `plugins/mgraphctl/README.md` | what it is (Python re-implementation of `msgraph` with extensions); install (`claude plugin marketplace add svd/mgraphctl`, `claude plugin install mgraphctl@mgraphctl`); prerequisite `uv` with install one-liners for macOS/Linux/Windows; first run and login (`status`, `login`, browser, `--device-code`); where the venv and token cache live; scopes, `extended`, admin consent URL; differences from `msgraph`; troubleshooting (`uv` missing, first-run slowness, `CONSENT_REQUIRED`, device-code blocked by Conditional Access, proxies, `MGRAPHCTL_TZ`); provenance (original design, no upstream); licence note (MIT, `LICENSE` at the repo root) |
| `plugins/mgraphctl/CHANGELOG.md` | `# Changelog` / `## [Unreleased]` / bullets: initial Python implementation, parity list, extensions |
| `.claude-plugin/marketplace.json` | entry from §2.1 |
| `.gitignore` | add `plugins/mgraphctl/skills/mgraphctl/scripts/.venv/`, `**/tests/fixtures/live/`, `.pytest_cache/`, `.ruff_cache/` |
| Validators | `python3 scripts/validate_marketplace.py`, `python3 scripts/scan_secrets.py`, `claude plugin validate .` all pass; `scan_secrets.py` must stay green over `tests/fixtures/` and `uv.lock` (no internal hostnames, no tokens; `example.com`/`contoso` placeholders only) |
| Release | per `.claude/skills/releasing-a-version/SKILL.md`: bump `plugin.json`, `pyproject.toml`, `__init__.py`, run `uv lock` in `scripts/` (the lock records the project version; `--frozen` would otherwise run a stale lock), date the CHANGELOG block, `claude plugin tag` → `mgraphctl--v0.1.0` |

## 14. Implementation phases

| Phase | Deliverable | Parallelism |
|---|---|---|
| 0 — skeleton (one agent) | `pyproject.toml`, `uv.lock`, `.python-version`, shim; `config`, `errors`, `auth`, `http`, `odata`, `render`, `html`, `fixtures`; `resolve.py` with only the generic machinery (`looks_like_id`, `pick_unique`); `graph/users.py` (`get_me`, `get_user`, `search_users`, `list_unified_groups`) and `graph/files.py` because several groups need them; `cli.py` with `@graph_command`, the no-args help callback, and `login/logout/status/claims/me/version/api`; `tests/conftest.py`, `test_http/odata/auth/render/fixture_mode/cli_root`; `test_surface.py` scaffold | serial; freezes the §5.1, §7.2, §7.3 contracts |
| 1 — nouns (parallel agents, one per group) | per group: `graph/<noun>.py`, `commands/<noun>.py`, `tests/test_cli_<noun>.py`, `tests/fixtures/<noun>/*.json`; register the sub-app in `cli.py` (one line each; merge conflicts limited to that list) | A `mail`+`mailbox`; B `calendar`+`meetings`; C `people`+`org`+`groups`; D `teams`+`chats`+`presence`; E `onedrive`+`sharepoint` (both on `graph/files.py`); F `onenote`; G `planner`+`todo`; H `search`. Each group adds its own `resolve_*` functions to its `graph/<noun>.py`. Cross-group imports allowed only through `graph/`, and only these: `todo.from_mail` → `graph.mail.get_message` (G→A); `mailbox.focused` → `graph.mail.list_messages` (A internal); `meetings` → `graph.calendar.calendar_view` (B internal); `search` → `graph.chats.shape_chat_hit` (H→D); `chats.dm`, `planner.create --assign`, `presence.get` → `graph.users.get_user` (Phase 0); `planner.plans`, `groups.list --unified` → `graph.users.list_unified_groups` (Phase 0); `sharepoint`/`onedrive` → `graph.files` (Phase 0). For the two cross-group edges (G→A, H→D) the importing group stubs the function's Graph calls with respx and the owning group ships the function; signatures are agreed in the Phase 0 plan |
| 2 — extended-scope verbs | all P2 rows of §8 (same groups as above), scope-gate branch tests, consent-hint tests | parallel as in phase 1 |
| 3 — docs | `SKILL.md`, `reference/commands.md`, `README.md`, `CHANGELOG.md`, `LICENSE`, marketplace entry, `.gitignore` | one agent, after phase 2 |
| 4 — verification | full `pytest`, `ruff`, three validators, manual smoke of `status` → `login` → `mail list --json` → `calendar list` → `chats list` on a real account, first-run timing of the shim on a machine without the venv | serial |

Shared contracts every phase-1 agent must not change: `GraphClient` signatures, `PageResult`/`Plan`/`PlannedRequest`/`BatchResponse`/`SearchResult`, `render` result dataclasses, `errors` hierarchy and exit codes, `resolve.looks_like_id`/`resolve.pick_unique`, `graph.users.*` and `graph.files.*` signatures, the `@covers` test registry, fixture file format, and the scope declaration form (`scopes=["A", "B|C"]` passed to `cli.graph_command`, which performs the gate and constructs the client).

## 15. Assumptions and open points

Decided without user input; each is reversible before phase 1 starts.

1. The plugin/skill name is `mgraphctl` throughout; the spelling `msgrpah-py` seen in earlier notes is treated as a typo.
2. `extended` scopes and the on-demand ones (`OnlineMeetingRecording.Read.All`, `User.Read.All`, `Presence.Read.All`) will need admin consent on the existing app registration in tenants under the Microsoft-managed consent policy; the CLI prints the admin-consent URL but cannot grant it. `MailboxSettings.Read` is not in `default`, so `mailbox settings`/`oof get` are P2 even though they only read.
3. Env var prefix `MGRAPHCTL_`; client id and tenant are env-only (no `--client-id/--tenant` flags).
4. Exit codes differ from Node (3 for auth instead of 0/2; 4 for not-found); SKILL.md and README carry the new table.
5. Node snapshots and fixtures are not reused; the query-encoding parity requirement (quirk 20) is dropped.
6. `chats hosted-content` is added beyond the requested verb list for parity with `teams --hosted-content`; `org` summary mode is dropped.
7. `search` uses `--after/--before` (not `--from/--to`) so date options are named identically everywhere and `--from` always means a sender.
8. `tzdata` is added as a Windows-only dependency; the Windows→IANA mapping table is committed data, not a dependency.
9. `Prefer: IdType="ImmutableId"` is not sent; `mail move` therefore returns a new id (documented). Revisit if the skill needs to cache ids across calls.
10. Downloads overwrite existing files and create parent directories; `--output` never prompts.
11. `meetings insights` probes v1.0 first and falls back to `/beta` on 404, exactly as Node does; it is the only implicit beta call outside `--beta`/`api --beta`.
12. `teams list`/`channels` declare `Team.ReadBasic.All|Group.Read.All` and `Channel.ReadBasic.All|Group.Read.All` because Node proves `Group.Read.All` suffices; `teams members` declares `TeamMember.Read.All` only (P2), to be relaxed if `Group.Read.All` is confirmed sufficient.
13. `org manager|reports` without a UPN declare `User.Read` (Node proves it works for `/me`); for other users Graph requires `User.Read.All` (admin).
14. `people contacts --search` keeps Node's `$search` with a client-side fallback; `onenote search` passes Graph's error through for work accounts.
15. The Node tests were never in CI, and this plugin's pytest suite is also not in `.gitlab-ci.yml` yet (runners lack `uv`); adding a `uv`-capable job is a follow-up.
16. Version pins (`msal>=1.38`, `httpx>=0.28,<1`, `typer>=0.27`, `markdownify>=1.2`, `uv_build>=0.8`) follow the research document's PyPI readings of 2026-09-02; `uv lock` with `exclude-newer` fixes the exact set.
17. `chats list` expands `members` (25-member cap) purely to name 1:1 chats; group chats show `topic` or the first three member names.
18. `presence set` default expiration is 1 hour; Microsoft's own defaults (1 day / 7 days) are longer than a CLI user typically wants.
