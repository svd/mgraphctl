# mgraphctl Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `plugins/mgraphctl/`, a Python re-implementation of the Node `msgraph` skill with the extensions, fixes and exit-code contract of `docs/specs/2026-09-02-mgraphctl-design.md` (the spec; authoritative wherever this plan is silent): a `uv`-run typer CLI (`mgraphctl <noun> <verb>`) backed by msal + httpx, every verb covered by an offline pytest/respx test, every write verb dry-runnable, and the skill/reference/README docs needed to list it in the marketplace.

**Architecture:** `scripts/` is a self-contained uv project (src layout, `uv_build`). Layers, top to bottom: `cli.py` (root typer app, global options, `@graph_command(scopes=[...])` which gates scopes, builds a `GraphClient` and emits the returned `render` result) → `commands/<noun>.py` (thin typer sub-apps: parse → resolve → call `graph/` → return a `render` result) → `graph/<noun>.py` (pure Graph operations: `client` + typed params → `dict | PageResult | Plan`; write ops come as `plan_<op>()` / `run_<op>()` pairs) → `http.py` (`GraphClient`: retry, 401 refresh, paging, `$batch`, upload sessions, redirect-following downloads, Search API, `PlannedRequest` execution) with `auth.py` (msal public client, cache, JWT scope gate), `odata.py` (encoding), `errors.py` (exception hierarchy → exit codes), `render.py` (result dataclasses, tables, datetimes), `html.py` (HTML→Markdown, VTT), `fixtures.py` (record/replay transport). Noun modules are discovered by a static registry in `commands/__init__.py`, so Phase 1 groups add files without touching `cli.py`.

**Tech Stack:** Python `>=3.11,<3.14` via `uv` 0.12.x (`uv python find 3.11` → Homebrew 3.11 on the dev machine); `msal>=1.38,<2`, `httpx>=0.28,<1`, `typer>=0.27,<1` (typer 0.27.2 vendors Click and depends on `rich>=13.8.0`, which `render.py` imports directly), `markdownify>=1.2,<2` (1.2.3; `bs4` comes with it), `tzdata` on Windows only; dev: `pytest>=8`, `respx>=0.23` (0.23.1), `ruff>=0.13`; build backend `uv_build>=0.8,<1`.

## Global Constraints

- Plugin root `$ROOT/plugins/mgraphctl/`; skill `$ROOT/plugins/mgraphctl/skills/mgraphctl/`; uv project `$ROOT/plugins/mgraphctl/skills/mgraphctl/scripts/` (referred to as `$SCRIPTS`); package `$SCRIPTS/src/mgraphctl/`; tests `$SCRIPTS/tests/`. `$ROOT` = repository root.
- `requires-python = ">=3.11,<3.14"`; `.python-version` = `3.11`.
- Runtime dependencies, verbatim: `msal>=1.38,<2`, `httpx>=0.28,<1`, `typer>=0.27,<1`, `markdownify>=1.2,<2`, `tzdata; sys_platform == 'win32'`. Dev group, verbatim: `pytest>=8`, `respx>=0.23`, `ruff>=0.13`. Nothing else, ever (`rich` is reached through typer's own dependency).
- Build: `requires = ["uv_build>=0.8,<1"]`, `build-backend = "uv_build"`; `[tool.uv] exclude-newer = "2026-09-01T00:00:00Z"`.
- `[tool.ruff] line-length = 100`, `target-version = "py311"`, `lint.select = ["E","F","I","UP","B","SIM"]`; `ruff check` and `ruff format --check` must pass on `src` and `tests` after every task.
- `[tool.pytest.ini_options] testpaths = ["tests"]`, `addopts = "-q"`, markers `real_auth` and `scopes`.
- Canonical invocation: `${CLAUDE_PLUGIN_ROOT}/mgraphctl <noun> <verb> [args]`; the shim is spec §2.4 verbatim, mode 0755, and runs `uv run --project "$here" --frozen --no-dev mgraphctl "$@"`.
- Developer commands (no `UV_PROJECT_ENVIRONMENT` set; env is `$SCRIPTS/.venv`): `cd $SCRIPTS && uv sync` once, then `uv run pytest tests/test_x.py -q`, `uv run ruff check src tests`, `uv run ruff format src tests`.
- Env vars (`config.py`): `MGRAPHCTL_CLIENT_ID` (default `00000000-0000-0000-0000-000000000000`), `MGRAPHCTL_TENANT_ID` (`common`), `MGRAPHCTL_SCOPES` (`default`), `MGRAPHCTL_TOKEN_CACHE` (`~/.mgraphctl/token_cache.json`), `MGRAPHCTL_TZ` (detected), `MGRAPHCTL_DEBUG` (`1`), `MGRAPHCTL_FIXTURE_DIR`, `MGRAPHCTL_RECORD`; `NO_COLOR`, `COLUMNS`, `HTTPS_PROXY`/`HTTP_PROXY` honoured. Paths: `~/.mgraphctl/` (0700), `~/.mgraphctl/token_cache.json` (0600).
- Exit codes: 0 success (incl. `meetings insights` 403 soft path, empty lists); 1 runtime (GraphError other than 401/403/404, I/O, fixture, upload); 2 usage (Click parse errors, `UsageError`, `AmbiguousError`); 3 auth (`NOT_LOGGED_IN`, `MISSING_SCOPE`, `CONSENT_REQUIRED`, `LOGIN_TIMEOUT`, `UNAUTHORIZED`, HTTP 401/403); 4 not found (HTTP 404, zero-candidate name).
- stderr error block, one per run: `error[<CODE>]: <message>` then optional `  request-id: <id>` (or `  correlation-id: <id>` for msal) then optional `  hint: <one actionable sentence>`. Errors never go to stdout.
- JSON (`--json`): one `json.dumps(obj, indent=2, ensure_ascii=False)` document on stdout. Lists `{"items":[...],"count":N,"truncated":bool}`; single objects = the Graph object unrenamed; writes = the Graph object or `{"status":"sent"}` / `{"status":"deleted","id":...}` / `{"status":"accepted"}`; multi-id writes use the list envelope; dry run `{"dryRun":true,"requests":[{"method","url","headers","body"}]}`.
- Text mode: rich table `Table(box=None, show_edge=False, pad_edge=False, padding=(0,2))` on `Console(width=max(int(COLUMNS or 200), natural width), force_terminal=False, no_color=NO_COLOR set, soft_wrap=True)`; ids always in full; free text capped at 60 chars with `…`; object views `Label : value`; ASCII markers only (`*` unread, `A` attachment, `T` Teams, `X` cancelled); diagnostics on stderr only.
- Datetimes: input `YYYY-MM-DD`, `YYYY-MM-DDTHH:MM[:SS][Z|±HH:MM]`, `now|today|tomorrow|yesterday`, `±Nd|±Nh`; naive = `--tz`; date-only = start of day except `--end`/`--before` = `23:59:59`; durations `30m|2h|1d|PT30M`; rendered `YYYY-MM-DDTHH:MM±HH:MM`, all-day `YYYY-MM-DD (all day)`, null `N/A`.
- Secrets rule (CONTRIBUTING.md): never commit client data, credentials, tokens, or internal hostnames; test data uses `@example.com` users, `contoso.example` / `example.com` hosts, ids like `AAMk-msg-0001`, `19:chat-0001@thread.v2`; `python3 scripts/scan_secrets.py` must stay green over `tests/fixtures/` and `uv.lock`.
- Never write inside `scripts/` at runtime: no venv, no cache, no logs; the shim exports `PYTHONDONTWRITEBYTECODE=1`; the runtime venv lives at `${UV_PROJECT_ENVIRONMENT:-${CLAUDE_PLUGIN_DATA:-${XDG_CACHE_HOME:-$HOME/.cache}/mgraphctl}/venv}`.
- Data commands never call `acquire_token_interactive` or the device flow; only `login` does. Write verbs never prompt; the CLI reads stdin only for `--body-file -`.
- Commit style: `type(mgraphctl): summary` (`feat`, `fix`, `docs`, `test`, `chore`), imperative mood, no attribution trailers (no `Co-Authored-By`, no `Generated-by`). Commit from `$ROOT`; stage only the paths the task owns.
- Parallel tasks never edit the same file; every file has exactly one owning task (File map). Phase 1 tasks never modify `cli.py`, `commands/__init__.py`, `conftest.py`, `helpers.py`, or any Phase 0 module.

## File map

Owner = the task that creates and is allowed to edit the file. Paths are relative to `$ROOT/plugins/mgraphctl/` unless they start with `/` (repo root).

| File | Responsibility | Owner |
|---|---|---|
| `/.gitignore` (modify) | add `plugins/mgraphctl/skills/mgraphctl/scripts/.venv/`, `**/tests/fixtures/live/`, `.pytest_cache/`, `.ruff_cache/` | T1 |
| `.claude-plugin/plugin.json` | plugin manifest (name, version 0.1.0, description, author, keywords) | T1 |
| `skills/mgraphctl/scripts/pyproject.toml` | uv project (§2.3 verbatim) | T1 |
| `skills/mgraphctl/scripts/.python-version` | `3.11` | T1 |
| `skills/mgraphctl/scripts/uv.lock` | committed lock; regenerated only by `uv lock` in T1 and re-checked in T13 | T1 |
| `skills/mgraphctl/scripts/mgraphctl` | bash shim (§2.4 verbatim, 0755) | T1 |
| `skills/mgraphctl/scripts/src/mgraphctl/__init__.py` | `__version__ = "0.1.0"` | T1 |
| `skills/mgraphctl/scripts/src/mgraphctl/__main__.py` | `from .cli import main; main()` | T1 |
| `skills/mgraphctl/scripts/src/mgraphctl/cli.py` | root app, globals, `graph_command`, `make_noun_app`, error→exit mapping, `main()` (T1 writes the minimal stub; T6 owns the final file) | T6 |
| `skills/mgraphctl/scripts/tests/test_version.py` | version consistency test | T1 |
| `skills/mgraphctl/scripts/src/mgraphctl/config.py` | env parsing, paths, scope sets, implication table, constants | T2 |
| `skills/mgraphctl/scripts/src/mgraphctl/errors.py` | exception hierarchy, `HINTS`, `format_error`, Graph body parsing | T2 |
| `skills/mgraphctl/scripts/src/mgraphctl/odata.py` | §5.5 encoding helpers | T2 |
| `skills/mgraphctl/scripts/tests/test_config.py`, `test_errors.py`, `test_odata.py` | unit tests for T2 | T2 |
| `skills/mgraphctl/scripts/src/mgraphctl/http.py` | `GraphClient`, `PageResult`, `PlannedRequest`, `Plan`, batch/upload/download/search dataclasses | T3 |
| `skills/mgraphctl/scripts/src/mgraphctl/fixtures.py` | `FixtureTransport`, key/path helpers, `transport_from_env` | T3 |
| `skills/mgraphctl/scripts/tests/test_http.py`, `test_fixture_mode.py` | respx tests for T3 | T3 |
| `skills/mgraphctl/scripts/src/mgraphctl/auth.py` | msal singleton, cache, silent/interactive/device flows, scope gate, JWT decode, synthetic token | T4 |
| `skills/mgraphctl/scripts/tests/test_auth.py` | fake-msal tests for T4 | T4 |
| `skills/mgraphctl/scripts/src/mgraphctl/render.py` | result dataclasses, `emit`, tables, `fmt_*`, `parse_dt`, `parse_duration`, `local_tz`, `WINDOWS_TO_IANA` | T5 |
| `skills/mgraphctl/scripts/src/mgraphctl/html.py` | `to_markdown`, `text_to_html`, `vtt_to_text` | T5 |
| `skills/mgraphctl/scripts/tests/test_render.py`, `test_html.py` | tests for T5 | T5 |
| `skills/mgraphctl/scripts/src/mgraphctl/resolve.py` | `looks_like_id`, `split_id_prefix`, `pick_unique` | T6 |
| `skills/mgraphctl/scripts/src/mgraphctl/commands/__init__.py` | `NOUNS` registry + `register_all(root)` | T6 |
| `skills/mgraphctl/scripts/src/mgraphctl/commands/top.py` | `login logout status claims me version` | T6 |
| `skills/mgraphctl/scripts/src/mgraphctl/commands/api.py` | `api` escape hatch | T6 |
| `skills/mgraphctl/scripts/src/mgraphctl/graph/__init__.py` | empty package marker | T6 |
| `skills/mgraphctl/scripts/src/mgraphctl/graph/users.py` | `get_me`, `get_user`, `search_users`, `list_unified_groups`, `resolve_user`, `user_path` | T6 |
| `skills/mgraphctl/scripts/tests/helpers.py` | `covers`, `VERBS_TESTED`, `mock_graph`, `graph_error`, fixture loader | T6 |
| `skills/mgraphctl/scripts/tests/conftest.py` | `fake_auth` (autouse), `graph`, `app`, `invoke` fixtures | T6 |
| `skills/mgraphctl/scripts/tests/test_cli_root.py`, `test_cli_top.py`, `test_cli_api.py`, `test_resolve.py`, `test_graph_users.py`, `test_surface.py` | tests for T6 | T6 |
| `skills/mgraphctl/scripts/tests/fixtures/top/*.json`, `fixtures/api/*.json`, `fixtures/users/*.json` | respx response files for T6 | T6 |
| `skills/mgraphctl/scripts/tests/fixtures/replay/*.json` | one-file record/replay corpus for the shim smoke test (`me`) | T6 |
| `skills/mgraphctl/scripts/src/mgraphctl/graph/files.py` | drive-item operations parametrised by drive base (`onedrive` + `sharepoint`) | T7 |
| `skills/mgraphctl/scripts/tests/test_graph_files.py` | respx tests for T7 | T7 |
| `.../graph/mail.py`, `.../graph/mailbox.py`, `.../commands/mail.py`, `.../commands/mailbox.py`, `tests/test_cli_mail.py`, `tests/test_cli_mailbox.py`, `tests/fixtures/mail/*.json`, `tests/fixtures/mailbox/*.json` | group A | T8 |
| `.../graph/calendar.py`, `.../commands/calendar.py`, `tests/test_cli_calendar.py`, `tests/fixtures/calendar/*.json` | group B | T9 |
| `.../graph/people.py`, `.../graph/org.py`, `.../graph/groups.py`, `.../commands/people.py`, `.../commands/org.py`, `.../commands/groups.py`, `tests/test_cli_people.py`, `tests/test_cli_org.py`, `tests/test_cli_groups.py`, `tests/fixtures/{people,org,groups}/*.json` | group C | T10 |
| `.../graph/teams.py`, `.../graph/chats.py`, `.../graph/presence.py`, `.../commands/teams.py`, `.../commands/chats.py`, `.../commands/presence.py`, `tests/test_cli_teams.py`, `tests/test_cli_chats.py`, `tests/test_cli_presence.py`, `tests/fixtures/{teams,chats,presence}/*.json` | group D | T11 |
| `.../graph/meetings.py`, `.../commands/meetings.py`, `tests/test_cli_meetings.py`, `tests/fixtures/meetings/*.json` | group E | T12 |
| `.../graph/onedrive.py`, `.../commands/onedrive.py`, `tests/test_cli_onedrive.py`, `tests/fixtures/onedrive/*.json` | group F | T13 |
| `.../graph/sharepoint.py`, `.../commands/sharepoint.py`, `tests/test_cli_sharepoint.py`, `tests/fixtures/sharepoint/*.json` | group G | T14 |
| `.../graph/onenote.py`, `.../commands/onenote.py`, `tests/test_cli_onenote.py`, `tests/fixtures/onenote/*.json` | group H | T15 |
| `.../graph/planner.py`, `.../graph/todo.py`, `.../commands/planner.py`, `.../commands/todo.py`, `tests/test_cli_planner.py`, `tests/test_cli_todo.py`, `tests/fixtures/{planner,todo}/*.json` | group I | T16 |
| `.../graph/search.py`, `.../commands/search.py`, `tests/test_cli_search.py`, `tests/fixtures/search/*.json` | group J | T17 |
| `skills/mgraphctl/SKILL.md`, `skills/mgraphctl/reference/commands.md` | skill docs (K) | T18 |
| `README.md`, `CHANGELOG.md`, `/.claude-plugin/marketplace.json` (modify) | plugin docs + marketplace entry (L) | T19 |
| `skills/mgraphctl/scripts/tests/test_docs.py` | commands.md coverage test | T20 |

(`...` = `skills/mgraphctl/scripts/src/mgraphctl`.) Task numbering: T1–T7 Phase 0; T8–T17 Phase 1 (groups A–J); T18–T19 Phase 2 (K, L); T20 Phase 3.

## Phase 0 contract (signatures every later task codes against)

These are produced by T2–T7 exactly as written; Phase 1 tasks import them and never redefine them. Where the spec gives a signature (§5.1, §7.3) this is that signature; additions are marked *(added)*.

```python
# config.py (T2)
CLIENT_ID_DEFAULT = "00000000-0000-0000-0000-000000000000"
GRAPH_V1 = "https://graph.microsoft.com/v1.0"; GRAPH_BETA = "https://graph.microsoft.com/beta"
TOKEN_HOST = "login.microsoftonline.com"
DEFAULT_SCOPES: list[str]        # the 23 of §4.1 in spec order
EXTENDED_EXTRA: list[str]        # the 10 extra of §4.1 in spec order
EXTENDED_SCOPES: list[str]       # DEFAULT_SCOPES + EXTENDED_EXTRA
ON_DEMAND_SCOPES = ["OnlineMeetingRecording.Read.All", "User.Read.All", "Presence.Read.All"]
RESERVED_SCOPES = frozenset({"openid", "profile", "offline_access"})
SCOPE_IMPLIES: dict[str, tuple[str, ...]]   # §4.4 table, e.g. "Mail.ReadWrite": ("Mail.Read", "Mail.ReadBasic")
CHUNK_DRIVE = 10_485_760; CHUNK_OUTLOOK = 3_932_160
MAIL_INLINE_TOTAL = 2_621_440; MAIL_SMALL_ATTACHMENT = 3_145_728; DRIVE_SIMPLE_UPLOAD = 4_194_304
RETRY_STATUSES = frozenset({429, 503, 504}); MAX_ATTEMPTS = 5; RETRY_AFTER_CAP = 300
@dataclass(frozen=True)
class Settings:
    client_id: str; tenant_id: str; authority: str; scope_set: str; scopes: list[str]
    token_cache: Path; state_dir: Path
    tz: str | None; debug: int; fixture_dir: Path | None; record: bool
def settings() -> Settings                       # reads os.environ on every call (never cached)
def resolve_scopes(spec: str | None, extra: Iterable[str] = ()) -> tuple[str, list[str]]
    # ("default"|"extended"|"custom", scopes); spec = "default"|"extended"|space/comma list|None
def msal_scopes(scopes: Iterable[str]) -> list[str]   # drops RESERVED_SCOPES, keeps order
def shim_path() -> str    # <scripts>/mgraphctl when it exists next to the package, else "mgraphctl"
def user_agent() -> str   # "mgraphctl/<version>"

# errors.py (T2)
class MsgraphError(Exception):
    def __init__(self, code: str, message: str, *, hint: str | None = None, exit_code: int = 1,
                 request_id: str | None = None, correlation_id: str | None = None) -> None
class UsageError(MsgraphError)      # code "USAGE", exit 2
class AuthError(MsgraphError)       # exit 3; code is one of NOT_LOGGED_IN MISSING_SCOPE CONSENT_REQUIRED LOGIN_TIMEOUT UNAUTHORIZED
class NotFoundError(MsgraphError)   # code "NOT_FOUND", exit 4
class AmbiguousError(MsgraphError)  # code "AMBIGUOUS", exit 2; .candidates: list[tuple[str, str]] (id, name), listed on stderr
class GraphError(MsgraphError):     # exit 3 for 401/403, 4 for 404, else 1
    status: int; url: str; body: Any
class FixtureError(MsgraphError)    # FIXTURE_MISSING / FIXTURE_EXHAUSTED / FIXTURE_FORBIDDEN_HOST, exit 1
HINTS: dict[str, str]
def hint_for(code: str, status: int | None) -> str | None
def graph_error_from_response(status: int, headers: Mapping[str, str], body: bytes, url: str) -> GraphError
def graph_error_from_batch(status: int, headers: Mapping[str, str], body: Any, url: str) -> GraphError
def format_error(exc: MsgraphError) -> str      # the §6.5 block, newline-terminated

# odata.py (T2)
def p(*segments: str) -> str                    # "/" + "/".join(quote(s, safe="") ...)
def site_ref(value: str) -> str                 # "/sites/..." per §5.5/§6.6 (URL, host:/a/b, composite id, plain id)
def drive_path(path: str) -> str                # segments quoted with safe="", joined by "/", no leading "/"
def query(params: Mapping[str, Any]) -> str     # "k=v&k2=v2", values quote(safe=""), bools true/false, None dropped
def with_query(path: str, params: Mapping[str, Any] | None) -> str   # (added) path + "?" + query() when non-empty
def kql(*terms: str) -> str                     # '"a AND b"'
def odata_str(s: str) -> str                    # ' → ''
def share_id(url: str) -> str                   # "u!" + base64url(url).rstrip("=")

# http.py (T3)
@dataclass(frozen=True) class PageResult: items: list[dict]; truncated: bool; pages: int
@dataclass class PlannedRequest:
    method: str; url: str; headers: dict[str, str] = field(default_factory=dict); body: Any = None
    note: str | None = None; file: Path | None = None; chunk_size: int | None = None
    expect: Literal["json", "bytes", "text", "none", "response"] = "json"
Plan = list[PlannedRequest]
@dataclass(frozen=True) class BatchRequest: id: str; method: str; url: str; headers: dict[str, str] | None = None; body: Any = None
@dataclass(frozen=True) class BatchResponse: id: str; status: int; headers: dict[str, str]; body: Any; error: GraphError | None
@dataclass(frozen=True) class DownloadResult: path: Path; bytes: int; content_type: str
@dataclass(frozen=True) class SearchResult: hits: list[dict]; total: int | None; more: bool
def plan_to_json(plan: Plan) -> list[dict]      # dry-run JSON steps
def plan_to_text(plan: Plan) -> str             # "DRY RUN — nothing sent\n1. POST https://...\n   Content-Type: ...\n   {...}"
class GraphClient:
    tz: str; beta: bool; debug: int
    def __init__(self, token_provider: Callable[[bool], str], *, tz: str, beta: bool = False,
                 debug: int = 0, transport: httpx.BaseTransport | None = None) -> None   # debug is an int level (spec: bool) so --debug --debug can add bodies
    def url(self, path: str, *, beta: bool | None = None) -> str            # (added) absolute URL for a path
    def request(self, method: str, path: str, *, params: Mapping | None = None, json: Any = None,
                content: bytes | None = None, headers: Mapping | None = None, beta: bool | None = None,
                outlook_tz: bool = False, text_body: bool = False,
                expect: Literal["json", "bytes", "text", "none", "response"] = "json") -> Any
    def get(self, path, **kw) / post / patch / put / delete                  # thin wrappers
    def paginate(self, path: str, *, params=None, headers: Mapping | None = None, beta=None,
                 outlook_tz=False, limit: int | None, all_: bool, cap: int, page_size: int | None) -> PageResult
    def batch(self, requests: list[BatchRequest], *, beta=None) -> list[BatchResponse]
    def download(self, path_or_url: str, dest: Path, *, beta=None) -> DownloadResult
    def upload_session(self, create_path: str, create_body: dict, file: Path, *, chunk_size: int, beta=None) -> dict
    def search(self, entity_types: list[str], query: str, *, size: int, limit: int, fields: list[str] | None = None,
               enable_top_results: bool = False) -> SearchResult
    def execute(self, planned: PlannedRequest) -> Any
    sleep = staticmethod(time.sleep)            # monkeypatched by tests
    def close(self) -> None; __enter__/__exit__

# fixtures.py (T3)
class FixtureTransport(httpx.BaseTransport):
    def __init__(self, dir: Path, *, record: bool, inner: httpx.BaseTransport | None = None) -> None
def fixture_key(request: httpx.Request) -> str  # "<METHOD> <raw path+query>"; query stripped when no Authorization header
def fixture_path(dir: Path, key: str) -> Path   # dir / (sha256(key)[:16] + ".json")
def transport_from_env(s: config.Settings) -> FixtureTransport | None

# auth.py (T4)
DECLARED_SCOPES: set[str]                       # filled by cli.graph_command at decoration time
def app() -> msal.PublicClientApplication       # lazy singleton; tests patch auth._build_app and reset auth._app
def _build_app(s: config.Settings, cache: msal.SerializableTokenCache) -> msal.PublicClientApplication
def load_cache(path: Path) -> msal.SerializableTokenCache
def save_cache() -> None
def acquire_silent(*, force_refresh: bool = False) -> dict
def get_access_token(force_refresh: bool = False) -> str      # the token_provider handed to GraphClient
def cached_access_token() -> str | None                      # no network (claims)
def login_interactive(scopes: list[str], *, force: bool) -> dict
def login_device_code(scopes: list[str]) -> dict
def logout() -> Path | None
def decode_jwt(token: str) -> dict
def expand_scopes(held: Iterable[str]) -> set[str]
def require_scopes(token: str, declared: list[str]) -> None   # raises AuthError MISSING_SCOPE
def synthetic_token(scopes: Iterable[str], *, upn: str = "fixture-user@example.com", ttl: int = 3600) -> str
def classify_msal_error(result: dict | None, *, during_login: bool) -> AuthError
def admin_consent_url() -> str
def account_upn() -> str | None

# render.py (T5)
@dataclass class Column: header: str; path: str | Callable[[dict], Any]; width: int | None = None
@dataclass class ListResult: items: list[dict]; columns: list[Column]; truncated: bool = False; empty_text: str = "No results."; hit_cap: int | None = None; extra: dict | None = None
@dataclass class ObjectResult: obj: dict; fields: list[tuple[str, str | Callable[[dict], Any]]]; body: str | None = None
@dataclass class TextResult: text: str; json_obj: Any
@dataclass class WriteResult: obj: dict | None; message: str
@dataclass class DryRunResult: plan: Plan
@dataclass class FileResult: path: Path; bytes: int; meta: dict; message: str
Result = ListResult | ObjectResult | TextResult | WriteResult | DryRunResult | FileResult
def emit(result: Result, *, json_mode: bool) -> None          # the only stdout writer
def dig(obj: Any, path: str) -> Any                           # dotted lookup, None-safe
def truncate(text: str | None, n: int = 60) -> str
def fmt_dt(value: str | None, tz: str) -> str                 # "Z"/offset ISO string → "YYYY-MM-DDTHH:MM±HH:MM" | "N/A"
def fmt_dtz(obj: dict | None, tz: str) -> str                 # Graph dateTimeTimeZone → same, or "<dateTime> (<Windows zone>)"
def fmt_event_time(event: dict, key: str, tz: str) -> str     # all-day → "YYYY-MM-DD (all day)"
def fmt_date(value: str | None) -> str; def fmt_size(n: int | None) -> str; def fmt_person(obj: dict | None) -> str
def parse_dt(value: str, tz: str, *, end_of_day: bool = False) -> datetime
def parse_duration(value: str) -> timedelta; def iso_duration(td: timedelta) -> str
def to_graph_dtz(dt: datetime, tz: str) -> dict               # {"dateTime": "YYYY-MM-DDTHH:MM:SS", "timeZone": tz}
def to_iso_offset(dt: datetime) -> str; def kql_date(dt: datetime, tz: str) -> str
def local_tz() -> str; def is_iana(name: str) -> bool
WINDOWS_TO_IANA: dict[str, str]
def note(text: str) -> None                                   # stderr line

# html.py (T5)
def to_markdown(html: str, mode: Literal["teams", "onenote", "mail"]) -> str
def text_to_html(text: str) -> str
def vtt_to_text(vtt: str) -> str

# resolve.py (T6)
GUID_RE: re.Pattern
def looks_like_id(value: str, kind: str) -> bool    # kinds: guid mail_folder team channel chat user site drive drive_item onenote planner todo_list group calendar
def split_id_prefix(value: str) -> tuple[str, bool]  # ("x", True) for "id:x", else (value, False)
def pick_unique(candidates: list[dict], key: str | Callable[[dict], str | None], needle: str, *, what: str) -> dict

# cli.py (T6)
@dataclass class Globals: debug: int; tz: str; beta: bool
JsonFlag = Annotated[bool, typer.Option("--json", help="Print JSON instead of text.")]
DryRunFlag = Annotated[bool, typer.Option("--dry-run", help="Show the request(s); send nothing.")]
LimitOpt = Annotated[int | None, typer.Option("--limit", min=1, help="Maximum items.")]
AllFlag = Annotated[bool, typer.Option("--all", help="Fetch every page up to the cap.")]
def make_noun_app(help: str) -> typer.Typer     # invoke_without_command=True + no-args help callback
def graph_command(*, scopes: list[str]) -> Callable[[F], F]
def gate(scopes: list[str]) -> None             # branch-time scope check (mail send draft path, chats dm create)
def page_bounds(limit: int | None, all_: bool, *, default: int) -> tuple[int, bool]
def open_client(g: Globals, scopes: list[str]) -> GraphClient
def build_app() -> typer.Typer; def main() -> None

# commands/__init__.py (T6)
@dataclass(frozen=True) class Noun: name: str; module: str; help: str; kind: Literal["group", "command"] = "group"
NOUNS: list[Noun]; def register_all(root: typer.Typer) -> None

# graph/users.py (T6)
ME_SELECT, USER_SELECT, USERS_SEARCH_SELECT: str
def user_path(ref: str) -> str
def get_me(client, *, select: str = ME_SELECT) -> dict
def get_user(client, ref: str, *, select: str = USER_SELECT) -> dict
def search_users(client, q: str, *, limit: int, all_: bool) -> PageResult
def list_unified_groups(client) -> list[dict]
def resolve_user(client, value: str, *, can_search: bool) -> dict

# graph/files.py (T7) — base is "/me/drive", "/drives/{id}" or "/sites/{id}/drive" (already encoded)
ITEM_SELECT: str
def item_ref(base: str, ref: str) -> str                  # "{base}/items/{id}" or "{base}/root:/{drive_path}"
def children_path(base: str, path: str | None) -> str    # "{base}/root/children" or "{base}/root:/{p}:/children"
def list_children(client, base, path, *, limit, all_) -> PageResult
def search_items(client, base, q, *, limit, shared: bool = False) -> PageResult
def get_item(client, base, ref) -> dict
def resolve_item_id(client, base, ref) -> str
def download_item(client, base, ref, dest: Path | None) -> tuple[dict, DownloadResult]
def plan_upload(client, base, file: Path, dest: str, conflict: str) -> Plan; def run_upload(client, base, file, dest, conflict) -> dict
def plan_mkdir(client, base, path) -> Plan; def run_mkdir(client, base, path) -> dict
def plan_move(client, base, ref, to: str, name: str | None) -> Plan; def run_move(...) -> dict
def plan_rename(client, base, ref, name) -> Plan; def run_rename(...) -> dict
def plan_delete(client, base, ref) -> Plan; def run_delete(...) -> dict
def plan_share(client, base, ref, *, link_type, scope, expires: datetime | None) -> Plan; def run_share(...) -> dict
def get_shared_item(client, url: str) -> dict; def download_shared_item(client, url, dest) -> tuple[dict, DownloadResult]
def item_columns(tz: str) -> list[Column]                # type d/f, id, size, modified, name

# tests/helpers.py (T6)
VERBS_TESTED: set[str]; def covers(*verbs: str)          # decorator registering coverage
def load_fixture(name: str) -> list[dict]                # tests/fixtures/<noun>/<verb>.json
def mock_graph(router: respx.MockRouter, name: str) -> list[respx.Route]
def graph_error(status: int, code: str, message: str = "boom", request_id: str = "req-0001") -> httpx.Response
# tests/conftest.py (T6): fixtures fake_auth (autouse), graph, app (session), invoke(*args, input=None) -> Result
```

## Shared patterns

Every Phase 1 task copies these five patterns; do not re-derive them.

### (a) Command function — `commands/<noun>.py`

```python
"""Outlook mail commands."""

from typing import Annotated

import typer

from mgraphctl.cli import AllFlag, DryRunFlag, JsonFlag, LimitOpt, gate, graph_command, make_noun_app, page_bounds
from mgraphctl.graph import mail
from mgraphctl.http import GraphClient
from mgraphctl.render import Column, DryRunResult, ListResult, ObjectResult, WriteResult, fmt_dt, fmt_person, truncate

app = make_noun_app("Outlook mail: list, read, send, reply, organise.")
drafts = make_noun_app("Draft messages.")
app.add_typer(drafts, name="drafts")


@app.command("list")
@graph_command(scopes=["Mail.Read"])
def list_(
    client: GraphClient,
    folder: Annotated[str, typer.Option("--folder", help="Folder name, id, or 'all'.")] = "inbox",
    unread: Annotated[bool, typer.Option("--unread")] = False,
    search: Annotated[str | None, typer.Option("--search", help="KQL query.")] = None,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List messages (default: Inbox, newest first)."""
    limit, all_ = page_bounds(limit, all_, default=10)
    folder_id = mail.resolve_folder(client, folder)
    page = mail.list_messages(client, folder_id=folder_id, unread=unread, search=search, senders=[], recipients=[],
                              after=None, before=None, select=None, limit=limit, all_=all_, tz=client.tz)
    tz = client.tz
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        hit_cap=mail.CAP_LIST if all_ else None,
        columns=[
            Column("id", "id"),
            Column("received", lambda m: fmt_dt(m.get("receivedDateTime"), tz)),
            Column("flags", mail.flags),
            Column("from", lambda m: fmt_person(m.get("from"))),
            Column("subject", lambda m: truncate(m.get("subject"))),
        ],
    )


@app.command("reply")
@graph_command(scopes=["Mail.Send"])
def reply(
    client: GraphClient,
    message_id: Annotated[str, typer.Argument(metavar="ID")],
    body: Annotated[str | None, typer.Option("--body")] = None,
    body_file: Annotated[str | None, typer.Option("--body-file", help="File, or - for stdin.")] = None,
    html: Annotated[bool, typer.Option("--html")] = False,
    reply_all: Annotated[bool, typer.Option("--reply-all")] = False,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Reply to a message."""
    text = mail.read_body(body, body_file)                     # UsageError when neither/both given
    plan = mail.plan_reply(client, message_id, body=text, html=html, reply_all=reply_all, extra_to=[])
    if dry_run:
        return DryRunResult(plan)
    mail.run_plan(client, plan)
    return WriteResult(obj={"status": "sent"}, message="Sent.")
```

Rules the decorator enforces: the first parameter is `client: GraphClient` (removed from the CLI signature and injected); a `typer.Context` is prepended (hidden); the function **returns** a `render` result and never prints; `json_: JsonFlag = False` must be present (the decorator reads `kwargs["json_"]` to choose the mode); write verbs add `dry_run: DryRunFlag = False`; list verbs use `LimitOpt`/`AllFlag` + `page_bounds`. A branch that needs an extra scope calls `gate(["Mail.ReadWrite"])` before the extra request (§4.4). Nested verbs (`mail drafts list`, `teams channel send`, `mailbox oof get`) live on a second `make_noun_app` added with `app.add_typer(sub, name="drafts")`.

### (b) Service function — `graph/<noun>.py`

```python
"""Graph operations for Outlook mail. Pure: client + params in, Graph dicts / PageResult / Plan out."""

from __future__ import annotations

from datetime import datetime

from mgraphctl import odata
from mgraphctl.errors import UsageError
from mgraphctl.http import GraphClient, PageResult, Plan, PlannedRequest
from mgraphctl.render import kql_date

LIST_SELECT = ("id,subject,from,toRecipients,ccRecipients,receivedDateTime,isRead,hasAttachments,"
               "importance,bodyPreview,conversationId,webLink,inferenceClassification")
PAGE_SEARCH, PAGE_FILTER, CAP_LIST = 25, 50, 500
JSON = {"Content-Type": "application/json"}


def list_messages(client: GraphClient, *, folder_id: str | None, unread: bool, search: str | None,
                  senders: list[str], recipients: list[str], after: datetime | None, before: datetime | None,
                  select: str | None, limit: int | None, all_: bool, tz: str) -> PageResult:
    path = "/me/messages" if folder_id is None else odata.p("me", "mailFolders", folder_id, "messages")
    params: dict[str, object] = {"$select": select or LIST_SELECT}
    search_mode = bool(search or senders or recipients)
    if search_mode:                                               # §8.2 list, search mode
        terms = [search] if search else []
        terms += [f"from:{a}" for a in senders] + [f"to:{a}" for a in recipients]
        if after: terms.append(f"received>={kql_date(after, tz)}")
        if before: terms.append(f"received<={kql_date(before, tz)}")
        params["$search"] = odata.kql(*terms)
        page = client.paginate(path, params=params, outlook_tz=True, limit=limit, all_=all_, cap=CAP_LIST,
                               page_size=PAGE_SEARCH)
        if unread:                                                # client-side (KQL has no isRead)
            page = PageResult([m for m in page.items if not m.get("isRead")], page.truncated, page.pages)
        return page
    filters = []                                                  # §8.2 list, filter mode
    if after: filters.append(f"receivedDateTime ge {after.isoformat()}")
    if before: filters.append(f"receivedDateTime le {before.isoformat()}")
    if unread: filters.append("isRead eq false")
    if filters: params["$filter"] = " and ".join(filters)
    params["$orderby"] = "receivedDateTime desc"
    return client.paginate(path, params=params, outlook_tz=True, limit=limit, all_=all_, cap=CAP_LIST,
                           page_size=PAGE_FILTER)


def plan_reply(client: GraphClient, message_id: str, *, body: str, html: bool, reply_all: bool,
               extra_to: list[str]) -> Plan:
    verb = "replyAll" if reply_all else "reply"
    payload: dict[str, object] = {"comment": body} if not html else {"message": {"body": {"contentType": "HTML", "content": body}}}
    if extra_to:
        payload.setdefault("message", {})["toRecipients"] = [{"emailAddress": {"address": a}} for a in extra_to]
    return [PlannedRequest("POST", client.url(odata.p("me", "messages", message_id, verb)), dict(JSON), payload,
                           expect="none")]


def run_plan(client: GraphClient, plan: Plan) -> list:
    """Execute a plan whose steps are independent (no ids threaded between them)."""
    return [client.execute(step) for step in plan]


def read_body(body: str | None, body_file: str | None) -> str:
    if (body is None) == (body_file is None):
        raise UsageError("USAGE", "give exactly one of --body or --body-file")
    if body is not None:
        return body
    import sys
    from pathlib import Path
    return sys.stdin.read() if body_file == "-" else Path(body_file).read_text()
```

Rules: no printing, no `sys.exit`, no env reads, only `errors.*` raised; read operations return Graph dicts unchanged; writes are `plan_<op>(client, ...) -> Plan` (no network; `client` is only used for `client.url()` and file stats) plus `run_<op>(client, ...) -> dict` when steps thread ids (multi-step writes build each `PlannedRequest` with the real id as it becomes known, and the `plan_` twin shows `{draftId}`/`{chatId}`/`{etag}` placeholders); single-step writes reuse `run_plan`. `resolve_<thing>(client, value) -> dict | str` functions live in the noun's own `graph/` module and call `resolve.looks_like_id` + `resolve.pick_unique`.

### (c) CliRunner test with respx — `tests/test_cli_<noun>.py`

Fixture file `tests/fixtures/mail/list.json` (a JSON list; `path` is the full URL path including `/v1.0`; `query` is optional and compared decoded and exactly; body is `json`, `text` or `b64`; `headers` optional):

```json
[
  {
    "method": "GET",
    "path": "/v1.0/me/mailFolders/inbox/messages",
    "query": {
      "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,isRead,hasAttachments,importance,bodyPreview,conversationId,webLink,inferenceClassification",
      "$orderby": "receivedDateTime desc",
      "$top": "50"
    },
    "status": 200,
    "json": {
      "value": [
        {"id": "AAMk-msg-0001", "subject": "Sprint review", "isRead": false, "hasAttachments": true,
         "importance": "high", "receivedDateTime": "2026-08-31T08:15:00Z",
         "from": {"emailAddress": {"name": "Ada Example", "address": "ada@example.com"}}},
        {"id": "AAMk-msg-0002", "subject": "Lunch", "isRead": true, "hasAttachments": false,
         "importance": "normal", "receivedDateTime": "2026-08-30T11:00:00Z",
         "from": {"emailAddress": {"name": "Bob Example", "address": "bob@example.com"}}}
      ]
    }
  }
]
```

Test module:

```python
"""CLI tests for the mail noun."""

import json

import httpx
import pytest

from helpers import covers, graph_error, mock_graph


@covers("mail list")
def test_mail_list_json(invoke, graph):
    routes = mock_graph(graph, "mail/list")
    result = invoke("mail", "list", "--json")
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert set(doc) == {"items", "count", "truncated"}
    assert doc["count"] == 2 and doc["items"][0]["id"] == "AAMk-msg-0001" and doc["truncated"] is False
    req = routes[0].calls.last.request
    assert req.headers["Prefer"] == 'outlook.timezone="Europe/Warsaw"'
    assert req.headers["Authorization"].startswith("Bearer ")
    assert result.stderr == ""


@covers("mail list")
def test_mail_list_text(invoke, graph):
    mock_graph(graph, "mail/list")
    result = invoke("mail", "list")
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["id", "received", "flags", "from", "subject"]
    assert "AAMk-msg-0001" in lines[1] and "2026-08-31T10:15+02:00" in lines[1] and "*A!" in lines[1]
```

How auth is bypassed without `MGRAPHCTL_FIXTURE_DIR`: `tests/conftest.py` installs an **autouse** `fake_auth` fixture that `monkeypatch.setattr(auth, "get_access_token", lambda force_refresh=False: token)` where `token = auth.synthetic_token(scopes)`; `scopes` is every known scope (`config.DEFAULT_SCOPES + config.EXTENDED_EXTRA + config.ON_DEMAND_SCOPES` plus `auth.DECLARED_SCOPES`) unless the test carries `@pytest.mark.scopes([...])`, in which case the synthetic `scp` holds exactly those. `auth.require_scopes` is **not** patched, so the real gate runs against the synthetic claim. The fixture also `monkeypatch.setattr(auth, "save_cache", lambda: None)`, sets `MGRAPHCTL_TZ=Europe/Warsaw`, `COLUMNS=200`, `NO_COLOR=1`, and deletes `MGRAPHCTL_FIXTURE_DIR`/`MGRAPHCTL_RECORD`. Modules whose `pytestmark = pytest.mark.real_auth` (only `test_auth.py`) skip the fixture. The `graph` fixture is `respx.mock(assert_all_called=False)` (default `assert_all_mocked=True`, so an unexpected request fails the test). `invoke(*args, input=None)` runs `CliRunner().invoke(app, list(args), input=input, catch_exceptions=False)`; `result.stdout` and `result.stderr` are separate.

### (d) `--dry-run` test

```python
@covers("mail reply")
def test_mail_reply_dry_run(invoke, graph):
    result = invoke("mail", "reply", "AAMk-msg-0001", "--body", "Thanks", "--dry-run", "--json")
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["dryRun"] is True
    assert doc["requests"] == [{
        "method": "POST",
        "url": "https://graph.microsoft.com/v1.0/me/messages/AAMk-msg-0001/reply",
        "headers": {"Content-Type": "application/json"},
        "body": {"comment": "Thanks"},
    }]
    assert graph.calls.call_count == 0


@covers("mail reply")
def test_mail_reply_dry_run_text(invoke, graph):
    result = invoke("mail", "reply", "AAMk-msg-0001", "--body", "Thanks", "--dry-run")
    assert result.stdout.startswith("DRY RUN — nothing sent\n1. POST https://graph.microsoft.com/v1.0/me/messages/AAMk-msg-0001/reply\n")
    assert graph.calls.call_count == 0


@covers("mail reply")
def test_mail_reply_sends(invoke, graph):
    route = graph.post("https://graph.microsoft.com/v1.0/me/messages/AAMk-msg-0001/reply").mock(
        return_value=httpx.Response(202))
    result = invoke("mail", "reply", "AAMk-msg-0001", "--body", "Thanks", "--json")
    assert result.exit_code == 0 and json.loads(result.stdout) == {"status": "sent"}
    assert json.loads(route.calls.last.request.content) == {"comment": "Thanks"}
```

### (e) Exit-code tests

```python
@covers("mail read")
@pytest.mark.parametrize("status,code,exit_code", [(404, "ErrorItemNotFound", 4), (403, "ErrorAccessDenied", 3), (400, "BadRequest", 1)])
def test_mail_read_error_exit_codes(invoke, graph, status, code, exit_code):
    graph.get("https://graph.microsoft.com/v1.0/me/messages/AAMk-x").mock(return_value=graph_error(status, code))
    result = invoke("mail", "read", "AAMk-x")
    assert result.exit_code == exit_code
    assert result.stdout == ""
    assert result.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("mail read")
def test_mail_read_401_after_refresh(invoke, graph):
    route = graph.get("https://graph.microsoft.com/v1.0/me/messages/AAMk-x").mock(
        return_value=graph_error(401, "InvalidAuthenticationToken"))
    result = invoke("mail", "read", "AAMk-x")
    assert result.exit_code == 3 and route.call_count == 2
    assert result.stderr.startswith("error[UNAUTHORIZED]:") and "login --force" in result.stderr


@covers("mail mark")
@pytest.mark.scopes(["User.Read", "Mail.Read"])
def test_mail_mark_missing_scope(invoke, graph):
    result = invoke("mail", "mark", "AAMk-x", "--read")
    assert result.exit_code == 3 and graph.calls.call_count == 0
    assert result.stderr.startswith("error[MISSING_SCOPE]: this command needs Mail.ReadWrite; the current token has Mail.Read\n")
    assert "login --scopes extended" in result.stderr


@covers("mail list")
def test_mail_list_limit_zero_is_usage_error(invoke):
    assert invoke("mail", "list", "--limit", "0").exit_code == 2


@covers("mail list")
def test_mail_list_all_and_limit_conflict(invoke):
    result = invoke("mail", "list", "--all", "--limit", "5")
    assert result.exit_code == 2 and result.stderr.startswith("error[USAGE]: --all and --limit are mutually exclusive")
```

`helpers.graph_error(status, code, message="boom", request_id="req-0001")` returns `httpx.Response(status, json={"error": {"code": code, "message": message, "innerError": {"request-id": request_id, "date": "2026-09-02T00:00:00"}}})`.

## Phase 0 — core (sequential unless noted)

Conventions for every task: `$SCRIPTS = $ROOT/plugins/mgraphctl/skills/mgraphctl/scripts`; test runs are `cd $SCRIPTS && uv run pytest tests/<file> -q`; lint is `cd $SCRIPTS && uv run ruff check src tests && uv run ruff format src tests`; commits run from `$ROOT`.

### Task 1: Scaffold the uv project, shim and version test   (Phase 0, sequential, depends on: nothing)

**Files:** Create `/.gitignore` (modify), `plugins/mgraphctl/.claude-plugin/plugin.json`, `$SCRIPTS/pyproject.toml`, `$SCRIPTS/.python-version`, `$SCRIPTS/uv.lock`, `$SCRIPTS/mgraphctl`, `$SCRIPTS/src/mgraphctl/__init__.py`, `$SCRIPTS/src/mgraphctl/__main__.py`, `$SCRIPTS/src/mgraphctl/cli.py` (stub, replaced in T6), `$SCRIPTS/tests/test_version.py`.
**Interfaces:** Produces `mgraphctl.__version__ = "0.1.0"`, console script `mgraphctl = "mgraphctl.cli:main"`, `cli.app`/`cli.main()` (stub), the shim, the lock. Consumes nothing.

- [ ] **Step 1: Check tools.** Run `uv --version` (expect `uv 0.12.x`) and `uv python find 3.11` (expect a 3.11 interpreter path). If 3.11 is missing run `uv python install 3.11`.
- [ ] **Step 2: Write `$SCRIPTS/pyproject.toml`** (spec §2.3 verbatim; the two `markers` lines are needed by the test conventions of this plan):
  ```toml
  [project]
  name = "mgraphctl"
  version = "0.1.0"
  description = "Microsoft Graph CLI behind the mgraphctl Claude Code skill"
  requires-python = ">=3.11,<3.14"
  dependencies = [
    "msal>=1.38,<2",
    "httpx>=0.28,<1",
    "typer>=0.27,<1",
    "markdownify>=1.2,<2",
    "tzdata; sys_platform == 'win32'",
  ]

  [project.scripts]
  mgraphctl = "mgraphctl.cli:main"

  [dependency-groups]
  dev = ["pytest>=8", "respx>=0.23", "ruff>=0.13"]

  [build-system]
  requires = ["uv_build>=0.8,<1"]
  build-backend = "uv_build"

  [tool.uv]
  exclude-newer = "2026-09-01T00:00:00Z"

  [tool.uv.build-backend]
  module-name = "mgraphctl"

  [tool.ruff]
  line-length = 100
  target-version = "py311"

  [tool.ruff.lint]
  select = ["E", "F", "I", "UP", "B", "SIM"]

  [tool.pytest.ini_options]
  testpaths = ["tests"]
  addopts = "-q"
  markers = [
    "real_auth: module tests auth itself; do not install the fake token provider",
    "scopes(list): scopes carried by the synthetic token for this test",
  ]
  ```
- [ ] **Step 3: Write `$SCRIPTS/.python-version`** containing `3.11` and a trailing newline.
- [ ] **Step 4: Write the package skeleton.** `src/mgraphctl/__init__.py`:
  ```python
  """mgraphctl: Microsoft Graph CLI for the mgraphctl skill."""

  __version__ = "0.1.0"
  ```
  `src/mgraphctl/__main__.py`:
  ```python
  from .cli import main

  main()
  ```
  `src/mgraphctl/cli.py` (stub; T6 replaces the whole file):
  ```python
  """Command-line entry point (minimal stub; completed in Task 6)."""

  from typing import Annotated

  import typer

  from mgraphctl import __version__

  app = typer.Typer(add_completion=False, invoke_without_command=True, rich_markup_mode=None,
                    pretty_exceptions_enable=False)


  def _version(value: bool) -> None:
      if value:
          typer.echo(f"mgraphctl {__version__}")
          raise typer.Exit(0)


  @app.callback()
  def root(
      ctx: typer.Context,
      version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True,
                                            help="Print the version and exit.")] = False,
  ) -> None:
      """Microsoft Graph from the command line."""
      if ctx.invoked_subcommand is None:
          typer.echo(ctx.get_help())
          raise typer.Exit(0)


  def main() -> None:
      app(prog_name="mgraphctl")
  ```
- [ ] **Step 5: Write the failing version test** `$SCRIPTS/tests/test_version.py`:
  ```python
  """The three version strings must agree (spec §2.3)."""

  import importlib.metadata
  import json
  from pathlib import Path

  import mgraphctl

  PLUGIN_JSON = Path(__file__).resolve().parents[1] / ".claude-plugin" / "plugin.json"


  def test_versions_agree():
      assert mgraphctl.__version__ == importlib.metadata.version("mgraphctl")
      assert json.loads(PLUGIN_JSON.read_text())["version"] == mgraphctl.__version__
  ```
- [ ] **Step 6: Lock and sync.** `cd $SCRIPTS && uv lock && uv sync` (creates `$SCRIPTS/.venv` with the dev group; `uv.lock` is committed). Confirm `uv run python -c "import msal, httpx, typer, markdownify, rich; print(msal.__version__, httpx.__version__, typer.__version__)"` prints `1.38.x 0.28.x 0.27.x`.
- [ ] **Step 7: Run the test, expect failure.** `uv run pytest tests/test_version.py -q` → fails with `FileNotFoundError` on `plugin.json`.
- [ ] **Step 8: Write `plugins/mgraphctl/.claude-plugin/plugin.json`** (spec §2.1; mirrors `plugins/msgraph/.claude-plugin/plugin.json` style):
  ```json
  {
    "$schema": "https://json.schemastore.org/claude-code-plugin.json",
    "name": "mgraphctl",
    "version": "0.1.0",
    "description": "Work with Microsoft 365 — Outlook mail and calendar, Teams chats and channels, presence, meetings and transcripts, SharePoint, OneDrive, OneNote, Planner, To Do, people and org chart — through the Microsoft Graph API (Python CLI run with uv).",
    "author": {
      "name": "Sviatoslav Sviridov",
      "email": "sviridov@gmail.com"
    },
    "keywords": ["microsoft-365", "graph-api", "outlook", "teams", "sharepoint", "onedrive", "python", "uv"]
  }
  ```
- [ ] **Step 9: Run the test, expect pass.** `uv run pytest tests/test_version.py -q` → `1 passed`.
- [ ] **Step 10: Write the shim** `$SCRIPTS/mgraphctl` (spec §2.4 verbatim) and `chmod 755 $SCRIPTS/mgraphctl`:
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
- [ ] **Step 11: Smoke the shim into a throw-away env.** `UV_PROJECT_ENVIRONMENT=/tmp/mgraphctl-venv-shim $SCRIPTS/mgraphctl --version` → stderr shows the first-run notice, stdout `mgraphctl 0.1.0`, exit 0. Then `... $SCRIPTS/mgraphctl` with no args → help on stdout, exit 0. Confirm `ls -a $SCRIPTS` shows no `__pycache__` outside `.venv` and no new files.
- [ ] **Step 12: Update `/.gitignore`** by appending (keep the existing three lines):
  ```
  plugins/mgraphctl/skills/mgraphctl/scripts/.venv/
  **/tests/fixtures/live/
  .pytest_cache/
  .ruff_cache/
  ```
- [ ] **Step 13: Lint.** `cd $SCRIPTS && uv run ruff check src tests && uv run ruff format src tests` → clean.
- [ ] **Step 14: Commit.** From `$ROOT`: `git add .gitignore plugins/mgraphctl/.claude-plugin/plugin.json plugins/mgraphctl/skills/mgraphctl/scripts/pyproject.toml plugins/mgraphctl/skills/mgraphctl/scripts/.python-version plugins/mgraphctl/skills/mgraphctl/scripts/uv.lock plugins/mgraphctl/mgraphctl plugins/mgraphctl/skills/mgraphctl/scripts/src plugins/mgraphctl/skills/mgraphctl/scripts/tests` then `git commit -m "feat(mgraphctl): scaffold uv project, shim and plugin manifest"`. Verify with `git status --short` that `.venv/` is not listed.

### Task 2: `config.py`, `errors.py`, `odata.py`   (Phase 0, sequential, depends on: T1)

**Files:** Create `src/mgraphctl/config.py`, `src/mgraphctl/errors.py`, `src/mgraphctl/odata.py`, `tests/test_config.py`, `tests/test_errors.py`, `tests/test_odata.py`.
**Interfaces:** Consumes `mgraphctl.__version__`. Produces everything listed under `config.py`, `errors.py`, `odata.py` in the Phase 0 contract.

- [ ] **Step 1: Write failing tests `tests/test_odata.py`** (spec §5.5):
  ```python
  from mgraphctl import odata


  def test_p_encodes_every_segment():
      assert odata.p("me", "mailFolders", "Sent Items/2026#1'x") == "/me/mailFolders/Sent%20Items%2F2026%231%27x"


  def test_query_uses_percent20_never_plus_and_drops_none():
      q = odata.query({"$select": "id,subject", "$search": '"from:a b"', "$count": True, "skip": None})
      assert q == "$select=id%2Csubject&$search=%22from%3Aa%20b%22&$count=true"
      assert "+" not in q


  def test_with_query_omits_question_mark_when_empty():
      assert odata.with_query("/me", {}) == "/me"
      assert odata.with_query("/me", {"$top": 5}) == "/me?$top=5"


  def test_kql_joins_and_quotes():
      assert odata.kql("from:x", "received>=2026-08-01") == '"from:x AND received>=2026-08-01"'


  def test_odata_str_doubles_quotes():
      assert odata.odata_str("O'Brien") == "O''Brien"


  def test_share_id_known_vector():
      assert odata.share_id("https://example.com/a") == "u!aHR0cHM6Ly9leGFtcGxlLmNvbS9h"


  def test_drive_path_quotes_segments():
      assert odata.drive_path("Docs/Q3 plan.docx") == "Docs/Q3%20plan.docx"


  def test_site_ref_forms():
      assert odata.site_ref("https://contoso.example/sites/Eng Team/Shared") == "/sites/contoso.example:/sites/Eng%20Team"
      assert odata.site_ref("https://contoso.example/teams/ops") == "/sites/contoso.example:/teams/ops"
      assert odata.site_ref("https://contoso.example/") == "/sites/contoso.example"
      assert odata.site_ref("contoso.example:/sites/a b") == "/sites/contoso.example:/sites/a%20b"
      assert odata.site_ref("contoso.example,11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222") == "/sites/contoso.example,11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222"
      assert odata.site_ref("root") == "/sites/root"
  ```
  `tests/test_config.py`:
  ```python
  from pathlib import Path

  from mgraphctl import config


  def test_scope_sets_have_spec_sizes():
      assert len(config.DEFAULT_SCOPES) == 23 and "offline_access" in config.DEFAULT_SCOPES
      assert len(config.EXTENDED_EXTRA) == 10 and len(config.EXTENDED_SCOPES) == 33


  def test_msal_scopes_strips_reserved():
      assert "offline_access" not in config.msal_scopes(config.DEFAULT_SCOPES)


  def test_resolve_scopes():
      assert config.resolve_scopes(None) == ("default", config.DEFAULT_SCOPES)
      assert config.resolve_scopes("extended") == ("extended", config.EXTENDED_SCOPES)
      name, scopes = config.resolve_scopes("User.Read, Mail.Read Files.Read")
      assert (name, scopes) == ("custom", ["User.Read", "Mail.Read", "Files.Read"])
      name, scopes = config.resolve_scopes("default", extra=["User.Read.All"])
      assert name == "custom" and scopes[-1] == "User.Read.All" and scopes.count("User.Read") == 1


  def test_settings_reads_env_each_call(monkeypatch, tmp_path):
      monkeypatch.setenv("MGRAPHCTL_TENANT_ID", "contoso.example")
      monkeypatch.setenv("MGRAPHCTL_TOKEN_CACHE", str(tmp_path / "c.json"))
      monkeypatch.setenv("MGRAPHCTL_DEBUG", "1")
      s = config.settings()
      assert s.authority == "https://login.microsoftonline.com/contoso.example"
      assert s.client_id == config.CLIENT_ID_DEFAULT and s.token_cache == tmp_path / "c.json" and s.debug == 1
      assert s.state_dir == Path.home() / ".mgraphctl" and s.fixture_dir is None
      monkeypatch.setenv("MGRAPHCTL_FIXTURE_DIR", str(tmp_path))
      monkeypatch.setenv("MGRAPHCTL_RECORD", "1")
      assert config.settings().fixture_dir == tmp_path and config.settings().record is True


  def test_shim_path_points_at_scripts_dir():
      assert config.shim_path().endswith("/mgraphctl")
  ```
  `tests/test_errors.py`:
  ```python
  from mgraphctl import errors


  def test_hierarchy_exit_codes():
      assert errors.UsageError("USAGE", "x").exit_code == 2
      assert errors.AuthError("NOT_LOGGED_IN", "x").exit_code == 3
      assert errors.NotFoundError("NOT_FOUND", "x").exit_code == 4
      assert errors.AmbiguousError("AMBIGUOUS", "x", candidates=[("1", "a")]).exit_code == 2
      body = b'{"error":{"code":"ErrorItemNotFound","message":"gone","innerError":{"request-id":"r-1"}}}'
      e = errors.graph_error_from_response(404, {"content-type": "application/json"}, body, "https://graph.microsoft.com/v1.0/me/messages/x")
      assert (e.status, e.code, e.message, e.request_id, e.exit_code) == (404, "ErrorItemNotFound", "gone", "r-1", 4)
      assert errors.graph_error_from_response(403, {}, b"nope", "u").exit_code == 3
      assert errors.graph_error_from_response(401, {}, b"", "u").exit_code == 3
      e = errors.graph_error_from_response(500, {}, b"<html>x</html>", "u")
      assert (e.code, e.exit_code, e.message) == ("HTTP_500", 1, "<html>x</html>")


  def test_format_error_block():
      e = errors.GraphError(404, "ErrorItemNotFound", "gone", request_id="r-1", url="u", body=None)
      assert errors.format_error(e) == "error[ErrorItemNotFound]: gone\n  request-id: r-1\n  hint: check the id; ids returned by 'mail move' change\n"
      a = errors.AmbiguousError("AMBIGUOUS", "team 'Eng' matches 2 teams", candidates=[("id-1", "Eng"), ("id-2", "eng")])
      assert errors.format_error(a) == "error[AMBIGUOUS]: team 'Eng' matches 2 teams\n  candidate: id-1  Eng\n  candidate: id-2  eng\n"


  def test_hints_cover_spec_codes():
      for code in ("NOT_LOGGED_IN", "UNAUTHORIZED", "MISSING_SCOPE", "CONSENT_REQUIRED", "NOT_FOUND", "THROTTLED", "InefficientFilter", "UPLOAD_SESSION_LOST", "NETWORK"):
          assert code in errors.HINTS
      assert errors.hint_for("Whatever", 429) == errors.HINTS["THROTTLED"]
  ```
- [ ] **Step 2: Run, expect failure.** `uv run pytest tests/test_odata.py tests/test_config.py tests/test_errors.py -q` → `ModuleNotFoundError`.
- [ ] **Step 3: Implement `config.py`** (spec §3, §4.1, §4.4, §5.2, §5.4). Behaviour: constants exactly as in the Phase 0 contract; `DEFAULT_SCOPES` = the 23 of §4.1 line 130 in that order; `EXTENDED_EXTRA` = the 10 of line 131 in that order; `SCOPE_IMPLIES` = the §4.4 table (`Mail.ReadWrite→(Mail.Read, Mail.ReadBasic)`, `Calendars.ReadWrite→(Calendars.Read, Calendars.ReadBasic)`, `Files.ReadWrite→(Files.Read,)`, `Files.ReadWrite.All→(Files.Read.All,)`, `Sites.ReadWrite.All→(Sites.Read.All,)`, `Chat.ReadWrite→(Chat.Read, Chat.ReadBasic, ChatMessage.Send)`, `Tasks.ReadWrite→(Tasks.Read,)`, `Notes.ReadWrite→(Notes.Read,)`, `Contacts.ReadWrite→(Contacts.Read,)`, `Presence.ReadWrite→(Presence.Read,)`, `MailboxSettings.ReadWrite→(MailboxSettings.Read,)`, `TeamMember.ReadWrite.All→(TeamMember.Read.All,)`, `Group.ReadWrite.All→(Group.Read.All,)`, `User.Read.All→(User.ReadBasic.All,)`). Key code:
  ```python
  def resolve_scopes(spec: str | None, extra: Iterable[str] = ()) -> tuple[str, list[str]]:
      spec = (spec or "default").strip()
      if spec == "default":
          name, scopes = "default", list(DEFAULT_SCOPES)
      elif spec == "extended":
          name, scopes = "extended", list(EXTENDED_SCOPES)
      else:
          name, scopes = "custom", [s for s in re.split(r"[\s,]+", spec) if s]
      for s in extra:
          if s not in scopes:
              scopes.append(s)
              name = "custom"
      return name, scopes


  def settings() -> Settings:
      env = os.environ
      tenant = env.get("MGRAPHCTL_TENANT_ID") or "common"
      scope_set, scopes = resolve_scopes(env.get("MGRAPHCTL_SCOPES"))
      state_dir = Path.home() / ".mgraphctl"
      debug_raw = (env.get("MGRAPHCTL_DEBUG") or "").strip().lower()
      debug = int(debug_raw) if debug_raw.isdigit() else (1 if debug_raw in {"true", "yes", "on"} else 0)
      fixture_dir = env.get("MGRAPHCTL_FIXTURE_DIR")
      return Settings(
          client_id=env.get("MGRAPHCTL_CLIENT_ID") or CLIENT_ID_DEFAULT,
          tenant_id=tenant,
          authority=f"https://{TOKEN_HOST}/{tenant}",
          scope_set=scope_set, scopes=scopes,
          token_cache=Path(env.get("MGRAPHCTL_TOKEN_CACHE") or state_dir / "token_cache.json").expanduser(),
          state_dir=state_dir,
          tz=env.get("MGRAPHCTL_TZ") or None, debug=debug,
          fixture_dir=Path(fixture_dir).expanduser() if fixture_dir else None,
          record=(env.get("MGRAPHCTL_RECORD") or "") == "1",
      )


  def shim_path() -> str:
      candidate = Path(__file__).resolve().parents[2] / "mgraphctl"
      return str(candidate) if candidate.exists() else "mgraphctl"
  ```
- [ ] **Step 4: Implement `errors.py`** (spec §5.6, §6.5). Behaviour: the hierarchy of the Phase 0 contract; `GraphError.__init__(status, code, message, *, request_id=None, url="", body=None)` sets `exit_code = 3 if status in (401, 403) else 4 if status == 404 else 1` and `hint = hint_for(code, status)`; `graph_error_from_response` parses `error.code`, `error.message`, `error.innerError["request-id"]` from JSON bodies and otherwise uses `code="HTTP_<status>"` with the first 500 chars of the body (decoded, errors replaced), falling back to `message="HTTP <status>"` when the body is empty; `graph_error_from_batch` does the same for an already-parsed body; `HINTS` = `{"NOT_LOGGED_IN": f"run '{shim} login' in your own terminal (opens a browser)", "UNAUTHORIZED": f"run '{shim} login --force' in your own terminal", "MISSING_SCOPE": f"run '{shim} login --scopes extended' in your own terminal", "FORBIDDEN": f"the token lacks a permission for this call; run '{shim} login --scopes extended' or ask an admin to grant consent", "CONSENT_REQUIRED": "an admin must grant consent once (URL above)", "NOT_FOUND": "check the id; ids returned by 'mail move' change", "THROTTLED": "throttled; wait and retry with a smaller --limit", "InefficientFilter": "use --search (KQL) instead of date filters with this ordering", "NETWORK": "check the network or HTTPS_PROXY and retry", "UPLOAD_SESSION_LOST": "the upload session expired; rerun the upload", "ErrorAttachmentSizeShouldNotBeLessThanMinimumSize": "internal error: attachment routed to the wrong path; report it"}` where `shim = config.shim_path()` evaluated lazily inside `hint_for` (so tests can patch); `hint_for(code, status)` returns `HINTS.get(code)` or the status mapping 401→UNAUTHORIZED, 403→FORBIDDEN, 404→NOT_FOUND, 429→THROTTLED, else `None`; `format_error` renders `error[<code>]: <message>` then `  candidate: <id>  <name>` lines for `AmbiguousError`, then `  request-id:`, `  correlation-id:`, `  hint:` when present, newline-terminated.
- [ ] **Step 5: Implement `odata.py`** (spec §5.5) with `urllib.parse.quote` and `safe=""` everywhere except `site_ref` composite ids (`safe=","`). `query()` keeps insertion order, renders `True/False` as `true/false`, drops `None`; `site_ref()` implements the forms in the test above (URL → host + `sites|teams|personal` + name; `host:/a/b` → host quoted, each segment quoted, `:/` literal; contains `,` → composite; else `p("sites", value)`).
- [ ] **Step 6: Run, expect pass.** `uv run pytest tests/test_odata.py tests/test_config.py tests/test_errors.py -q` → all pass.
- [ ] **Step 7: Lint** (`uv run ruff check src tests && uv run ruff format src tests`).
- [ ] **Step 8: Commit.** `git add plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/config.py plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/errors.py plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/odata.py plugins/mgraphctl/skills/mgraphctl/scripts/tests/test_config.py plugins/mgraphctl/skills/mgraphctl/scripts/tests/test_errors.py plugins/mgraphctl/skills/mgraphctl/scripts/tests/test_odata.py && git commit -m "feat(mgraphctl): add config, error hierarchy and OData encoding helpers"`.

### Task 3: `http.py` GraphClient + `fixtures.py` record/replay   (Phase 0, parallel group P0-B with T4 and T5, depends on: T2)

**Files:** Create `src/mgraphctl/http.py`, `src/mgraphctl/fixtures.py`, `tests/test_http.py`, `tests/test_fixture_mode.py`.
**Interfaces:** Consumes `config.*`, `errors.*`, `odata.with_query/query`. Produces the `http.py` and `fixtures.py` contract (Phase 0 contract block).

- [ ] **Step 1: Write failing tests `tests/test_http.py`.** Module header and the first four tests in full; the remaining tests as one-line specifications each of which must exist by name:
  ```python
  """GraphClient behaviour (spec §5.1–5.4, §5.7) through respx."""

  import json
  from pathlib import Path

  import httpx
  import pytest
  import respx

  from mgraphctl import errors
  from mgraphctl.http import BatchRequest, GraphClient, PlannedRequest

  V1 = "https://graph.microsoft.com/v1.0"


  @pytest.fixture
  def client(monkeypatch):
      sleeps: list[float] = []
      monkeypatch.setattr(GraphClient, "sleep", staticmethod(sleeps.append))
      tokens = iter(["tok-1", "tok-2", "tok-3"])
      c = GraphClient(lambda force: next(tokens), tz="Europe/Warsaw")
      c.sleeps = sleeps  # type: ignore[attr-defined]
      yield c
      c.close()


  @respx.mock(assert_all_called=False)
  def test_retry_after_seconds_then_success(client):
      route = respx.get(f"{V1}/me").mock(side_effect=[
          httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={"id": "1"})])
      assert client.get("/me") == {"id": "1"}
      assert route.call_count == 2 and client.sleeps == [7]


  @respx.mock(assert_all_called=False)
  def test_retry_backoff_and_max_attempts(client):
      route = respx.get(f"{V1}/me").mock(return_value=httpx.Response(503))
      with pytest.raises(errors.GraphError) as info:
          client.get("/me")
      assert info.value.status == 503 and route.call_count == 5
      assert [int(s) for s in client.sleeps] == [2, 4, 8, 16] and all(s - int(s) < 1 for s in client.sleeps)


  @respx.mock(assert_all_called=False)
  def test_401_refreshes_once_then_retries_once(client):
      route = respx.get(f"{V1}/me").mock(return_value=httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken", "message": "x"}}))
      with pytest.raises(errors.AuthError) as info:
          client.get("/me")
      assert info.value.code == "UNAUTHORIZED" and route.call_count == 2
      assert [c.request.headers["Authorization"] for c in route.calls] == ["Bearer tok-1", "Bearer tok-2"]


  @respx.mock(assert_all_called=False)
  def test_paginate_limit_and_truncated(client):
      respx.get(f"{V1}/me/messages", params__eq={"$select": "id", "$top": "25"}).mock(return_value=httpx.Response(200, json={
          "value": [{"id": "1"}, {"id": "2"}], "@odata.nextLink": f"{V1}/me/messages?$skiptoken=abc"}))
      respx.get(f"{V1}/me/messages", params__contains={"$skiptoken": "abc"}).mock(return_value=httpx.Response(200, json={"value": [{"id": "3"}]}))
      page = client.paginate("/me/messages", params={"$select": "id"}, limit=2, all_=False, cap=500, page_size=25)
      assert [i["id"] for i in page.items] == ["1", "2"] and page.truncated is True and page.pages == 1
      page = client.paginate("/me/messages", params={"$select": "id"}, limit=None, all_=True, cap=500, page_size=25)
      assert len(page.items) == 3 and page.truncated is False and page.pages == 2
      first = respx.calls[0].request
      assert first.url.query.decode() == "$select=id&$top=25"
  ```
  Also required, each a separate test function: `test_paginate_cap_sets_truncated` (cap=2 with `--all`, nextLink pending → 2 items, truncated); `test_paginate_page_size_none_sends_no_top` (`/me/joinedTeams`, query is empty, no `?`); `test_paginate_rejects_limit_below_one` (`limit=0` → `UsageError`); `test_retry_after_http_date` (`Retry-After: <RFC 1123 date 90 s ahead>` → one sleep between 85 and 95); `test_retry_after_capped_at_300` (`Retry-After: 900` → sleep 300); `test_transport_error_retried_for_get_only` (`side_effect=httpx.ConnectError("x")` then 200 for GET → success; for POST → `MsgraphError` code `NETWORK`, one call); `test_prefer_headers_joined` (`outlook_tz=True, text_body=True` → `Prefer` equals `outlook.timezone="Europe/Warsaw", outlook.body-content-type="text"`); `test_default_headers` (`Accept: application/json`, `User-Agent: mgraphctl/0.1.0`, a UUID `client-request-id`); `test_beta_switch` (`GraphClient(..., beta=True)` → `/beta/me`; `beta=False` per call overrides to `/v1.0`); `test_absolute_url_used_verbatim` (`client.get("https://graph.microsoft.com/v1.0/x?y=1")` keeps the query); `test_expect_none_on_empty_body` (`202` no body → `None`); `test_batch_chunks_and_reorders` (25 `BatchRequest`s → 2 `POST /v1.0/$batch` calls with 20 and 5 sub-requests whose ids are `"1".."20"` / `"1".."5"`; responses returned in caller order with caller ids; a sub-status 404 yields `BatchResponse.error` a `GraphError` with `exit_code == 4`; a sub-request with a body carries `Content-Type: application/json`); `test_batch_resubmits_sub_429` (first response has id "2" as 429 with `headers: {"Retry-After": "1"}`, second `$batch` call contains only that sub-request; sleep == 1); `test_upload_session_320k_chunks` (a 700 000-byte file with `chunk_size=327_680` → 3 PUTs to the `uploadUrl` with `Content-Range: bytes 0-327679/700000`, `bytes 327680-655359/700000`, `bytes 655360-699999/700000`, **no** `Authorization` header, `Content-Length` set; the last PUT's JSON body is returned); `test_upload_session_4mb_chunks` (a 9 000 000-byte file with `chunk_size=3_932_160` → ranges `0-3932159`, `3932160-7864319`, `7864320-8999999`); `test_upload_session_honours_next_expected_ranges` (first PUT returns `{"nextExpectedRanges": ["100000-"]}` → next `Content-Range` starts at 100000); `test_upload_session_404_is_lost` (PUT 404 → `MsgraphError` code `UPLOAD_SESSION_LOST`, exit 1); `test_upload_session_retries_chunk_on_503` (503 then 201 on the same chunk); `test_download_follows_302_without_bearer` (`GET /v1.0/me/drive/items/x/content` → 302 `Location: https://files.example.com/blob?tempauth=abc` → bytes route asserts request has no `Authorization` header; result `bytes == len(payload)`, `content_type == "image/png"`, `dest` exists and `dest.with_name(dest.name + ".part")` does not); `test_download_200_direct_and_creates_parent` (dest in a not-yet-existing subdirectory); `test_download_error_status_raises_graph_error` (404 → exit 4); `test_search_pages_on_more_results` (two `POST /v1.0/search/query` calls with `from` 0 then 25; hits flattened; `total` taken from the container; `more` False at the end; body of the first call equals `{"requests": [{"entityTypes": ["message"], "query": {"queryString": "q"}, "from": 0, "size": 25}]}`); `test_search_stops_at_limit` (limit=25 with `moreResultsAvailable: true` → one call, `more` True); `test_execute_json_string_and_file_bodies` (`PlannedRequest("POST", url, {"Content-Type": "application/json"}, {"a": 1})` sends JSON; a `str` body with `Content-Type: text/html` is sent raw; `file=` sends the bytes; `chunk_size=` routes to `upload_session`); `test_plan_to_json_and_text` (file step renders `{"$file": ..., "bytes": N, "contentType": "text/plain"}`; text starts with `DRY RUN — nothing sent\n1. POST https://...\n   Content-Type: application/json\n   {` and the body is indented 3 spaces); `test_debug_log_redacts` (`debug=2`, caplog at DEBUG on logger `mgraphctl.http`: a line matches `DEBUG GET https://graph.microsoft.com/v1.0/me -> 200 \d+ms \[attempt 1\]`; the body line contains `"access_token": "***"` and never the raw value; `Authorization` never appears).
- [ ] **Step 2: Write failing tests `tests/test_fixture_mode.py`** (spec §5.8; uses `FixtureTransport` in `tmp_path` with an inner respx-mocked `httpx.HTTPTransport`): `test_record_then_replay_json_roundtrip` (record `GET /v1.0/me?$select=id` via a `GraphClient(..., transport=FixtureTransport(tmp_path, record=True, inner=httpx.HTTPTransport()))` under `respx.mock`; the file `fixtures.fixture_path(tmp_path, "GET /v1.0/me?$select=id")` exists, has `key` and one `responses` entry with `body`, and no `authorization`/`set-cookie` headers; then a fresh client with `record=False` and **no** respx returns the same dict); `test_replay_binary_download_strips_query_on_unauthenticated_client` (record a 302 download whose `Location` has `?tempauth=abc`; the recorded `Location` header has no query; the target is stored under key `GET /blob` with `body_b64`; replay produces identical bytes); `test_replay_consumes_sequentially_and_exhausts` (two recorded responses for one key → third call raises `FixtureError` code `FIXTURE_EXHAUSTED`); `test_replay_missing_key` (`FIXTURE_MISSING` message contains the key and the expected file path); `test_token_host_refused` (a request to `https://login.microsoftonline.com/x` raises `FixtureError` code `FIXTURE_FORBIDDEN_HOST` in both modes); `test_transport_from_env` (`Settings` with `fixture_dir` → instance with `record` mirroring the setting; `None` otherwise); `test_fixture_key_forms` (`Authorization` present → `"GET /v1.0/me?$select=id"`; absent → `"PUT /upload"`).
- [ ] **Step 3: Run, expect failure.** `uv run pytest tests/test_http.py tests/test_fixture_mode.py -q` → `ModuleNotFoundError: mgraphctl.http`.
- [ ] **Step 4: Implement `http.py`** (spec §5.1–5.4, §5.7). Two `httpx.Client`s: `self._api = httpx.Client(timeout=httpx.Timeout(connect=10, read=60, write=60, pool=10), follow_redirects=False, trust_env=True, transport=transport)` and `self._plain = httpx.Client(timeout=LONG, follow_redirects=True, max_redirects=5, trust_env=True, transport=transport)` where `LONG = httpx.Timeout(connect=10, read=300, write=300, pool=10)`; both share the same transport object so record/replay covers downloads. Request bodies are always `bytes` (never iterators) so a request can be re-sent. Key code:
  ```python
  log = logging.getLogger("mgraphctl.http")

  def url(self, path: str, *, beta: bool | None = None) -> str:
      if path.startswith("https://") or path.startswith("http://"):
          return path
      base = config.GRAPH_BETA if (self.beta if beta is None else beta) else config.GRAPH_V1
      return base + path

  def _build(self, client, method, url, *, params=None, json_body=None, content=None, headers=None,
             outlook_tz=False, text_body=False, accept="application/json", timeout=None) -> httpx.Request:
      url = odata.with_query(url, params) if params else url          # keeps "$" and "%2C" as built
      hdrs = {"Accept": accept, "User-Agent": config.user_agent(), "client-request-id": str(uuid.uuid4())}
      prefer = []
      if outlook_tz: prefer.append(f'outlook.timezone="{self.tz}"')
      if text_body: prefer.append('outlook.body-content-type="text"')
      if prefer: hdrs["Prefer"] = ", ".join(prefer)
      hdrs.update(headers or {})
      if client is self._api: hdrs["Authorization"] = f"Bearer {self._token_provider(False)}"
      if json_body is not None:
          content = json.dumps(json_body, ensure_ascii=False).encode(); hdrs.setdefault("Content-Type", "application/json")
      return client.build_request(method, url, content=content, headers=hdrs, timeout=timeout)

  def _send(self, client, request, *, retry_transport_errors: bool, stream: bool = False) -> httpx.Response:
      attempt, refreshed = 0, False
      while True:
          attempt += 1; started = time.monotonic()
          try:
              response = client.send(request, stream=stream)
          except (httpx.ConnectError, httpx.ReadTimeout) as exc:
              if not retry_transport_errors or attempt >= config.MAX_ATTEMPTS:
                  raise MsgraphError("NETWORK", f"{type(exc).__name__}: {exc}", hint=errors.HINTS["NETWORK"]) from exc
              delay = self._backoff(attempt, None); log.debug("retry in %.1fs after %s", delay, type(exc).__name__)
              self.sleep(delay); continue
          self._log(request, response, attempt, started)
          if response.status_code == 401 and not refreshed and client is self._api:
              refreshed = True; response.close()
              new_token = self._token_provider(True)
              if not new_token: raise AuthError("UNAUTHORIZED", "token refresh failed", hint=errors.HINTS["UNAUTHORIZED"])
              request.headers["Authorization"] = f"Bearer {new_token}"; continue
          if response.status_code in config.RETRY_STATUSES and attempt < config.MAX_ATTEMPTS:
              delay = self._backoff(attempt, response.headers.get("Retry-After")); response.close()
              log.debug("retry in %.1fs after HTTP %s", delay, response.status_code); self.sleep(delay); continue
          return response

  @staticmethod
  def _backoff(attempt: int, retry_after: str | None) -> float:
      if retry_after:
          value = retry_after.strip()
          if value.isdigit(): return float(min(int(value), config.RETRY_AFTER_CAP))
          with contextlib.suppress(TypeError, ValueError):
              when = email.utils.parsedate_to_datetime(value)
              return max(0.0, min((when - datetime.now(UTC)).total_seconds(), config.RETRY_AFTER_CAP))
      return min(2 ** attempt, 30) + random.uniform(0, 1)

  def request(self, method, path, *, params=None, json=None, content=None, headers=None, beta=None,
              outlook_tz=False, text_body=False, expect="json"):
      req = self._build(self._api, method, self.url(path, beta=beta), params=params, json_body=json, content=content,
                        headers=headers, outlook_tz=outlook_tz, text_body=text_body,
                        accept="*/*" if expect == "bytes" else "application/json")
      resp = self._send(self._api, req, retry_transport_errors=(method == "GET"), stream=(expect == "response"))
      if expect == "response": 
          if resp.status_code >= 400: resp.read(); resp.close(); raise errors.graph_error_from_response(resp.status_code, resp.headers, resp.content, str(resp.url))
          return resp
      if resp.status_code == 401:
          detail = errors.graph_error_from_response(401, resp.headers, resp.content, str(resp.url))
          raise AuthError("UNAUTHORIZED", detail.message, hint=errors.HINTS["UNAUTHORIZED"], request_id=detail.request_id)
      if resp.status_code >= 400: raise errors.graph_error_from_response(resp.status_code, resp.headers, resp.content, str(resp.url))
      if expect == "none" or not resp.content: return None
      if expect == "bytes": return resp.content
      if expect == "text": return resp.text
      return resp.json()
  ```
  `paginate`: validates `limit >= 1` unless `all_` (else `UsageError`), `bound = cap if all_ else min(limit, cap)`, adds `$top=page_size` only when `page_size is not None`, GETs `odata.with_query(path, params)` then each `@odata.nextLink` verbatim while `len(items) < bound`, returns `PageResult(items[:bound], truncated=len(items) > bound or next_link is not None, pages)`. `batch`: chunks of 20, internal ids `"1".."20"`, sub-request `{"id","method","url","headers"?,"body"?}` with `Content-Type: application/json` added whenever `body` is present, `POST /$batch`, results keyed back to caller ids and returned in caller order, sub-status ≥ 400 → `BatchResponse.error = errors.graph_error_from_batch(...)`, sub-429s collected and re-submitted alone after `sleep(min(max Retry-After, 300))` up to `MAX_ATTEMPTS` rounds. `upload_session`: `POST create_path` → `uploadUrl`; sequential PUTs through `self._plain` (no bearer) with `Content-Range: bytes s-e/total` and `Content-Length`, each sent with `_send(retry_transport_errors=True)`; 404 → `MsgraphError("UPLOAD_SESSION_LOST", ...)` (exit 1); ≥ 400 → `graph_error_from_response`; next offset = first `nextExpectedRanges` start if present else `e + 1`; returns the last JSON body (`{}` when empty). `download`: builds on `_api` with `Accept: */*` and `timeout=LONG`, `stream=True`; on 301/302/303/307/308 reads `Location` and streams it through `_plain`; writes `<dest>.part` then `os.replace`; creates parent dirs; returns `DownloadResult(dest, n, content_type)`. `search`: loops `from += size` while `moreResultsAvailable` and `len(hits) < limit`, flattening `value[0].hitsContainers[].hits[]`, `total` from the container, `more = pending or len(hits) > limit`, slices to `limit`. `execute`: `chunk_size` → `upload_session(url, body, file, chunk_size=...)`; `file` → `content=file.read_bytes()`; `str`/`bytes` body → `content`; else `json=body`; passes `headers` and `expect`. `plan_to_json`/`plan_to_text` as in the contract (file bodies become `{"$file": str(path), "bytes": size, "contentType": mimetypes.guess_type(name)[0] or "application/octet-stream"}`; upload-session steps become `{"createUploadSession": body, "upload": <file dict>, "chunkSize": n}`; `note` appears only when set). `_log`: one line per attempt `%s %s -> %s %dms [attempt %d] [%s]` with the `request-id` response header; at `debug >= 2` also the response body truncated to 2 KB with `re.sub(r'("(?:access|refresh)_token"\s*:\s*")[^"]*"', r'\1***"', body)`; the logged URL for `_plain` requests has its query stripped; `Authorization` is never logged. `sleep = staticmethod(time.sleep)`.
- [ ] **Step 5: Implement `fixtures.py`** (spec §5.8): `FixtureTransport.handle_request` refuses `config.TOKEN_HOST`; `record=True` → `inner.handle_request(request)`, `response.read()`, append `{"status","headers","body"|"body_text"|"body_b64"}` to `<dir>/<sha256(key)[:16]>.json` (`{"key": key, "responses": [...]}`; headers lower-cased, `authorization`/`set-cookie` dropped, `location` query stripped), and return an equivalent `httpx.Response`; `record=False` → load the file, take `responses[cursor[key]]`, increment, build `httpx.Response(status, headers=..., content=...)` (`body` → `json.dumps(...).encode()`, `body_text` → `.encode()`, `body_b64` → `base64.b64decode`); exhausted → `FixtureError("FIXTURE_EXHAUSTED", ...)`, missing → `FixtureError("FIXTURE_MISSING", f"no fixture for {key} (expected {path})")`. `fixture_key(request)` = `f"{request.method} {request.url.raw_path.decode()}"` when the request has an `Authorization` header, else `f"{request.method} {request.url.path}"`. `transport_from_env(s)` = `FixtureTransport(s.fixture_dir, record=s.record) if s.fixture_dir else None`.
- [ ] **Step 6: Run, expect pass.** `uv run pytest tests/test_http.py tests/test_fixture_mode.py -q`.
- [ ] **Step 7: Lint.**
- [ ] **Step 8: Commit.** `git add plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/http.py plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/fixtures.py plugins/mgraphctl/skills/mgraphctl/scripts/tests/test_http.py plugins/mgraphctl/skills/mgraphctl/scripts/tests/test_fixture_mode.py && git commit -m "feat(mgraphctl): add GraphClient with retry, paging, batch, uploads and fixture transport"`.

### Task 4: `auth.py`   (Phase 0, parallel group P0-B with T3 and T5, depends on: T2)

**Files:** Create `src/mgraphctl/auth.py`, `tests/test_auth.py`.
**Interfaces:** Consumes `config.settings/resolve_scopes/msal_scopes/SCOPE_IMPLIES/ON_DEMAND_SCOPES/EXTENDED_EXTRA/shim_path`, `errors.AuthError/HINTS`. Produces the `auth.py` contract block. msal API used (verified against msal 1.38 docs/source): `msal.PublicClientApplication(client_id, authority=..., token_cache=...)`, `.get_accounts()`, `.acquire_token_silent(scopes, account=..., force_refresh=...)`, `.acquire_token_interactive(scopes, prompt=..., port=None, timeout=300, auth_uri_callback=...)` (`auth_uri_callback` travels through `**kwargs` to `AuthCodeReceiver.get_auth_response`), `.initiate_device_flow(scopes)` → dict with `user_code`/`message`, `.acquire_token_by_device_flow(flow)`, `.token_cache.find(msal.TokenCache.CredentialType.ACCESS_TOKEN, query={...})`, `msal.SerializableTokenCache().serialize()/.deserialize(str)/.has_state_changed`; the browser timeout raises `msal.oauth2cli.oauth2.BrowserInteractionTimeoutError`.

- [ ] **Step 1: Write failing tests `tests/test_auth.py`.** Header, fake, and the first tests in full:
  ```python
  """auth.py against a scripted fake msal application (spec §4)."""

  import base64
  import json
  import os
  import stat
  import time

  import msal
  import pytest

  from mgraphctl import auth, config, errors

  pytestmark = pytest.mark.real_auth


  def jwt(claims: dict) -> str:
      enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
      return f"{enc({'alg': 'none', 'typ': 'JWT'})}.{enc(claims)}."


  ACCOUNT = {"home_account_id": "uid.utid", "environment": "login.microsoftonline.com", "username": "ada@example.com"}


  class FakeApp:
      def __init__(self, *, accounts=(), silent=None, interactive=None, device=None, raise_interactive=None):
          self.accounts, self.silent, self.interactive, self.device = list(accounts), silent, interactive, device
          self.raise_interactive, self.calls, self.token_cache = raise_interactive, [], msal.SerializableTokenCache()

      def get_accounts(self, username=None):
          self.calls.append(("get_accounts",)); return self.accounts

      def acquire_token_silent(self, scopes, account, force_refresh=False, **kw):
          self.calls.append(("silent", list(scopes), force_refresh)); return self.silent

      def acquire_token_interactive(self, scopes, **kw):
          self.calls.append(("interactive", list(scopes), kw))
          if self.raise_interactive: raise self.raise_interactive
          return self.interactive

      def initiate_device_flow(self, scopes=None, **kw):
          self.calls.append(("device_flow", list(scopes or [])))
          return {"user_code": "ABCD1234", "device_code": "dc", "message": "To sign in, use a web browser to open https://microsoft.com/devicelogin and enter the code ABCD1234"}

      def acquire_token_by_device_flow(self, flow, **kw):
          self.calls.append(("device", flow["device_code"])); return self.device


  @pytest.fixture
  def fake(monkeypatch, tmp_path):
      monkeypatch.setenv("HOME", str(tmp_path))
      monkeypatch.setenv("MGRAPHCTL_TOKEN_CACHE", str(tmp_path / ".mgraphctl" / "token_cache.json"))
      monkeypatch.delenv("MGRAPHCTL_FIXTURE_DIR", raising=False)
      monkeypatch.delenv("MGRAPHCTL_SCOPES", raising=False)
      holder = {}
      monkeypatch.setattr(auth, "_build_app", lambda s, cache: holder["app"])
      monkeypatch.setattr(auth, "_app", None); monkeypatch.setattr(auth, "_cache", None)
      def install(app): holder["app"] = app; return app
      return install


  def test_silent_success_returns_token_without_interaction(fake):
      tok = jwt({"scp": "User.Read Mail.Read", "exp": int(time.time()) + 3600, "upn": "ada@example.com"})
      app = fake(FakeApp(accounts=[ACCOUNT], silent={"access_token": tok, "expires_in": 3600}))
      assert auth.get_access_token() == tok
      assert app.calls[-1] == ("silent", config.msal_scopes(config.DEFAULT_SCOPES), False)
      assert not any(c[0] in ("interactive", "device_flow") for c in app.calls)
      auth.get_access_token(force_refresh=True)
      assert app.calls[-1][2] is True


  def test_no_accounts_is_not_logged_in(fake, tmp_path):
      fake(FakeApp())
      with pytest.raises(errors.AuthError) as info:
          auth.get_access_token()
      assert info.value.code == "NOT_LOGGED_IN" and info.value.message == "no cached sign-in"
      assert info.value.hint.endswith("mgraphctl login' in your own terminal (opens a browser)")


  def test_silent_none_and_invalid_grant_are_not_logged_in(fake):
      app = fake(FakeApp(accounts=[ACCOUNT], silent=None))
      with pytest.raises(errors.AuthError) as info: auth.get_access_token()
      assert info.value.code == "NOT_LOGGED_IN"
      app.silent = {"error": "invalid_grant", "error_description": "AADSTS50173: token revoked\nTrace ID: x", "correlation_id": "corr-1"}
      with pytest.raises(errors.AuthError) as info: auth.get_access_token()
      assert (info.value.code, info.value.message, info.value.correlation_id) == ("NOT_LOGGED_IN", "AADSTS50173: token revoked", "corr-1")


  def test_consent_required_classification(fake):
      for result in ({"error": "consent_required", "error_description": "x"},
                     {"error": "invalid_grant", "error_description": "AADSTS65001: The user or administrator has not consented"},
                     {"error": "invalid_grant", "error_description": "AADSTS650052: needs approval"},
                     {"error": "invalid_grant", "error_description": "Need admin approval"}):
          fake(FakeApp(accounts=[ACCOUNT], silent=result))
          with pytest.raises(errors.AuthError) as info: auth.get_access_token()
          assert info.value.code == "CONSENT_REQUIRED"
          assert info.value.hint == "an admin must grant consent once: https://login.microsoftonline.com/common/adminconsent?client_id=" + config.CLIENT_ID_DEFAULT


  ```
  Also required, one test function each: `test_login_interactive_uses_select_account_and_login_on_force` (result kwargs: `prompt == "select_account"`, `port is None`, `timeout == 300`, callable `auth_uri_callback`; with `force=True` → `prompt == "login"`; the callback writes the URL to stderr); `test_login_interactive_timeout` (`raise_interactive=BrowserInteractionTimeoutError("x")` imported from `msal.oauth2cli.oauth2` → `AuthError` code `LOGIN_TIMEOUT`); `test_login_interactive_error_dict_uses_login_force_hint` (`{"error": "access_denied", "error_description": "user cancelled"}` → `NOT_LOGGED_IN`, hint contains `login --force`); `test_login_device_code_prints_message_to_stderr` (stderr contains `ABCD1234`; returns the device result; `("device", "dc")` in calls); `test_scopes_sent_exclude_offline_access` (every scope list in `app.calls` lacks `offline_access`); `test_cache_saved_0600_atomically` (a real `msal.SerializableTokenCache`; set `auth._cache = cache` and `cache.has_state_changed = True` (a plain attribute on `SerializableTokenCache`), then `auth.save_cache()` → file mode `0o600`, parent `0o700`, no `.tmp` left, content == `cache.serialize()`; with `has_state_changed = False` nothing is written; an unwritable parent → no exception, a debug log); `test_logout_removes_cache_only` (cache file exists → after `auth.logout()` it is gone, return value is the path; second call returns `None`); `test_decode_jwt_and_synthetic_token` (`decode_jwt(synthetic_token(["User.Read", "Mail.Read"]))` has `upn == "fixture-user@example.com"`, `oid == "00000000-0000-0000-0000-000000000001"`, `tid == "00000000-0000-0000-0000-000000000002"`, `scp == "User.Read Mail.Read"`, `exp` within 3600±5 s of now); `test_fixture_mode_bypasses_msal` (`MGRAPHCTL_FIXTURE_DIR` set, `_build_app` raising if called → `get_access_token()` returns a token whose `scp` contains every `config.DEFAULT_SCOPES`, `EXTENDED_EXTRA`, `ON_DEMAND_SCOPES` entry and every `auth.DECLARED_SCOPES` entry); `test_expand_scopes_implication_table` (`expand_scopes(["Mail.ReadWrite"]) ⊇ {"Mail.Read", "Mail.ReadBasic"}`, `Chat.ReadWrite` yields `ChatMessage.Send`, `User.Read.All` yields `User.ReadBasic.All`); `test_require_scopes_any_of_and_missing` (`require_scopes(tok(scp="Group.Read.All"), ["Team.ReadBasic.All|Group.Read.All"])` passes; `require_scopes(tok(scp="Mail.Read"), ["Mail.ReadWrite"])` raises `MISSING_SCOPE` with message `this command needs Mail.ReadWrite; the current token has Mail.Read` and hint containing `login --scopes extended`; `["OnlineMeetingRecording.Read.All"]` missing → hint contains `login --scope OnlineMeetingRecording.Read.All`; a token with none of the family → `the current token has none`; `require_scopes(tok, [])` never raises); `test_cached_access_token_reads_msal_cache_without_network` (build a real `SerializableTokenCache` by `cache.deserialize(json.dumps({"AccessToken": {"k1": {"credential_type": "AccessToken", "secret": tok, "home_account_id": "uid.utid", "environment": "login.microsoftonline.com", "client_id": config.CLIENT_ID_DEFAULT, "realm": "utid", "target": "User.Read", "cached_at": "1", "expires_on": str(int(time.time()) + 100), "extended_expires_on": "1"}}, "Account": {}}))`, set it as `FakeApp.token_cache`, accounts `[ACCOUNT]` → `cached_access_token() == tok`; no accounts → `None`; `silent` never called); `test_account_upn` (`ACCOUNT["username"]` returned; `None` when no accounts).
- [ ] **Step 2: Run, expect failure.** `uv run pytest tests/test_auth.py -q` → `ModuleNotFoundError: mgraphctl.auth`.
- [ ] **Step 3: Implement `auth.py`** (spec §4.1–4.6, §5.8 auth bypass). Key code:
  ```python
  from msal.oauth2cli.oauth2 import BrowserInteractionTimeoutError

  log = logging.getLogger("mgraphctl.auth")
  DECLARED_SCOPES: set[str] = set()
  _app: msal.PublicClientApplication | None = None
  _cache: msal.SerializableTokenCache | None = None
  CONSENT_MARKERS = ("AADSTS65001", "AADSTS650052", "Need admin approval")


  def _build_app(s: config.Settings, cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
      return msal.PublicClientApplication(s.client_id, authority=s.authority, token_cache=cache)


  def app() -> msal.PublicClientApplication:
      global _app, _cache
      if _app is None:
          s = config.settings()
          _cache = load_cache(s.token_cache)
          _app = _build_app(s, _cache)
      return _app


  def _all_scopes() -> list[str]:
      seen: dict[str, None] = dict.fromkeys(config.DEFAULT_SCOPES + config.EXTENDED_EXTRA + config.ON_DEMAND_SCOPES)
      seen.update(dict.fromkeys(sorted(DECLARED_SCOPES)))
      return [s for s in seen if s not in config.RESERVED_SCOPES]


  def acquire_silent(*, force_refresh: bool = False) -> dict:
      s = config.settings()
      if s.fixture_dir is not None and not s.record:
          log.debug("token source: fixture")
          return {"access_token": synthetic_token(_all_scopes())}
      a = app()
      accounts = a.get_accounts()
      if not accounts:
          raise AuthError("NOT_LOGGED_IN", "no cached sign-in", hint=errors.HINTS["NOT_LOGGED_IN"])
      result = a.acquire_token_silent(config.msal_scopes(s.scopes), account=accounts[0], force_refresh=force_refresh)
      if not result or "error" in result:
          raise classify_msal_error(result, during_login=False)
      log.debug("token source: %s", "refresh" if force_refresh else "cache")
      return result


  def get_access_token(force_refresh: bool = False) -> str:
      return acquire_silent(force_refresh=force_refresh)["access_token"]


  def login_interactive(scopes: list[str], *, force: bool) -> dict:
      try:
          result = app().acquire_token_interactive(
              config.msal_scopes(scopes), prompt="login" if force else "select_account", port=None, timeout=300,
              auth_uri_callback=_print_auth_uri)
      except BrowserInteractionTimeoutError as exc:
          raise AuthError("LOGIN_TIMEOUT", "the browser sign-in did not complete within 300 s",
                          hint=f"run '{config.shim_path()} login' again and finish the sign-in in the browser") from exc
      if not result or "error" in result:
          raise classify_msal_error(result, during_login=True)
      log.debug("token source: interactive")
      return result


  def _print_auth_uri(uri: str) -> None:
      sys.stderr.write(f"If no browser opened, visit this URL to sign in:\n{uri}\n"); sys.stderr.flush()


  def classify_msal_error(result: dict | None, *, during_login: bool) -> AuthError:
      result = result or {}
      desc = result.get("error_description") or ""
      first = desc.splitlines()[0] if desc else (result.get("error") or "no cached sign-in")
      if result.get("error") == "consent_required" or any(m in desc for m in CONSENT_MARKERS):
          return AuthError("CONSENT_REQUIRED", first, hint=f"an admin must grant consent once: {admin_consent_url()}",
                           correlation_id=result.get("correlation_id"))
      hint = errors.HINTS["UNAUTHORIZED"] if during_login else errors.HINTS["NOT_LOGGED_IN"]
      return AuthError("NOT_LOGGED_IN", first, hint=hint, correlation_id=result.get("correlation_id"))


  def require_scopes(token: str, declared: list[str]) -> None:
      if not declared:
          return
      held = expand_scopes(decode_jwt(token).get("scp", "").split())
      for entry in declared:
          options = entry.split("|")
          if any(o in held for o in options):
              continue
          wanted = options[0]
          family = wanted.split(".")[0]
          closest = max((h for h in held if h.split(".")[0] == family), key=len, default=None)
          if wanted in config.ON_DEMAND_SCOPES:
              hint = f"run '{config.shim_path()} login --scope {wanted}' in your own terminal"
          else:
              hint = errors.HINTS["MISSING_SCOPE"]
          raise AuthError("MISSING_SCOPE", f"this command needs {' or '.join(options)}; the current token has {closest or 'none'}", hint=hint)
  ```
  Remaining behaviour: `load_cache(path)` deserialises the file when it exists (unreadable/invalid → start empty, `log.debug`); `save_cache()` returns when `_cache is None or not _cache.has_state_changed`, else `mkdir(parents=True, exist_ok=True)` + `chmod 0o700` on the parent, `os.open(tmp, O_WRONLY|O_CREAT|O_TRUNC, 0o600)`, write `serialize()`, `os.replace(tmp, path)`, `chmod 0o600`, the whole write wrapped in `try/except OSError` → `log.debug("could not save the token cache: %s", exc)` (it runs in a `finally` block in `cli.MsgraphGroup.invoke` and must never mask the command's own exit); `logout()` resets `_app/_cache`, unlinks the cache file and returns its path, or `None`; `login_device_code(scopes)` per §4.2 (flow without `user_code` → `classify_msal_error(flow, during_login=True)`; `flow["message"]` to stderr); `decode_jwt` splits on `.`, pads base64url, `json.loads`; `expand_scopes` = held ∪ every `SCOPE_IMPLIES[h]`; `synthetic_token` builds `{"upn", "unique_name", "oid": "00000000-0000-0000-0000-000000000001", "tid": "00000000-0000-0000-0000-000000000002", "scp": " ".join(scopes), "iat": now, "exp": now + ttl}` with header `{"alg": "none", "typ": "JWT"}` and an empty signature; `admin_consent_url()` uses `tid` of `cached_access_token()` when decodable else `settings().tenant_id`; `cached_access_token()` = fixture synthetic in replay mode, else the newest `expires_on` entry of `app().token_cache.find(msal.TokenCache.CredentialType.ACCESS_TOKEN, query={"home_account_id": accounts[0]["home_account_id"]})`'s `secret`, `None` without accounts; `account_upn()` = `accounts[0]["username"]` or `None`.
- [ ] **Step 4: Run, expect pass.** `uv run pytest tests/test_auth.py -q`.
- [ ] **Step 5: Lint.**
- [ ] **Step 6: Commit.** `git add plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/auth.py plugins/mgraphctl/skills/mgraphctl/scripts/tests/test_auth.py && git commit -m "feat(mgraphctl): add msal auth flows, token cache and scope gate"`.

### Task 5: `render.py` + `html.py`   (Phase 0, parallel group P0-B with T3 and T4, depends on: T2)

**Files:** Create `src/mgraphctl/render.py`, `src/mgraphctl/html.py`, `tests/test_render.py`, `tests/test_html.py`.
**Interfaces:** Consumes `errors.UsageError`, `http.Plan/plan_to_json/plan_to_text` (T3 — import lazily inside `emit` so T5 can run in parallel with T3; the `DryRunResult` branch is tested in T6 where both exist). Produces the `render.py` and `html.py` contract blocks.

- [ ] **Step 1: Write failing tests `tests/test_render.py`** (spec §6.2, §6.3, §7.3). In full:
  ```python
  """Rendering and datetime helpers (spec §6.2, §6.3)."""

  import json
  from datetime import UTC, datetime, timedelta
  from zoneinfo import ZoneInfo

  import pytest

  from mgraphctl import errors, render

  TZ = "Europe/Warsaw"


  def test_fmt_dt_converts_z_and_offsets_to_tz():
      assert render.fmt_dt("2026-08-31T08:15:00Z", TZ) == "2026-08-31T10:15+02:00"
      assert render.fmt_dt("2026-08-31T08:15:00.1234567Z", TZ) == "2026-08-31T10:15+02:00"
      assert render.fmt_dt("2026-01-10T05:00:00-05:00", TZ) == "2026-01-10T11:00+01:00"
      assert render.fmt_dt(None, TZ) == "N/A"


  def test_fmt_dtz_iana_utc_and_windows():
      assert render.fmt_dtz({"dateTime": "2026-08-31T08:15:00.0000000", "timeZone": "UTC"}, TZ) == "2026-08-31T10:15+02:00"
      assert render.fmt_dtz({"dateTime": "2026-08-31T10:15:00.0000000", "timeZone": "Europe/Warsaw"}, "UTC") == "2026-08-31T08:15+00:00"
      assert render.fmt_dtz({"dateTime": "2026-08-31T10:15:00.0000000", "timeZone": "Pacific Standard Time"}, TZ) == "2026-08-31T10:15:00.0000000 (Pacific Standard Time)"
      assert render.fmt_dtz(None, TZ) == "N/A"


  def test_fmt_event_time_all_day():
      ev = {"isAllDay": True, "start": {"dateTime": "2026-09-03T00:00:00.0000000", "timeZone": "UTC"}}
      assert render.fmt_event_time(ev, "start", TZ) == "2026-09-03 (all day)"


  def test_parse_dt_forms(monkeypatch):
      fixed = datetime(2026, 9, 2, 12, 0, tzinfo=ZoneInfo(TZ))
      monkeypatch.setattr(render, "_now", lambda zone: fixed.astimezone(zone))
      assert render.parse_dt("2026-09-05", TZ) == datetime(2026, 9, 5, 0, 0, tzinfo=ZoneInfo(TZ))
      assert render.parse_dt("2026-09-05", TZ, end_of_day=True) == datetime(2026, 9, 5, 23, 59, 59, tzinfo=ZoneInfo(TZ))
      assert render.parse_dt("2026-09-05T14:30", TZ) == datetime(2026, 9, 5, 14, 30, tzinfo=ZoneInfo(TZ))
      assert render.parse_dt("2026-09-05T14:30:15Z", TZ) == datetime(2026, 9, 5, 14, 30, 15, tzinfo=UTC)
      assert render.parse_dt("2026-09-05T14:30+02:00", TZ).utcoffset() == timedelta(hours=2)
      assert render.parse_dt("now", TZ) == fixed
      assert render.parse_dt("today", TZ) == fixed.replace(hour=0, minute=0)
      assert render.parse_dt("tomorrow", TZ, end_of_day=True) == datetime(2026, 9, 3, 23, 59, 59, tzinfo=ZoneInfo(TZ))
      assert render.parse_dt("yesterday", TZ).day == 1
      assert render.parse_dt("+2d", TZ) == fixed + timedelta(days=2)
      assert render.parse_dt("-30d", TZ) == fixed - timedelta(days=30)
      assert render.parse_dt("+3h", TZ) == fixed + timedelta(hours=3)
      with pytest.raises(errors.UsageError):
          render.parse_dt("next tuesday", TZ)


  def test_parse_duration_and_iso():
      assert render.parse_duration("30m") == timedelta(minutes=30)
      assert render.parse_duration("2h") == timedelta(hours=2)
      assert render.parse_duration("1d") == timedelta(days=1)
      assert render.parse_duration("PT30M") == timedelta(minutes=30)
      assert render.parse_duration("PT1H30M") == timedelta(hours=1, minutes=30)
      assert render.iso_duration(timedelta(hours=1, minutes=30)) == "PT1H30M"
      with pytest.raises(errors.UsageError):
          render.parse_duration("2026-09-05T10:00")


  def test_to_graph_dtz_and_iso_offset_and_kql_date():
      dt = datetime(2026, 9, 5, 14, 30, tzinfo=ZoneInfo(TZ))
      assert render.to_graph_dtz(dt, TZ) == {"dateTime": "2026-09-05T14:30:00", "timeZone": TZ}
      assert render.to_graph_dtz(datetime(2026, 9, 5, 12, 30, tzinfo=UTC), TZ) == {"dateTime": "2026-09-05T14:30:00", "timeZone": TZ}
      assert render.to_iso_offset(dt) == "2026-09-05T14:30:00+02:00"
      assert render.kql_date(datetime(2026, 9, 5, 23, 30, tzinfo=UTC), TZ) == "2026-09-06"


  def test_fmt_size_and_person():
      assert render.fmt_size(0) == "0 B" and render.fmt_size(1536) == "1.5 KB" and render.fmt_size(5 * 1024 * 1024) == "5.0 MB"
      assert render.fmt_person({"emailAddress": {"name": "Ada Example", "address": "ada@example.com"}}) == "Ada Example <ada@example.com>"
      assert render.fmt_person({"emailAddress": {"address": "ada@example.com"}}) == "ada@example.com"
      assert render.fmt_person(None) == ""


  def test_list_table_never_truncates_ids(capsys, monkeypatch):
      monkeypatch.setenv("COLUMNS", "80")
      long_id = "AAMk" + "x" * 150
      res = render.ListResult(items=[{"id": long_id, "s": "hello"}], columns=[render.Column("id", "id"), render.Column("subject", "s")])
      render.emit(res, json_mode=False)
      out = capsys.readouterr().out.splitlines()
      assert out[0].split() == ["id", "subject"] and long_id in out[1] and "hello" in out[1] and "\x1b[" not in out[1]


  def test_list_json_envelope_and_notes(capsys):
      res = render.ListResult(items=[{"id": "1"}], columns=[render.Column("id", "id")], truncated=True)
      render.emit(res, json_mode=True)
      captured = capsys.readouterr()
      assert json.loads(captured.out) == {"items": [{"id": "1"}], "count": 1, "truncated": True} and captured.err == ""
      render.emit(res, json_mode=False)
      assert capsys.readouterr().err.strip() == "(more results available — rerun with --all)"
      render.emit(render.ListResult(items=[{"id": "1"}], columns=[render.Column("id", "id")], truncated=True, hit_cap=200), json_mode=False)
      assert capsys.readouterr().err.strip() == "(hit the 200-item cap — narrow the query)"
      render.emit(render.ListResult(items=[], columns=[render.Column("id", "id")]), json_mode=False)
      assert capsys.readouterr().out == "No results.\n"
      render.emit(render.ListResult(items=[], columns=[], extra={"note": "n"}), json_mode=True)
      assert json.loads(capsys.readouterr().out) == {"items": [], "count": 0, "truncated": False, "note": "n"}


  def test_object_text_write_file_results(capsys, tmp_path):
      render.emit(render.ObjectResult(obj={"subject": "Hi", "from": {"emailAddress": {"address": "a@example.com"}}},
                                      fields=[("Subject", "subject"), ("From", lambda o: render.fmt_person(o["from"]))], body="Body text"), json_mode=False)
      assert capsys.readouterr().out == "Subject : Hi\nFrom    : a@example.com\n\nBody text\n"
      render.emit(render.TextResult(text="plain", json_obj={"text": "plain"}), json_mode=True)
      assert json.loads(capsys.readouterr().out) == {"text": "plain"}
      render.emit(render.WriteResult(obj={"status": "sent"}, message="Sent."), json_mode=False)
      assert capsys.readouterr().out == "Sent.\n"
      render.emit(render.FileResult(path=tmp_path / "a.png", bytes=12, meta={"contentType": "image/png"}, message="Downloaded a.png (12 B) to x"), json_mode=True)
      assert json.loads(capsys.readouterr().out) == {"path": str(tmp_path / "a.png"), "bytes": 12, "contentType": "image/png"}


  def test_truncate_and_dig():
      assert render.truncate("a" * 70) == "a" * 59 + "…" and render.truncate("short") == "short" and render.truncate(None) == ""
      assert render.dig({"a": {"b": [1]}}, "a.b") == [1] and render.dig({"a": None}, "a.b") is None


  def test_local_tz_detection(monkeypatch):
      monkeypatch.setenv("MGRAPHCTL_TZ", "Asia/Tokyo"); assert render.local_tz() == "Asia/Tokyo"
      monkeypatch.delenv("MGRAPHCTL_TZ"); monkeypatch.setenv("TZ", "Europe/Paris"); assert render.local_tz() == "Europe/Paris"
      monkeypatch.setenv("TZ", "Nowhere/City"); monkeypatch.setattr(render.os, "readlink", lambda p: "/usr/share/zoneinfo/America/New_York")
      assert render.local_tz() == "America/New_York"


  def test_windows_table_anchor_entries():
      assert len(render.WINDOWS_TO_IANA) >= 130
      for win, iana in {"Pacific Standard Time": "America/Los_Angeles", "Eastern Standard Time": "America/New_York",
                        "Central European Standard Time": "Europe/Warsaw", "W. Europe Standard Time": "Europe/Berlin",
                        "GMT Standard Time": "Europe/London", "India Standard Time": "Asia/Calcutta",
                        "Tokyo Standard Time": "Asia/Tokyo", "UTC": "Etc/UTC"}.items():   # CLDR canonical ids
          assert render.WINDOWS_TO_IANA[win] == iana
      assert all(render.is_iana(v) for v in render.WINDOWS_TO_IANA.values())
  ```
  `tests/test_html.py` in full:
  ```python
  """HTML → Markdown, text → HTML and VTT → text (spec §6.2, §7.1)."""

  from mgraphctl import html


  TEAMS = ('<div><style>p{color:red}</style><p>Hi <at id="0">Ada Example</at>, see '
           '<attachment id="a1" name="plan.docx"></attachment> and '
           '<img src="https://graph.microsoft.com/v1.0/chats/19:c@thread.v2/messages/1/hostedContents/aWQ=/$value" width="10">'
           '</p><p></p><p></p><p>Done &amp; dusted</p><systemEventMessage/></div>')


  def test_to_markdown_teams_markers():
      md = html.to_markdown(TEAMS, "teams")
      assert "@Ada Example" in md and "[attachment: plan.docx]" in md and "[image: hostedContents/aWQ=]" in md
      assert "[system event]" in md and "color:red" not in md and "Done & dusted" in md
      assert "\n\n\n" not in md


  def test_to_markdown_mail_keeps_at_text_and_links():
      md = html.to_markdown('<p><b>Bold</b> <a href="https://example.com/x">link</a> <at id="1">Ada</at></p><script>x()</script>', "mail")
      assert md == "**Bold** [link](https://example.com/x) Ada"


  def test_to_markdown_onenote_headings():
      assert html.to_markdown("<html><body><h1>Title</h1><p>Body</p></body></html>", "onenote") == "# Title\n\nBody"


  def test_text_to_html_escapes_and_paragraphs():
      assert html.text_to_html("a <b>\nc\n\nd & e") == "<p>a &lt;b&gt;<br>c</p><p>d &amp; e</p>"


  def test_vtt_to_text():
      vtt = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\n<v Ada Example>Hello there</v>\n\n00:00:03.500 --> 00:00:05.000\nplain line\n"
      assert html.vtt_to_text(vtt) == "[00:00:01] Ada Example: Hello there\n[00:00:03] plain line"
  ```
- [ ] **Step 2: Run, expect failure.** `uv run pytest tests/test_render.py tests/test_html.py -q` → `ModuleNotFoundError`.
- [ ] **Step 3: Generate `WINDOWS_TO_IANA`** once with this throw-away script (run from `$SCRIPTS`, output pasted into `render.py` as a literal dict sorted by key; the script is not committed):
  ```bash
  uv run python - <<'EOF'
  import urllib.request, xml.etree.ElementTree as ET
  xml = urllib.request.urlopen("https://raw.githubusercontent.com/unicode-org/cldr/main/common/supplemental/windowsZones.xml").read()
  root = ET.fromstring(xml)
  rows = {m.get("other"): m.get("type").split()[0] for m in root.iter("mapZone") if m.get("territory") == "001"}
  print("WINDOWS_TO_IANA: dict[str, str] = {")
  for k in sorted(rows): print(f"    {k!r}: {rows[k]!r},")
  print("}")
  EOF
  ```
  Expect roughly 140 rows (the CLDR "001" primary mappings). Add the comment `# CLDR windowsZones.xml territory="001" mappings, generated 2026-09-02; regenerate with the script in the plan.`
- [ ] **Step 4: Implement `render.py`** (spec §6.2, §6.3, §7.3). Key code:
  ```python
  def _now(zone: ZoneInfo) -> datetime:                       # patched by tests
      return datetime.now(zone)

  def _console(natural_width: int) -> Console:
      width = max(int(os.environ.get("COLUMNS") or 200), natural_width)
      return Console(file=sys.stdout, width=width, force_terminal=False, no_color="NO_COLOR" in os.environ,
                     soft_wrap=True, highlight=False, markup=False)

  def _cell(col: Column, item: dict) -> str:
      value = col.path(item) if callable(col.path) else dig(item, col.path)
      if value is None: return ""
      if isinstance(value, list): return ", ".join(str(v) for v in value)
      return str(value)

  def _emit_list(res: ListResult) -> None:
      if not res.items:
          sys.stdout.write(res.empty_text + "\n")
      else:
          rows = [[_cell(c, it) for c in res.columns] for it in res.items]
          widths = [max(len(c.header), *(len(r[i]) for r in rows)) for i, c in enumerate(res.columns)]
          table = Table(box=None, show_edge=False, pad_edge=False, padding=(0, 2), header_style="bold")
          for c in res.columns: table.add_column(c.header, no_wrap=True, overflow="ignore")
          for r in rows: table.add_row(*r)
          _console(sum(widths) + 2 * (len(widths) - 1) + 1).print(table)
      if res.truncated:
          note(f"(hit the {res.hit_cap}-item cap — narrow the query)" if res.hit_cap else "(more results available — rerun with --all)")

  def emit(result: Result, *, json_mode: bool) -> None:
      if json_mode:
          sys.stdout.write(json.dumps(_to_json(result), indent=2, ensure_ascii=False) + "\n"); return
      match result:
          case ListResult(): _emit_list(result)
          case ObjectResult():
              width = max(len(label) for label, _ in result.fields)
              for label, path in result.fields:
                  value = path(result.obj) if callable(path) else dig(result.obj, path)
                  sys.stdout.write(f"{label:<{width}} : {'' if value is None else value}\n")
              if result.body is not None: sys.stdout.write("\n" + result.body.rstrip("\n") + "\n")
          case TextResult(): sys.stdout.write(result.text.rstrip("\n") + "\n")
          case WriteResult() | FileResult(): sys.stdout.write(result.message + "\n")
          case DryRunResult():
              from mgraphctl.http import plan_to_text
              sys.stdout.write(plan_to_text(result.plan))
  ```
  `_to_json`: `ListResult` → `{"items", "count", "truncated", **extra}`; `ObjectResult` → `obj`; `TextResult` → `json_obj`; `WriteResult` → `obj if obj is not None else {"status": "ok"}`; `DryRunResult` → `{"dryRun": True, "requests": plan_to_json(plan)}` (lazy import); `FileResult` → `{"path": str(path), "bytes": bytes, **meta}`. `fmt_dt` truncates fractional seconds to 6 digits with `re.sub(r"(\.\d{6})\d+", r"\1", v)`, replaces a trailing `Z` with `+00:00`, `datetime.fromisoformat`, `.astimezone(ZoneInfo(tz)).isoformat(timespec="minutes")`. `fmt_dtz`: `timeZone == "UTC"` or `is_iana(timeZone)` → aware in that zone → `--tz`; else `f"{dateTime} ({timeZone})"`. `is_iana(name)`: `try: ZoneInfo(name); return True; except (ZoneInfoNotFoundError, ValueError, IsADirectoryError): return False` (memoised with `functools.cache`). `fmt_event_time(event, key, tz)`: `isAllDay` → `dateTime[:10] + " (all day)"` else `fmt_dtz(event[key], tz)`. `parse_dt`: the forms of the test; `_day(date, zone, end_of_day)` builds 00:00:00 or 23:59:59; ISO parsing via `datetime.fromisoformat(v.replace("Z", "+00:00"))`; naive → `replace(tzinfo=ZoneInfo(tz))`; anything else → `UsageError("USAGE", f"invalid datetime {value!r}: use YYYY-MM-DD, YYYY-MM-DDTHH:MM[:SS][Z|±HH:MM], now, today, tomorrow, yesterday, +Nd, -Nd, +Nh")`. `parse_duration`: `^(\d+)([mhd])$` or `^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$` or `^P(\d+)D$`, else `UsageError("USAGE", f"invalid duration {value!r}: use 30m, 2h, 1d or ISO 8601 PT30M")`. `iso_duration(td)`: `PT{h}H{m}M` omitting zero parts (`PT0M` for zero). `to_graph_dtz(dt, tz)`: `dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%dT%H:%M:%S")`. `to_iso_offset(dt)`: `dt.isoformat(timespec="seconds")`. `kql_date(dt, tz)`: `dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")`. `fmt_size`: `B/KB/MB/GB` with one decimal above bytes. `fmt_person`: `"Name <address>"`, address alone, or `""`. `truncate(text, n=60)`: `text[: n - 1] + "…"` when longer than `n`. `local_tz()` per §6.3 (`MGRAPHCTL_TZ` → `TZ` if `is_iana` → `os.readlink("/etc/localtime")` suffix after `zoneinfo/` → on `win32` `WINDOWS_TO_IANA.get(time.tzname[0])` → `"UTC"` with a one-time `note("warning: could not detect the local time zone; using UTC (set MGRAPHCTL_TZ)")`). `note(text)` writes `text + "\n"` to `sys.stderr`.
- [ ] **Step 5: Implement `html.py`** with markdownify 1.2 (`MarkdownConverter` subclass; hook signature `convert_<tag>(self, el, text, parent_tags)`; bs4 comes with markdownify): `to_markdown(html, mode)` parses with `BeautifulSoup(html, "html.parser")`, `decompose()`s every `style`/`script`, converts with `_TeamsConverter` when `mode == "teams"` (`convert_at` → `"@" + text`, `convert_attachment` → `[attachment: <name or id>]`, `convert_img` → `[image: hostedContents/<id>]` when `src` matches `/hostedContents/([^/]+)/\$value` else the default image, `convert_systemeventmessage` → `[system event]`) and the plain `MarkdownConverter` otherwise (so `<at>` renders as its text), options `heading_style="ATX"`, `bullets="-"`, `escape_underscores=False`, `escape_asterisks=False`; post-process with `re.sub(r"\n{3,}", "\n\n", text).strip()`. `text_to_html(text)`: split on blank lines into `<p>` paragraphs, `html.escape` each line, join lines with `<br>`. `vtt_to_text(vtt)`: iterate cue blocks; a timing line `HH:MM:SS.mmm --> ...` gives the stamp `[HH:MM:SS]`; following text lines have `<v Name>...</v>` turned into `Name: ...` and other tags stripped; one output line per cue, joined by `\n`.
- [ ] **Step 6: Run, expect pass.** `uv run pytest tests/test_render.py tests/test_html.py -q`.
- [ ] **Step 7: Lint.**
- [ ] **Step 8: Commit.** `git add plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/render.py plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/html.py plugins/mgraphctl/skills/mgraphctl/scripts/tests/test_render.py plugins/mgraphctl/skills/mgraphctl/scripts/tests/test_html.py && git commit -m "feat(mgraphctl): add result renderers, datetime helpers and HTML conversion"`.

### Task 6: `cli.py`, registry, `resolve.py`, `graph/users.py`, top-level commands, test infrastructure   (Phase 0, parallel group P0-C with T7, depends on: T3, T4, T5)

**Files:** Create `src/mgraphctl/cli.py` (replace the T1 stub), `src/mgraphctl/resolve.py`, `src/mgraphctl/commands/__init__.py`, `src/mgraphctl/commands/top.py`, `src/mgraphctl/commands/api.py`, `src/mgraphctl/graph/__init__.py`, `src/mgraphctl/graph/users.py`, `tests/helpers.py`, `tests/conftest.py`, `tests/test_cli_root.py`, `tests/test_cli_top.py`, `tests/test_cli_api.py`, `tests/test_resolve.py`, `tests/test_graph_users.py`, `tests/test_surface.py`, `tests/fixtures/top/me.json`, `tests/fixtures/top/me_photo.json`, `tests/fixtures/api/get_me.json`, `tests/fixtures/api/paged.json`, `tests/fixtures/users/get_user.json`, `tests/fixtures/users/search_users.json`, `tests/fixtures/users/unified_groups.json`, `tests/fixtures/replay/<hash>.json`.
**Interfaces:** Consumes `http.GraphClient`, `auth.*`, `render.*`, `errors.*`, `config.*`, `fixtures.transport_from_env`, `odata.p`. Produces the `cli.py`, `commands/__init__.py`, `resolve.py`, `graph/users.py`, `tests/helpers.py`, `tests/conftest.py` contract blocks. **Registration mechanism (frozen for Phase 1):** `commands/__init__.py` holds the static list below; `register_all(root)` imports each module lazily; a module that does not exist yet is skipped with `log.debug("noun %s not implemented yet", name)`; a module that exists must expose `app: typer.Typer` (kind `group`) or `command: Callable` (kind `command`). Phase 1 tasks only create their module — they never edit `cli.py` or this registry.

```python
NOUNS: list[Noun] = [
    Noun("mail", "mgraphctl.commands.mail", "Outlook mail."),
    Noun("mailbox", "mgraphctl.commands.mailbox", "Mailbox settings, automatic replies, focused inbox."),
    Noun("calendar", "mgraphctl.commands.calendar", "Calendar events, availability, meeting times."),
    Noun("people", "mgraphctl.commands.people", "People, contacts and directory users."),
    Noun("org", "mgraphctl.commands.org", "Manager, direct reports, management chain."),
    Noun("groups", "mgraphctl.commands.groups", "Microsoft 365 groups."),
    Noun("teams", "mgraphctl.commands.teams", "Teams and channels."),
    Noun("chats", "mgraphctl.commands.chats", "Teams chats and direct messages."),
    Noun("presence", "mgraphctl.commands.presence", "Teams presence."),
    Noun("meetings", "mgraphctl.commands.meetings", "Online meetings, transcripts, AI insights."),
    Noun("onedrive", "mgraphctl.commands.onedrive", "OneDrive files."),
    Noun("sharepoint", "mgraphctl.commands.sharepoint", "SharePoint sites, drives and lists."),
    Noun("onenote", "mgraphctl.commands.onenote", "OneNote notebooks and pages."),
    Noun("planner", "mgraphctl.commands.planner", "Planner plans and tasks."),
    Noun("todo", "mgraphctl.commands.todo", "Microsoft To Do."),
    Noun("search", "mgraphctl.commands.search", "Unified search across Microsoft 365.", kind="command"),
]
```

- [ ] **Step 1: Write `tests/helpers.py`** (test infrastructure, no test functions):
  ```python
  """Shared test helpers: coverage registry, fixture loading, respx routing."""

  import json
  from pathlib import Path

  import httpx
  import respx

  FIXTURES = Path(__file__).parent / "fixtures"
  VERBS_TESTED: set[str] = set()
  GRAPH = "https://graph.microsoft.com"


  def covers(*verbs: str):
      """Mark a test as covering the given `noun verb` names (test_surface.py checks completeness)."""
      VERBS_TESTED.update(verbs)
      return lambda fn: fn


  def load_fixture(name: str) -> list[dict]:
      noun, _, verb = name.partition("/")
      return json.loads((FIXTURES / noun / f"{verb}.json").read_text())


  def _response(entry: dict) -> httpx.Response:
      headers = entry.get("headers") or {}
      if "json" in entry:
          return httpx.Response(entry["status"], json=entry["json"], headers=headers)
      if "text" in entry:
          return httpx.Response(entry["status"], text=entry["text"], headers=headers)
      if "b64" in entry:
          import base64
          return httpx.Response(entry["status"], content=base64.b64decode(entry["b64"]), headers=headers)
      return httpx.Response(entry["status"], headers=headers)


  def mock_graph(router: respx.MockRouter, name: str) -> list[respx.Route]:
      """Register one respx route per fixture entry; `path` exact, `query` (optional) compared decoded and exactly."""
      routes = []
      for entry in load_fixture(name):
          kwargs = {"method": entry["method"], "url": GRAPH + entry["path"]}
          if "query" in entry:
              kwargs["params__eq"] = entry["query"]
          responses = entry["responses"] if "responses" in entry else [entry]
          route = router.route(**kwargs).mock(side_effect=[_response(r) for r in responses]) if len(responses) > 1 \
              else router.route(**kwargs).mock(return_value=_response(responses[0]))
          routes.append(route)
      return routes


  def graph_error(status: int, code: str, message: str = "boom", request_id: str = "req-0001") -> httpx.Response:
      return httpx.Response(status, json={"error": {"code": code, "message": message,
                                                    "innerError": {"request-id": request_id, "date": "2026-09-02T00:00:00"}}})
  ```
  (A fixture entry may carry `"responses": [{"status", "json"|...}, ...]` instead of a single body when one URL must answer differently on successive calls, e.g. Planner etag re-reads.)
- [ ] **Step 2: Write `tests/conftest.py`:**
  ```python
  """Fixtures shared by every CLI test (spec §11)."""

  import pytest
  import respx
  from typer.testing import CliRunner

  from mgraphctl import auth, config

  ALL_SCOPES = [s for s in dict.fromkeys(config.DEFAULT_SCOPES + config.EXTENDED_EXTRA + config.ON_DEMAND_SCOPES)
                if s not in config.RESERVED_SCOPES]


  @pytest.fixture(autouse=True)
  def fake_auth(request, monkeypatch, tmp_path):
      monkeypatch.setenv("MGRAPHCTL_TZ", "Europe/Warsaw")
      monkeypatch.setenv("COLUMNS", "200")
      monkeypatch.setenv("NO_COLOR", "1")
      monkeypatch.delenv("MGRAPHCTL_FIXTURE_DIR", raising=False)
      monkeypatch.delenv("MGRAPHCTL_RECORD", raising=False)
      monkeypatch.delenv("MGRAPHCTL_DEBUG", raising=False)
      monkeypatch.setenv("MGRAPHCTL_TOKEN_CACHE", str(tmp_path / "token_cache.json"))
      if request.node.get_closest_marker("real_auth"):
          return
      marker = request.node.get_closest_marker("scopes")
      scopes = list(marker.args[0]) if marker else sorted(set(ALL_SCOPES) | auth.DECLARED_SCOPES)
      token = auth.synthetic_token(scopes)
      monkeypatch.setattr(auth, "get_access_token", lambda force_refresh=False: token)
      monkeypatch.setattr(auth, "cached_access_token", lambda: token)
      monkeypatch.setattr(auth, "save_cache", lambda: None)


  @pytest.fixture
  def graph():
      with respx.mock(assert_all_called=False) as router:
          yield router


  @pytest.fixture(scope="session")
  def app():
      from mgraphctl.cli import build_app
      return build_app()


  @pytest.fixture
  def invoke(app):
      runner = CliRunner()

      def _invoke(*args: str, input: str | None = None):
          return runner.invoke(app, list(args), input=input, catch_exceptions=False)

      return _invoke
  ```
- [ ] **Step 3: Write failing tests.** `tests/test_cli_root.py` (spec §6.1, §6.5) in full:
  ```python
  """Root app behaviour (spec §6.1, §6.5)."""

  import json

  import httpx

  from helpers import GRAPH, covers, mock_graph


  def test_version_flag(invoke):
      r = invoke("--version")
      assert r.exit_code == 0 and r.stdout == "mgraphctl 0.1.0\n"


  def test_no_args_prints_help_exit_0(invoke):
      r = invoke()
      assert r.exit_code == 0 and "Usage:" in r.stdout and "me" in r.stdout


  def test_noun_without_verb_prints_help_exit_0():
      # Real noun groups arrive in Phase 1 (each group's tests assert `invoke("<noun>")` → help, exit 0);
      # here an ad-hoc group proves make_noun_app's callback path.
      from typer.testing import CliRunner

      from mgraphctl.cli import build_app, make_noun_app

      root = build_app()
      root.add_typer(make_noun_app("Probe group."), name="probe")
      r = CliRunner().invoke(root, ["probe"], catch_exceptions=False)
      assert r.exit_code == 0 and "Usage:" in r.stdout


  def test_tz_propagates_to_prefer(invoke, graph):
      route = graph.get(f"{GRAPH}/v1.0/me").mock(return_value=httpx.Response(200, json={"id": "1"}))
      assert invoke("--tz", "Asia/Tokyo", "api", "GET", "/me", "--query", "$select=id", "--outlook-tz").exit_code == 0
      assert route.calls.last.request.headers["Prefer"] == 'outlook.timezone="Asia/Tokyo"'


  def test_bad_tz_is_usage_error(invoke):
      r = invoke("--tz", "Mars/Olympus", "me")
      assert r.exit_code == 2 and r.stderr.startswith("error[USAGE]: unknown time zone 'Mars/Olympus'")


  def test_beta_switches_base(invoke, graph):
      route = graph.get(f"{GRAPH}/beta/me").mock(return_value=httpx.Response(200, json={"id": "1"}))
      assert invoke("--beta", "me", "--json").exit_code == 0 and route.called


  def test_errors_never_on_stdout_and_json_never_on_stderr(invoke, graph):
      graph.get(f"{GRAPH}/v1.0/me").mock(return_value=httpx.Response(404, json={"error": {"code": "NotFound", "message": "x"}}))
      r = invoke("me", "--json")
      assert r.exit_code == 4 and r.stdout == "" and r.stderr.startswith("error[NotFound]: x\n")


  def test_unknown_option_is_click_usage_error(invoke):
      assert invoke("me", "--bogus").exit_code == 2


  def test_debug_logs_to_stderr(invoke, graph):
      graph.get(f"{GRAPH}/v1.0/me").mock(return_value=httpx.Response(200, json={"id": "1"}))
      r = invoke("--debug", "me", "--json")
      assert r.exit_code == 0 and json.loads(r.stdout)["id"] == "1"
      assert "GET https://graph.microsoft.com/v1.0/me" in r.stderr and "Bearer" not in r.stderr
  ```
  `tests/test_cli_top.py` — tests, each named; the first in full:
  ```python
  """login/logout/status/claims/me/version (spec §4.2, §4.3, §4.6, §8.1)."""

  import json
  import time
  from pathlib import Path

  import httpx
  import pytest

  from helpers import GRAPH, covers, graph_error, mock_graph
  from mgraphctl import auth


  @covers("me")
  def test_me_json_and_text(invoke, graph):
      routes = mock_graph(graph, "top/me")
      r = invoke("me", "--json")
      assert r.exit_code == 0 and json.loads(r.stdout)["userPrincipalName"] == "ada@example.com"
      assert routes[0].calls.last.request.url.query.decode() == "$select=id%2CdisplayName%2CuserPrincipalName%2Cmail%2CjobTitle%2Cdepartment%2CofficeLocation%2CbusinessPhones%2CmobilePhone%2CpreferredLanguage"
      r = invoke("me")
      assert r.exit_code == 0 and "Name    : Ada Example" in r.stdout and "UPN     : ada@example.com" in r.stdout
  ```
  Required tests: `test_me_photo_saves_file` (`fixtures/top/me_photo.json` = `GET /v1.0/me/photo/$value` with `b64` PNG bytes and `headers: {"content-type": "image/png"}`; `me --photo <tmp>/p.png` writes the bytes, prints `Downloaded photo (<n> B) to <path>`; `--json` gives `{"path", "bytes", "contentType"}`); `test_me_photo_404_exit_4`; `test_status_logged_in` (patch `auth.acquire_silent` to return `{"access_token": tok}` where `tok` has `upn`, `exp`; patch `auth.account_upn` → `"ada@example.com"`: stdout has `Logged in as: ada@example.com`, `Token expires: <ISO with offset>`, `Scopes: default (23)`, `Cache: <path>`; exit 0); `test_status_logged_out_json_still_on_stdout` (patch `acquire_silent` to raise `AuthError("NOT_LOGGED_IN", ...)`: exit 3, stdout JSON `{"loggedIn": false, "account": None, "expiresAt": None, "scopeSet": "default", "scopes": [...23], "cache": ...}`, stderr starts `error[NOT_LOGGED_IN]:`); `test_status_json_logged_in` (`loggedIn` True, `account`, `expiresAt`); `test_status_fixture_mode` (`real_auth` marker + `MGRAPHCTL_FIXTURE_DIR=<tmp>` → `Logged in as: fixture-user@example.com`); `test_claims_sections_and_json` (patched `cached_access_token` with a token carrying `upn, oid, tid, iat, exp, deviceid, amr: ["pwd","mfa"], scp`; text has `IDENTITY`, `DEVICE`, `AUTH METHODS`, `SCOPES` headers, `expires in` text, sorted scopes one per line; `--json` equals the payload); `test_claims_without_token_exit_3` (`cached_access_token` → `None`); `test_login_already_logged_in` (patch `auth.acquire_silent` → result; `auth.account_upn` → upn; patch `auth.login_interactive` to raise if called: stdout `Already logged in as: ada@example.com\nUse --force to re-authenticate, --scopes extended to add permissions.\n`, exit 0); `test_login_force_runs_interactive_then_get_me` (patch `auth.login_interactive` recording `(scopes, force)` and returning a result; route `GET /v1.0/me?$select=id%2CdisplayName%2CuserPrincipalName`; stdout `Logged in as: Ada Example <ada@example.com>\nScopes: default (23)\nCache: <path>\n`; `--json` → `{"account","displayName","userId","scopes","scopeSet","cache"}`); `test_login_scopes_extended_when_missing_from_token` (silent succeeds but the token's `scp` lacks `Mail.ReadWrite`; `login --scopes extended` therefore proceeds to interactive; assert the recorded scopes list equals `config.msal_scopes(config.EXTENDED_SCOPES)` and stdout ends with `Scopes: extended (33)`); `test_login_scope_on_demand_appended` (`--scope User.Read.All` → `"User.Read.All"` in the recorded scopes, `Scopes: custom (24)`); `test_login_device_code` (patch `auth.login_device_code`; `--device-code` routes there); `test_login_not_logged_in_goes_interactive` (silent raises NOT_LOGGED_IN → interactive called, not raised); `test_login_timeout_exit_3` (`login_interactive` raises `AuthError("LOGIN_TIMEOUT", ...)` → exit 3 `error[LOGIN_TIMEOUT]`); `test_logout_messages` (patch `auth.logout` → path then `None`: `Logged out. Cache removed: <path>` / `No cached credentials found.`, exit 0 both); `test_version_command` (stdout matches `^mgraphctl 0\.1\.0 \(python 3\.1[123]\.\d+, msal \S+, httpx \S+\)$`; `--json` keys `version, python, msal, httpx`); `test_me_replays_committed_corpus` (`real_auth` + `MGRAPHCTL_FIXTURE_DIR=tests/fixtures/replay` → `me --json` yields `userPrincipalName == "fixture-user@example.com"`; no respx).
  `tests/test_cli_api.py` (spec §8.17 `api`): `test_api_get_json_passthrough` (`api GET /me --query '$select=id' --json` → body as-is; query sent exactly `$select=id`; `covers("api")`); `test_api_absolute_url_and_beta` (`api --beta GET /me` → `/beta/me`; `api GET https://graph.microsoft.com/beta/x` used verbatim); `test_api_post_body_inline_and_file` (`--body '{"a":1}'` and `--body @file.json` both send JSON with `Content-Type: application/json`; `--header X-Custom:1` present); `test_api_all_follows_next_link` (`fixtures/api/paged.json` two entries → merged `value` list of 3, output `{"value": [...]}`); `test_api_raw_streams_bytes_to_output` (`--raw --output f.bin` writes bytes; without `--output` prints bytes to stdout); `test_api_non_json_body_printed_as_text` (`text/plain` body → stdout text); `test_api_dry_run` (`api POST /me/sendMail --body '{"x":1}' --dry-run --json` → `{"dryRun": true, "requests": [...]}`, no call); `test_api_no_scope_gate` (`@pytest.mark.scopes(["User.Read"])`, `api GET /me/messages` → request sent, Graph decides); `test_api_error_exit_codes` (403 → 3, 404 → 4, 500 → 1); `test_api_bad_query_format` (`--query nokey` → exit 2).
  `tests/test_resolve.py`: `looks_like_id` per §6.6 (mail_folder: `inbox`, `SentItems`, 40+ chars no spaces → True; `Projects` → False; team: GUID; channel/chat: `19:` prefix; user: GUID/`@`/`me`; site: `https://`, `:/`, `,`; drive: `b!abc`; drive_item: `id:x` → True via `split_id_prefix`, `01ABCDEFGHIJKLMNOPQRSTUV` (24 alnum) → True, `Docs/a.txt` → False; onenote: `1-abc!12` True, `0-x` True, `Meeting notes` False; planner: 28 chars of `[A-Za-z0-9_-]`; todo_list: `AQMk…`/`AAMk…`/40+; group: GUID; calendar: 40+ no spaces); `pick_unique` (exact case-insensitive unique → dict; zero → `NotFoundError` code `NOT_FOUND` exit 4 with message `team 'x' not found`; two → `AmbiguousError` with `candidates == [("id-1","Eng"),("id-2","eng")]`).
  `tests/test_graph_users.py` (respx directly on a `GraphClient` with a static token provider): `get_me` select; `get_user("me")` → `/me`; `get_user(<guid>)` → `/users/<guid>`; `get_user("ada@example.com")` → `/users/ada%40example.com`; `search_users("ada")` → `$search` equals `"displayName:ada" OR "mail:ada"`, `$count=true`, `$top=100`, header `ConsistencyLevel: eventual`; `list_unified_groups` → `$filter=groupTypes/any(c:c eq 'Unified')`, `$count=true`, `$top=999`, `$select=id,displayName`, header, pages to 999 cap; `resolve_user("Ada Example", can_search=True)` → search + unique match; `can_search=False` → `UsageError` exit 2 mentioning `User.ReadBasic.All`.
  `tests/test_surface.py`:
  ```python
  """Every registered verb is covered by a test and carries --json (spec §11)."""

  import typer.main

  import helpers


  def walk(app):
      group = typer.main.get_group(app)
      out = {}

      def rec(cmd, prefix):
          for name, sub in cmd.commands.items():
              full = f"{prefix} {name}".strip()
              if hasattr(sub, "commands"):
                  rec(sub, full)
              else:
                  out[full] = sub
      rec(group, "")
      return out


  def test_every_verb_is_covered(app):
      missing = sorted(v for v in walk(app) if v not in helpers.VERBS_TESTED)
      assert not missing, f"verbs without a @covers test: {missing}"


  def test_every_verb_has_json_flag(app):
      for verb, cmd in walk(app).items():
          assert any("--json" in p.opts for p in cmd.params), verb
  ```
- [ ] **Step 4: Write the fixture files** under `tests/fixtures/top/`, `tests/fixtures/api/`, `tests/fixtures/users/` matching the queries asserted above (synthetic data only: `ada@example.com`, `Ada Example`, ids `00000000-0000-0000-0000-00000000000a`).
- [ ] **Step 5: Run, expect failure.** `uv run pytest tests/test_cli_root.py tests/test_cli_top.py tests/test_cli_api.py tests/test_resolve.py tests/test_graph_users.py tests/test_surface.py -q` → import errors (`build_app`, `resolve`, `graph.users` missing).
- [ ] **Step 6: Implement `resolve.py`** (§6.6 id-shape rules): `GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")`; `WELL_KNOWN_FOLDERS = {"inbox","drafts","sentitems","deleteditems","junkemail","archive","outbox","clutter","conversationhistory","msgfolderroot"}`; `split_id_prefix`; `looks_like_id(value, kind)` implementing the table (`mail_folder`: lower-cased value in `WELL_KNOWN_FOLDERS` or `len ≥ 40 and " " not in value`; `team`/`group`: GUID; `channel`/`chat`: `startswith("19:")`; `user`: GUID or `"@" in value` or `value == "me"`; `site`: `startswith(("https://","http://"))` or `":/" in value` or `"," in value`; `drive`: `startswith("b!")`; `drive_item`: `id:` prefix or `re.fullmatch(r"[A-Za-z0-9!]{20,}", value) and "." not in value`; `onenote`: `"!" in value or re.match(r"^\d-", value)`; `planner`: `re.fullmatch(r"[A-Za-z0-9_-]{28}", value)`; `todo_list`: `startswith(("AQMk","AAMk")) or len ≥ 40`; `calendar`: `len ≥ 40 and " " not in value`; unknown kind → `ValueError`); `pick_unique(candidates, key, needle, *, what)` = case-insensitive exact match on `key(c)` or `c.get(key)`; 0 → `NotFoundError("NOT_FOUND", f"{what} {needle!r} not found")`; > 1 → `AmbiguousError("AMBIGUOUS", f"{what} {needle!r} matches {n} items", candidates=[(c.get("id",""), name) ...])`.
- [ ] **Step 7: Implement `graph/__init__.py`** (docstring only) **and `graph/users.py`** per the contract: `ME_SELECT` = the §8.1 `me` list; `USER_SELECT` = the §8.5 `user` list; `USERS_SEARCH_SELECT` = the §8.5 `users` list; `search_users` sends `params={"$search": f'"displayName:{q}" OR "mail:{q}"', "$count": True, "$top" via page_size=100, "$select": USERS_SEARCH_SELECT}` with `headers={"ConsistencyLevel": "eventual"}`, `cap=999`; `list_unified_groups` paginates `/me/memberOf/microsoft.graph.group` with `$filter=groupTypes/any(c:c eq 'Unified')`, `$count=true`, `$select=id,displayName`, `page_size=999`, `all_=True`, `cap=999`, same header, returns `.items`; `resolve_user(client, value, *, can_search)`: `looks_like_id(value, "user")` → `get_user`; elif `can_search` → `pick_unique(search_users(client, value, limit=50, all_=False).items, "displayName", value, what="user")`; else `UsageError("USAGE", f"{value!r} is not a UPN or id; directory search needs User.ReadBasic.All (login --scopes extended)")`.
- [ ] **Step 8: Implement `cli.py`** (spec §6.1, §6.5, §7.1, §4.4). Key code:
  ```python
  log = logging.getLogger("mgraphctl")
  F = TypeVar("F", bound=Callable[..., Any])


  class MsgraphGroup(typer.core.TyperGroup):
      """Maps MsgraphError → stderr block + exit code and flushes the token cache (spec §6.5)."""

      def invoke(self, ctx):
          try:
              return super().invoke(ctx)
          except MsgraphError as exc:
              sys.stdout.flush()
              sys.stderr.write(format_error(exc))
              ctx.exit(exc.exit_code)
          finally:
              auth.save_cache()


  def _noargs_help(ctx: typer.Context) -> None:
      if ctx.invoked_subcommand is None:
          typer.echo(ctx.get_help())
          raise typer.Exit(0)


  def make_noun_app(help: str) -> typer.Typer:
      return typer.Typer(help=help, invoke_without_command=True, callback=_noargs_help, add_completion=False,
                         rich_markup_mode=None, pretty_exceptions_enable=False)


  def open_client(g: Globals, scopes: list[str]) -> GraphClient:
      token = auth.get_access_token(False)
      auth.require_scopes(token, scopes)
      return GraphClient(auth.get_access_token, tz=g.tz, beta=g.beta, debug=g.debug,
                         transport=fixtures.transport_from_env(config.settings()))


  def gate(scopes: list[str]) -> None:
      auth.require_scopes(auth.get_access_token(False), scopes)


  def graph_command(*, scopes: list[str]) -> Callable[[F], F]:
      auth.DECLARED_SCOPES.update(s for entry in scopes for s in entry.split("|"))

      def decorate(fn: F) -> F:
          sig = inspect.signature(fn)
          params = [p for p in sig.parameters.values() if p.name != "client"]
          ctx_param = inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=typer.Context)

          @functools.wraps(fn)
          def wrapper(ctx: typer.Context, **kwargs):
              g: Globals = ctx.find_root().obj
              with open_client(g, scopes) as client:
                  result = fn(client, **kwargs)
              if result is not None:
                  render.emit(result, json_mode=bool(kwargs.get("json_", False)))

          wrapper.__signature__ = sig.replace(parameters=[ctx_param, *params])          # typer reads this
          wrapper.__annotations__ = {k: v for k, v in fn.__annotations__.items() if k != "client"} | {"ctx": typer.Context}
          wrapper.__graph_scopes__ = list(scopes)
          return wrapper  # type: ignore[return-value]

      return decorate


  def page_bounds(limit: int | None, all_: bool, *, default: int) -> tuple[int, bool]:
      if all_ and limit is not None:
          raise UsageError("USAGE", "--all and --limit are mutually exclusive")
      return (limit if limit is not None else default), all_


  def build_app() -> typer.Typer:
      root = typer.Typer(cls=MsgraphGroup, invoke_without_command=True, add_completion=False, rich_markup_mode=None,
                         pretty_exceptions_enable=False, help="Microsoft Graph from the command line.")

      @root.callback()
      def _root(ctx: typer.Context,
                debug: Annotated[int, typer.Option("--debug", count=True, help="Log requests to stderr (-dd adds bodies).")] = 0,
                tz: Annotated[str | None, typer.Option("--tz", envvar="MGRAPHCTL_TZ", help="IANA time zone.")] = None,
                beta: Annotated[bool, typer.Option("--beta", help="Use the /beta endpoint.")] = False,
                version: Annotated[bool, typer.Option("--version", callback=_version_cb, is_eager=True)] = False) -> None:
          zone = tz or render.local_tz()
          if not render.is_iana(zone):
              raise UsageError("USAGE", f"unknown time zone {zone!r}; use an IANA name such as Europe/Warsaw")
          level = max(debug, config.settings().debug)
          if level:
              logging.basicConfig(stream=sys.stderr, level=logging.DEBUG, format="DEBUG %(message)s", force=True)
              logging.getLogger("msal").setLevel(logging.INFO)
          ctx.obj = Globals(debug=level, tz=zone, beta=beta)
          _noargs_help(ctx)

      from mgraphctl.commands import api, register_all, top
      top.register(root)
      api.register(root)
      register_all(root)
      return root


  def main() -> None:
      build_app()(prog_name="mgraphctl")
  ```
  Notes: do **not** use `from __future__ import annotations` in `cli.py` or any `commands/*.py` (typer must see real `Annotated` objects); `_version_cb` prints `mgraphctl <__version__>` and exits 0; `UsageError` raised inside the root callback still reaches `MsgraphGroup.invoke` because Click runs the group callback inside `invoke`; `GraphClient` gains `__enter__/__exit__` in T3 so `with open_client(...)` closes the httpx clients.
- [ ] **Step 9: Implement `commands/__init__.py`** (`Noun`, `NOUNS`, `register_all` exactly as described in the task header; import errors other than the module itself missing — `exc.name != noun.module` — must propagate).
- [ ] **Step 10: Implement `commands/top.py`** (spec §4.2, §4.3, §4.6, §8.1). `register(root)` adds `login`, `logout`, `status`, `claims`, `me`, `version` with `root.command(name)`. `login(scopes: Option("--scopes")="", scope: list[str] Option("--scope"), force, device_code, json_)`: `name, wanted = config.resolve_scopes(scopes or None, scope)` (env `MGRAPHCTL_SCOPES` applies when `--scopes` absent: pass `scopes or os.environ.get("MGRAPHCTL_SCOPES")`); unless `force`, try `auth.acquire_silent()`; on success, if every `wanted` scope (minus reserved) is already in `expand_scopes(decode_jwt(token)["scp"])` print the already-logged-in lines and exit 0, else fall through; call `auth.login_device_code(wanted)` or `auth.login_interactive(wanted, force=force)`; then `GET /me?$select=id,displayName,userPrincipalName` through `open_client(g, [])`; emit `TextResult` / JSON `{"account": upn, "displayName", "userId", "scopes": wanted, "scopeSet": name, "cache": str(settings().token_cache)}`. `status`: `acquire_silent()` → `claims = decode_jwt(token)`; text lines `Logged in as: <account_upn() or claims upn>`, `Token expires: <fmt of exp in tz with seconds>`, `Scopes: <scope_set> (<n>)`, `Cache: <path>`; JSON `{"loggedIn": True, "account", "expiresAt", "scopeSet", "scopes", "cache"}`; on `AuthError`: in JSON mode first write `{"loggedIn": False, "account": None, "expiresAt": None, "scopeSet", "scopes", "cache"}` to stdout, then re-raise (exit 3, error on stderr). `claims`: `auth.cached_access_token()` or `AuthError("NOT_LOGGED_IN", "no cached token", hint=HINTS["NOT_LOGGED_IN"])`; text sections `IDENTITY` (`upn`/`unique_name`, `oid`, `tid`, `iat`, `exp` + `expires in Nm` or `EXPIRED`), `DEVICE` (`deviceid` present/absent + `Conditional Access policies that require a compliant device will fail without it`, `join_type`), `AUTH METHODS` (`amr`), `SCOPES` (sorted, one per line); JSON = payload. `me` (`@graph_command(scopes=["User.Read"])`, `--photo PATH`): `users.get_me(client)` → `ObjectResult` with fields `Name/UPN/Mail/Title/Department/Office/Phones/Mobile/Language/Id`; `--photo` → `client.download("/me/photo/$value", Path(photo))` → `FileResult(message=f"Downloaded photo ({fmt_size(n)}) to {path}")`. `version`: `importlib.metadata.version` for `msal`/`httpx`, `platform.python_version()`.
- [ ] **Step 11: Implement `commands/api.py`** (spec §8.17): `register(root)`; `api(method: Argument, path: Argument, query: list[str] Option("--query"), body: Option("--body"), header: list[str] Option("--header"), beta: Option("--beta"), all_: AllFlag, raw, output, outlook_tz: Option("--outlook-tz", hidden=True), dry_run, json_)` decorated `@graph_command(scopes=[])` (empty → gate skipped); `--query k=v` split on the first `=` (missing `=` → `UsageError`); `--header k:v` on the first `:`; `--body` = JSON text or `@FILE`; `--all` → `client.paginate(path, params=..., limit=None, all_=True, cap=sys.maxsize, page_size=None)` and output `{"value": items}`; `--raw` → `expect="bytes"` written to `--output` or `sys.stdout.buffer`; otherwise `expect="response"` → JSON body printed pretty if `content-type` is JSON else text; `--dry-run` → `DryRunResult([PlannedRequest(method, client.url(with_query(path, params), beta=beta), headers, body)])`.
- [ ] **Step 12: Create the replay corpus** (`tests/fixtures/replay/`): run from `$SCRIPTS`
  ```bash
  uv run python - <<'EOF'
  import json
  from pathlib import Path
  from mgraphctl import fixtures
  key = ("GET /v1.0/me?$select=id%2CdisplayName%2CuserPrincipalName%2Cmail%2CjobTitle%2Cdepartment"
         "%2CofficeLocation%2CbusinessPhones%2CmobilePhone%2CpreferredLanguage")
  d = Path("tests/fixtures/replay"); d.mkdir(parents=True, exist_ok=True)
  body = {"id": "00000000-0000-0000-0000-000000000001", "displayName": "Fixture User",
          "userPrincipalName": "fixture-user@example.com", "mail": "fixture-user@example.com", "jobTitle": "Engineer",
          "department": "R&D", "officeLocation": "Remote", "businessPhones": [], "mobilePhone": None,
          "preferredLanguage": "en-US"}
  fixtures.fixture_path(d, key).write_text(json.dumps({"key": key, "responses": [
      {"status": 200, "headers": {"content-type": "application/json"}, "body": body}]}, indent=2) + "\n")
  print(fixtures.fixture_path(d, key))
  EOF
  ```
  This is the one committed replay corpus (hand-authored, synthetic; it is an exception to §11's "no corpus committed" so the shim can be smoke-tested offline in T20).
- [ ] **Step 13: Run, expect pass.** `uv run pytest -q` (whole suite).
- [ ] **Step 14: Lint.**
- [ ] **Step 15: Commit.** `git add plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/cli.py plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/resolve.py plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/commands plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/graph/__init__.py plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/graph/users.py plugins/mgraphctl/skills/mgraphctl/scripts/tests && git commit -m "feat(mgraphctl): add cli core, noun registry, users graph and top-level commands"`.

### Task 7: `graph/files.py`   (Phase 0, parallel group P0-C with T6, depends on: T3, T5)

**Files:** Create `src/mgraphctl/graph/files.py`, `tests/test_graph_files.py`. (If T6 has not yet created `graph/__init__.py`, create it here with the same one-line docstring; git merges identical content.)
**Interfaces:** Consumes `GraphClient`, `PageResult`, `Plan`, `PlannedRequest`, `DownloadResult`, `odata.p/drive_path/with_query/share_id`, `render.Column/fmt_dt/fmt_size`, `errors.UsageError`, `config.DRIVE_SIMPLE_UPLOAD/CHUNK_DRIVE`. Produces the `graph/files.py` contract block (spec §8.11 rows `ls get download upload mkdir move rename delete share link`, shared by §8.12 `ls download upload`).

- [ ] **Step 1: Write failing tests `tests/test_graph_files.py`** (respx against a `GraphClient(lambda f: "tok", tz="Europe/Warsaw")`; `V1 = "https://graph.microsoft.com/v1.0"`), one test each: `test_children_path_forms` (`children_path("/me/drive", None) == "/me/drive/root/children"`, `children_path("/drives/b!x", "Docs/Q3 plan") == "/drives/b!x/root:/Docs/Q3%20plan:/children"`); `test_item_ref_forms` (`item_ref(base, "01ABCDEFGHIJKLMNOPQRSTUV") == base + "/items/01ABCDEFGHIJKLMNOPQRSTUV"`, `item_ref(base, "id:abc") == base + "/items/abc"`, `item_ref(base, "/Docs/a.txt") == base + "/root:/Docs/a.txt"`, `item_ref(base, "Docs/a.txt")` same); `test_list_children_query` (`$top=200`, `$select=id,name,size,lastModifiedDateTime,file,folder,webUrl,parentReference`, `$orderby=name`; `limit=50`, cap 1000); `test_search_items_own_and_shared` (`/me/drive/root/search(q='O''Brien')` vs `/me/drive/search(q='x')`); `test_get_item_by_path_and_id`; `test_resolve_item_id_by_path_fetches_item`; `test_download_item_uses_content_and_item_name` (`GET .../items/x` for metadata → `GET .../items/x/content` → 302 → bytes; `dest=None` → `<cwd>/<name>`; returns `(item, DownloadResult)`); `test_plan_upload_small_put` (3 MiB file → one `PUT {base}/root:/Docs/f.bin:/content?@microsoft.graph.conflictBehavior=replace` with `file=` set and `Content-Type: application/octet-stream`); `test_plan_upload_large_session` (5 MiB file → one step `POST {base}/root:/Docs/f.bin:/createUploadSession` body `{"item": {"@microsoft.graph.conflictBehavior": "rename", "name": "f.bin"}}`, `chunk_size == 10_485_760`); `test_dest_rules` (`dest=None` → `/<basename>`; `dest="Docs/"` → `Docs/<basename>`; `dest="Docs/new.bin"` → as given); `test_run_upload_small_and_large` (small → PUT returns item; large → session + chunk PUTs through `upload_session`); `test_mkdir_plan` (`POST {base}/root:/Docs:/children {"name": "New", "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}`; root parent → `{base}/root/children`); `test_move_resolves_folder` (`to="Archive"` → `GET {base}/root:/Archive` for its id → `PATCH {base}/items/x {"parentReference": {"id": "fid"}, "name": "n"}`; `to="id:fid"` skips the GET); `test_rename_delete_share_plans` (`PATCH {"name"}`; `DELETE`; `POST .../createLink {"type": "view", "scope": "organization"}` + `expirationDateTime` when given); `test_shared_item_by_link` (`GET /shares/u!.../driveItem`; download → `.../driveItem/content`); `test_item_columns_render` (`d`/`f` type marker, size via `fmt_size`, modified via `fmt_dt`).
- [ ] **Step 2: Run, expect failure.** `uv run pytest tests/test_graph_files.py -q`.
- [ ] **Step 3: Implement `graph/files.py`** per the contract: `ITEM_SELECT = "id,name,size,lastModifiedDateTime,file,folder,webUrl,parentReference"`, `PAGE_LS, CAP_LS = 200, 1000`; `item_ref(base, ref)`: `split_id_prefix` → `id:` forces `/items/{p(id)}`; `resolve.looks_like_id(ref, "drive_item")` → `/items/{id}`; else `f"{base}/root:/{odata.drive_path(ref.lstrip('/'))}"`; `children_path`; `list_children` → `paginate(children_path(...), params={"$select": ITEM_SELECT, "$orderby": "name"}, page_size=200, cap=1000)`; `search_items` → `paginate(f"{base}/root/search(q='{odata.odata_str(q)}')" or f"{base}/search(q='…')", params={"$select": ITEM_SELECT}, page_size=200, cap=1000, limit)`; `get_item` → `client.get(item_ref(base, ref) + ("" if id form else "") , params={"$select": ITEM_SELECT})` (path form: `f"{base}/root:/{p}"` with `$select`); `resolve_item_id` → id form returns the id, path form fetches `get_item()["id"]`; `download_item` → `get_item` then `client.download(item_ref(...) + ("/content" if id form else ":/content"), dest or Path(item["name"]))`; `plan_upload(client, base, file, dest, conflict)`: `dest_path = _dest(file, dest)`; `size = file.stat().st_size`; `< DRIVE_SIMPLE_UPLOAD` → `[PlannedRequest("PUT", client.url(f"{base}/root:/{drive_path(dest_path)}:/content?@microsoft.graph.conflictBehavior={conflict}"), {"Content-Type": mimetype or "application/octet-stream"}, None, file=file)]`; else `[PlannedRequest("POST", client.url(f"{base}/root:/{drive_path(dest_path)}:/createUploadSession"), {"Content-Type": "application/json"}, {"item": {"@microsoft.graph.conflictBehavior": conflict, "name": dest_path.rsplit("/", 1)[-1]}}, file=file, chunk_size=config.CHUNK_DRIVE, note=f"upload {size} bytes in {ceil(size / CHUNK_DRIVE)} chunks")]`; `run_upload` → `client.execute(plan[0])`; `plan_mkdir` (parent = everything before the last `/`, root → `{base}/root/children`); `plan_move` (folder id via `get_item` unless `id:`), `plan_rename`, `plan_delete` (`expect="none"`), `plan_share` (`expirationDateTime = to_iso_offset(expires)` when given); every `run_*` = `client.execute(...)` of each step in order, returning the last body; `get_shared_item` → `client.get(f"/shares/{odata.share_id(url)}/driveItem")`; `download_shared_item` → `client.download(f"/shares/{share_id}/driveItem/content", dest or Path(item["name"]))`; `item_columns(tz)` → `[Column("type", lambda i: "d" if "folder" in i else "f"), Column("id", "id"), Column("size", lambda i: fmt_size(i.get("size"))), Column("modified", lambda i: fmt_dt(i.get("lastModifiedDateTime"), tz)), Column("name", "name")]`.
- [ ] **Step 4: Run, expect pass.** `uv run pytest tests/test_graph_files.py -q`.
- [ ] **Step 5: Lint.**
- [ ] **Step 6: Commit.** `git add plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/graph/__init__.py plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/graph/files.py plugins/mgraphctl/skills/mgraphctl/scripts/tests/test_graph_files.py && git commit -m "feat(mgraphctl): add shared drive-item operations"`.

## Phase 1 — nouns (fully parallel; each task depends only on Phase 0 unless stated)

Rules for every Phase 1 task: create only the files listed for the group; expose `app = make_noun_app(...)` (or `command` for J) in `commands/<noun>.py`; never edit `cli.py`, `commands/__init__.py`, `conftest.py`, `helpers.py` or any Phase 0 module; cross-group imports are limited to `mgraphctl.graph.users` (Phase 0), `mgraphctl.graph.files` (Phase 0, F and G only) and `mgraphctl.graph.chats.shape_chat_hit` (D → J); use the shared patterns (a)–(e) verbatim; read the spec rows cited before each cluster plus §5.3 (paging table, lines 225–242), §6.3 (lines 311–317), §6.4 (319–330), §6.6 (352–371). Every list verb takes its default `--limit`, page size and cap from §5.3. Every cluster ends with `uv run ruff check src tests && uv run ruff format src tests` and its own commit. After the last cluster run `uv run pytest -q` (whole suite, including `test_surface.py`) and confirm `invoke("<noun>")` prints help with exit 0.

**Acceptance list (identical for every group):** every verb of the group has ≥ 1 `@covers` test asserting exit 0, the exact request (method, path, decoded query, relevant headers, JSON body) and the stdout shape; every write verb has a `--dry-run` test asserting the plan JSON and `graph.calls.call_count == 0`; `--json` output tested for one list verb (envelope keys, count) and one single-object verb (raw Graph object); one P2 verb tested with `@pytest.mark.scopes([...])` lacking its scope → exit 3 `error[MISSING_SCOPE]` and no request; exit-code cases 404 → 4, 403 → 3, 401-after-refresh → 3, 400 → 1 for one read verb; `--limit 0` → 2 for one list verb; `invoke("<noun>")` → help, exit 0; `test_surface.py` passes; ruff clean; fixtures synthetic.

### Task 8: Group A — `mail` + `mailbox`   (Phase 1, parallel group P1, depends on: T6)

**Files:** Create `graph/mail.py`, `graph/mailbox.py`, `commands/mail.py`, `commands/mailbox.py`, `tests/test_cli_mail.py`, `tests/test_cli_mailbox.py`, `tests/fixtures/mail/*.json`, `tests/fixtures/mailbox/*.json`.
**Interfaces:** Consumes the Phase 0 contract. Produces (used only inside this group): `graph.mail.resolve_folder(client, value) -> str | None`, `list_messages(...)` (pattern b), `get_message(client, id, *, headers: bool, html: bool, tz) -> dict`, `list_attachments(client, id) -> list[dict]`, `download_attachment(client, id, aid, dest) -> DownloadResult`, `SendParams` dataclass, `needs_draft_path(p) -> bool`, `plan_send(client, p) -> Plan`, `run_send(client, p) -> dict`, `plan_reply/plan_forward`, `list_folders(client, *, depth, hidden) -> list[dict]` (nested `children`), `plan_mark(client, ids, patch) -> Plan`, `run_mark(client, ids, patch) -> list[dict]` (`$batch` when > 1), `plan_move/plan_delete`, `list_drafts`, `plan_create_draft/run_create_draft`, `plan_send_draft`, `list_rules`, `list_categories`, `flags(m) -> str`, `read_body(body, body_file)`; `graph.mailbox.get_settings`, `get_oof`, `plan_set_oof(client, ...)`, `list_focused(client, *, other, after, limit, all_, tz)` (calls `mail.list_messages` internals: same `$select`, filter `receivedDateTime ge {after} and inferenceClassification eq 'focused'|'other'`).

Verbs (spec §8.2 lines 431–449, §8.3 lines 451–458):

| Verb | Tier | Line | Scopes | W |
|---|---|---|---|---|
| `mail list` | P0 | 435 | `Mail.Read` | |
| `mail read ID` | P0 | 436 | `Mail.Read` | |
| `mail attachments ID` | P0 | 437 | `Mail.Read` | |
| `mail send` | P0 (draft path P2) | 438 | `Mail.Send`; draft path `gate(["Mail.ReadWrite"])` | W |
| `mail reply ID` | P1 | 439 | `Mail.Send` | W |
| `mail forward ID` | P1 | 440 | `Mail.Send` | W |
| `mail folders` | P1 | 441 | `Mail.Read` | |
| `mail mark ID...` | P2 | 442 | `Mail.ReadWrite` | W |
| `mail move ID` | P2 | 443 | `Mail.ReadWrite` | W |
| `mail delete ID` | P2 | 444 | `Mail.ReadWrite` | W |
| `mail drafts list` | P1 | 445 | `Mail.Read` | |
| `mail drafts create` | P2 | 446 | `Mail.ReadWrite` | W |
| `mail drafts send ID` | P2 | 447 | `Mail.ReadWrite`, `Mail.Send` | W |
| `mail rules list` | P2 | 448 | `MailboxSettings.Read` | |
| `mail categories` | P2 | 449 | `MailboxSettings.Read` | |
| `mailbox settings` | P2 | 455 | `MailboxSettings.Read` | |
| `mailbox oof get` | P2 | 456 | `MailboxSettings.Read` | |
| `mailbox oof set` | P2 | 457 | `MailboxSettings.ReadWrite` | W |
| `mailbox focused` | P1 | 458 | `Mail.Read` | |

Resolution (§6.6 line 358): `--folder all` → whole mailbox (`/me/messages`); well-known name (case-insensitive) or `looks_like_id(v, "mail_folder")` → used as is; otherwise exact `displayName` among `GET /me/mailFolders?$top=200` then each folder's `childFolders` (one level), via `pick_unique(..., what="mail folder")`.

- [ ] **Cluster A1: `mail list`, `mail read`, `mail attachments`, `mail folders`, `mail drafts list`** (read verbs).
  1. Write `tests/test_cli_mail.py` starting with pattern (c) tests plus: `test_mail_list_search_mode_and_unread_client_side` (`--search "budget" --from ada@example.com --after 2026-08-01 --unread` → `$search` equals `"budget AND from:ada@example.com AND received>=2026-08-01"`, `$top=25`, no `$orderby`/`$filter`; a read message in the response is dropped from output); `test_mail_list_filter_mode_dates_and_unread` (`--after 2026-08-01 --before 2026-08-31 --unread` → `$filter` equals `receivedDateTime ge 2026-08-01T00:00:00+02:00 and receivedDateTime le 2026-08-31T23:59:59+02:00 and isRead eq false`, `$orderby=receivedDateTime desc`, `$top=50`); `test_mail_list_folder_all_uses_me_messages`; `test_mail_list_folder_by_name_resolves_child` (fixture `mail/folders_resolve.json`: `GET /v1.0/me/mailFolders?$top=200` → two folders, one with `childFolderCount: 1` → `GET .../mailFolders/<id>/childFolders` → `Projects` found → messages fetched from `/me/mailFolders/<childId>/messages`); `test_mail_list_folder_ambiguous_exit_2` and `test_mail_list_folder_missing_exit_4`; `test_mail_list_select_override`; `test_mail_list_all_hits_cap_note` (`--all` with `nextLink` forever and 600 items → stderr `(hit the 500-item cap — narrow the query)`, `truncated: true`); `test_mail_read_text_body_prefers_text_and_truncates` (`Prefer` contains `outlook.body-content-type="text"` and `outlook.timezone=...`; `$select` ends with `,body,uniqueBody,replyTo`; a 5000-char body prints 4000 chars + stderr `(body truncated to 4000 chars; use --full)`; `--full` prints all); `test_mail_read_html_flag_and_markdown_fallback` (`--html` → no text Prefer, body printed raw; without `--html` but `body.contentType == "html"` → Markdown); `test_mail_read_headers` (`--headers` → `$select` includes `internetMessageHeaders`, text shows a `Headers` section); `test_mail_read_output_writes_full_body`; `test_mail_read_save_attachments` (fixture `mail/read_attachments.json`: message, attachments list with one `#microsoft.graph.fileAttachment` and one `#microsoft.graph.itemAttachment`, `$value` bytes → file saved as `<dir>/<name>`, stderr note `skipped <name>: itemAttachment cannot be downloaded`); `test_mail_read_json_is_raw_object`; pattern (e) exit-code tests for `mail read`; `test_mail_attachments_list_and_download` (`$select=id,name,contentType,size,isInline`; text columns `id type name size inline`; `--download <aid> --output f` → `GET .../attachments/<aid>/$value`, `Downloaded plan.docx (12 B) to f`); `test_mail_attachments_download_item_attachment_exit_1`; `test_mail_attachments_all_output_dir`; `test_mail_folders_tree_depth_and_hidden` (`$top=100`, `$select=id,displayName,parentFolderId,childFolderCount,unreadItemCount,totalItemCount`; `--hidden` adds `includeHiddenFolders=true`; `--depth 2` fetches `childFolders` for `childFolderCount > 0` twice at most; text indents children by two spaces; JSON nests `children`); `test_mail_drafts_list` (`GET /v1.0/me/mailFolders/drafts/messages` with `$orderby=lastModifiedDateTime desc`, `$top=50`, default limit 20).
  2. `uv run pytest tests/test_cli_mail.py -q` → `ModuleNotFoundError: mgraphctl.graph.mail`.
  3. Implement `graph/mail.py` (list/read/attachments/folders/drafts-list functions, `resolve_folder`, `flags(m)` = `("*" if not isRead) + ("A" if hasAttachments) + ("!" if importance == "high")`) and `commands/mail.py` (`app`, `drafts`, `rules` sub-apps; `list_`, `read`, `attachments`, `folders`, `drafts_list`). `read`: `ObjectResult(fields=[("Subject",…),("From",…),("To",…),("Cc",…),("Received",…),("Id","id"),("Web link","webLink")], body=<text>)`; `--output` writes the untruncated body and prints `Wrote <n> chars to <path>`.
  4. `uv run pytest tests/test_cli_mail.py -q` → pass. 5. Lint. 6. `git add plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/graph/mail.py plugins/mgraphctl/skills/mgraphctl/scripts/src/mgraphctl/commands/mail.py plugins/mgraphctl/skills/mgraphctl/scripts/tests/test_cli_mail.py plugins/mgraphctl/skills/mgraphctl/scripts/tests/fixtures/mail && git commit -m "feat(mgraphctl): add mail list, read, attachments, folders and drafts list"`.
- [ ] **Cluster A2: `mail send`, `mail reply`, `mail forward`, `mail drafts create`, `mail drafts send`.** Full test for the send paths:
  ```python
  @covers("mail send")
  def test_mail_send_inline_path(invoke, graph, tmp_path):
      f = tmp_path / "a.txt"; f.write_bytes(b"hello")
      route = graph.post(f"{GRAPH}/v1.0/me/sendMail").mock(return_value=httpx.Response(202))
      r = invoke("mail", "send", "--to", "ada@example.com,bob@example.com", "--cc", "eve@example.com", "--subject", "Hi",
                 "--body", "Body", "--attach", str(f), "--importance", "high", "--json")
      assert r.exit_code == 0 and json.loads(r.stdout) == {"status": "sent"}
      body = json.loads(route.calls.last.request.content)
      msg = body["message"]
      assert body["saveToSentItems"] is True and msg["subject"] == "Hi" and msg["importance"] == "high"
      assert msg["body"] == {"contentType": "Text", "content": "Body"}
      assert [r["emailAddress"]["address"] for r in msg["toRecipients"]] == ["ada@example.com", "bob@example.com"]
      assert msg["attachments"] == [{"@odata.type": "#microsoft.graph.fileAttachment", "name": "a.txt",
                                     "contentType": "text/plain", "contentBytes": "aGVsbG8="}]


  @covers("mail send")
  def test_mail_send_draft_path_dry_run_names_steps(invoke, graph, tmp_path):
      big = tmp_path / "big.bin"; big.write_bytes(b"\0" * 3_000_000)
      r = invoke("mail", "send", "--to", "ada@example.com", "--subject", "Big", "--body", "x", "--attach", str(big), "--dry-run", "--json")
      doc = json.loads(r.stdout)
      assert [s["method"] for s in doc["requests"]] == ["POST", "POST", "POST"]
      assert doc["requests"][0]["url"] == f"{GRAPH}/v1.0/me/messages" and "draft path" in doc["requests"][0]["note"]
      assert doc["requests"][1]["url"] == f"{GRAPH}/v1.0/me/messages/{{draftId}}/attachments"
      assert doc["requests"][1]["body"]["contentBytes"] == {"$file": str(big), "bytes": 3_000_000, "contentType": "application/octet-stream"}
      assert doc["requests"][2]["url"] == f"{GRAPH}/v1.0/me/messages/{{draftId}}/send"
      assert graph.calls.call_count == 0


  @covers("mail send")
  def test_mail_send_draft_path_large_attachment_upload_session(invoke, graph, tmp_path):
      huge = tmp_path / "huge.bin"; huge.write_bytes(b"\1" * 4_000_000)
      graph.post(f"{GRAPH}/v1.0/me/messages").mock(return_value=httpx.Response(201, json={"id": "AAMk-draft-1"}))
      graph.post(f"{GRAPH}/v1.0/me/messages/AAMk-draft-1/attachments/createUploadSession").mock(
          return_value=httpx.Response(201, json={"uploadUrl": "https://upload.example.com/session?tok=1", "nextExpectedRanges": ["0-"]}))
      put = graph.put("https://upload.example.com/session").mock(side_effect=[
          httpx.Response(200, json={"nextExpectedRanges": ["3932160-"]}), httpx.Response(201, headers={"Location": "https://graph.microsoft.com/v1.0/me/messages/AAMk-draft-1/attachments/x"})])
      send = graph.post(f"{GRAPH}/v1.0/me/messages/AAMk-draft-1/send").mock(return_value=httpx.Response(202))
      r = invoke("mail", "send", "--to", "ada@example.com", "--subject", "Huge", "--body", "x", "--attach", str(huge), "--json")
      assert r.exit_code == 0, r.stderr
      assert json.loads(r.stdout) == {"status": "sent", "draftId": "AAMk-draft-1"}
      assert [c.request.headers["Content-Range"] for c in put.calls] == ["bytes 0-3932159/4000000", "bytes 3932160-3999999/4000000"]
      assert "Authorization" not in put.calls[0].request.headers and send.called


  @covers("mail send")
  @pytest.mark.scopes(["Mail.Send", "Mail.Read"])
  def test_mail_send_draft_path_needs_mail_readwrite(invoke, graph, tmp_path):
      big = tmp_path / "big.bin"; big.write_bytes(b"\0" * 3_000_000)
      r = invoke("mail", "send", "--to", "ada@example.com", "--subject", "Big", "--body", "x", "--attach", str(big))
      assert r.exit_code == 3 and "needs Mail.ReadWrite" in r.stderr and graph.calls.call_count == 0
  ```
  Also: `test_mail_send_requires_to_and_body` (missing `--to` → exit 2; both `--body` and `--body-file` → 2; `--body-file -` reads stdin via `input=`); `test_mail_send_html_and_no_save` (`--html` → `contentType: "HTML"`; `--no-save-to-sent` → `saveToSentItems: false`); `test_mail_send_default_subject_no_subject` (`(no subject)`); `test_mail_send_attachment_over_150mb_exit_2` (monkeypatch `Path.stat` size); `test_mail_reply_*` (pattern d; `--reply-all` → `/replyAll`; `--html` → `{"message": {"body": {"contentType": "HTML", ...}}}`; `--to x` adds `message.toRecipients`); `test_mail_forward` (`{"toRecipients": [...], "comment": "..."}`); `test_mail_drafts_create_returns_draft` (`POST /me/messages` body has `subject/body/toRecipients`, no `saveToSentItems`; JSON = returned draft; attachments as in `send`); `test_mail_drafts_send` (`POST /me/messages/<id>/send` → `{"status": "sent"}`) plus dry-run tests for reply, forward, drafts create, drafts send.
  Implement: `SendParams`, `needs_draft_path(p) = sum(sizes) > config.MAIL_INLINE_TOTAL`, `build_message(p, *, for_plan)` (inline attachments as `fileAttachment` with base64 `contentBytes`, or the `$file` dict when `for_plan`), `plan_send`: inline → `[PlannedRequest("POST", url("/me/sendMail"), JSON, {"message": ..., "saveToSentItems": p.save_to_sent}, note="inline path: attachments total <= 2.5 MiB", expect="none")]`; draft → step 1 `POST /me/messages` (note `draft path: attachments total > 2.5 MiB`), then per attachment `< MAIL_SMALL_ATTACHMENT` → `POST /me/messages/{draftId}/attachments` with `fileAttachment` (`contentBytes` `$file` dict in the plan), `≥` → `POST /me/messages/{draftId}/attachments/createUploadSession` `{"AttachmentItem": {"attachmentType": "file", "name", "size"}}` with `file=`, `chunk_size=config.CHUNK_OUTLOOK`, then `POST /me/messages/{draftId}/send` (`expect="none"`); `run_send`: inline → execute; draft → `gate` is the command's job (call `gate(["Mail.ReadWrite"])` in the command when `needs_draft_path` and not `dry_run`), create draft, thread `draft["id"]` into the real URLs, execute each, return `{"status": "sent", "draftId": id}`; MIME via `mimetypes.guess_type`; `--attach` > 157 286 400 bytes → `UsageError`. Commit `feat(mgraphctl): add mail send, reply, forward and draft writes`.
- [ ] **Cluster A3: `mail mark`, `mail move`, `mail delete`, `mail rules list`, `mail categories`.** Tests: `test_mail_mark_single_patch_and_list_envelope` (`PATCH /me/messages/<id>` body `{"isRead": true, "flag": {"flagStatus": "flagged"}, "categories": ["Red"], "importance": "low"}`; JSON `{"items": [updated], "count": 1, "truncated": false}`); `test_mail_mark_many_uses_batch` (three ids → one `POST /v1.0/$batch` with three PATCH sub-requests carrying `Content-Type: application/json`; a sub-404 → exit 4 with `error[ErrorItemNotFound]`); `test_mail_mark_conflicting_flags_exit_2` (`--read --unread`); `test_mail_mark_dry_run`; pattern (e) `test_mail_mark_missing_scope`; `test_mail_move_returns_new_message` (`--folder Archive` → well-known → `POST .../move {"destinationId": "archive"}`; a name → resolved through `resolve_folder`; JSON = the new message; text `Moved to <folder>; new id: <id>`); `test_mail_move_dry_run`; `test_mail_delete` (`DELETE` → `{"status": "deleted", "id": ...}`) + dry-run; `test_mail_rules_list` (`GET /me/mailFolders/inbox/messageRules`; columns `id sequence enabled name actions`); `test_mail_categories` (`GET /me/outlook/masterCategories`; columns `id name color`). Implement `plan_mark/run_mark` (`$batch` via `BatchRequest(id=str(i), "PATCH", "/me/messages/<id>", body)` with `--flag-complete` → `flagStatus: "complete"`, `--unflag` → `"notFlagged"`, `--clear-categories` → `[]`; any `BatchResponse.error` → raise it), `plan_move`, `plan_delete`, `list_rules`, `list_categories`. Commit `feat(mgraphctl): add mail mark, move, delete, rules and categories`.
- [ ] **Cluster A4: `mailbox settings`, `mailbox oof get`, `mailbox oof set`, `mailbox focused`.** Tests in `tests/test_cli_mailbox.py`: `test_mailbox_settings` (`GET /me/mailboxSettings`; text shows `Time zone`, `Language`, `Working hours`, `Automatic replies`); `test_mailbox_oof_get`; `test_mailbox_oof_set_scheduled_external_contacts` (`--message "Away" --start 2026-09-10 --end 2026-09-12 --external contacts` → `PATCH /me/mailboxSettings {"automaticRepliesSetting": {"status": "scheduled", "externalAudience": "contactsOnly", "scheduledStartDateTime": {"dateTime": "2026-09-10T00:00:00", "timeZone": "Europe/Warsaw"}, "scheduledEndDateTime": {"dateTime": "2026-09-12T23:59:59", "timeZone": "Europe/Warsaw"}, "internalReplyMessage": "<p>Away</p>", "externalReplyMessage": "<p>Away</p>"}}`); `test_mailbox_oof_set_always_and_internal_only` (`alwaysEnabled`, `externalAudience: "none"`); `test_mailbox_oof_set_clear` (`{"automaticRepliesSetting": {"status": "disabled"}}`); `test_mailbox_oof_set_requires_message_unless_clear` (exit 2); dry-run test; `@pytest.mark.scopes(["Mail.Read"])` gate test on `oof set`; `test_mailbox_focused_filter` (default `--after -30d` → `$filter` equals `receivedDateTime ge <iso> and inferenceClassification eq 'focused'`, `$orderby=receivedDateTime desc`, `$top=50`, list `$select`; `--other` → `'other'`; default limit 25). Implement `graph/mailbox.py` and `commands/mailbox.py` (`oof` sub-app). Commit `feat(mgraphctl): add mailbox settings, automatic replies and focused inbox`.
- [ ] **Finish:** `uv run pytest -q`, lint, confirm `invoke("mail")`, `invoke("mail", "drafts")`, `invoke("mailbox")`, `invoke("mailbox", "oof")` print help with exit 0 (add `test_mail_group_help` / `test_mailbox_group_help`).

### Task 9: Group B — `calendar`   (Phase 1, parallel group P1, depends on: T6)

**Files:** Create `graph/calendar.py`, `commands/calendar.py`, `tests/test_cli_calendar.py`, `tests/fixtures/calendar/*.json`.
**Interfaces:** Consumes the Phase 0 contract. Produces: `graph.calendar.resolve_calendar(client, value) -> str | None`, `calendar_view(client, *, start, end, calendar_id, select, limit, all_, tz) -> PageResult`, `list_calendars`, `get_event(client, id, *, html, tz)`, `EventParams` dataclass, `event_body(p, tz, *, partial: bool) -> dict`, `plan_create(client, p, tz)`, `plan_update`, `plan_delete`, `plan_respond(client, id, action, *, comment, send, propose: tuple | None, tz)`, `get_schedule(client, *, users, start, end, interval, tz) -> dict`, `free_windows(schedule_item, start, interval) -> list[tuple[datetime, datetime]]`, `find_times(client, *, attendees, duration, start, end, max_candidates, domain, tz) -> dict`.

Verbs (spec §8.4 lines 460–472):

| Verb | Tier | Line | Scopes | W |
|---|---|---|---|---|
| `calendar list` | P0 | 464 | `Calendars.Read` | |
| `calendar calendars` | P1 | 465 | `Calendars.Read` | |
| `calendar get ID` | P1 | 466 | `Calendars.Read` | |
| `calendar create` | P0 | 467 | `Calendars.ReadWrite` | W |
| `calendar update ID` | P1 | 468 | `Calendars.ReadWrite` | W |
| `calendar delete ID` | P1 | 469 | `Calendars.ReadWrite` | W |
| `calendar respond ID accept\|decline\|tentative` | P1 | 470 | `Calendars.ReadWrite` | W |
| `calendar availability` | P0 | 471 | `Calendars.Read` | |
| `calendar find-times` | P2 | 472 | `Calendars.Read.Shared` | |

Resolution (§6.6 line 365): `--calendar` id when `looks_like_id(v, "calendar")`, else case-insensitive `name` in `/me/calendars`.

- [ ] **Cluster B1: `list`, `calendars`, `get`.** Full test:
  ```python
  @covers("calendar list")
  def test_calendar_list_window_and_columns(invoke, graph, monkeypatch):
      from mgraphctl import render
      fixed = datetime(2026, 9, 2, 9, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
      monkeypatch.setattr(render, "_now", lambda zone: fixed.astimezone(zone))
      routes = mock_graph(graph, "calendar/list")          # GET /v1.0/me/calendarView with the query below
      r = invoke("calendar", "list", "--json")
      assert r.exit_code == 0, r.stderr
      req = routes[0].calls.last.request
      assert dict(req.url.params) == {"startDateTime": "2026-09-02T09:00:00+02:00", "endDateTime": "2026-09-09T09:00:00+02:00",
          "$select": "id,subject,start,end,location,organizer,attendees,isOnlineMeeting,onlineMeeting,isCancelled,isAllDay,showAs,responseStatus,seriesMasterId,bodyPreview,webLink",
          "$orderby": "start/dateTime", "$top": "50"}
      assert req.headers["Prefer"] == 'outlook.timezone="Europe/Warsaw"'
      doc = json.loads(r.stdout); assert doc["count"] == 2 and doc["items"][0]["subject"] == "Standup"
      r = invoke("calendar", "list")
      assert r.stdout.splitlines()[0].split() == ["start", "end", "flags", "subject", "organizer", "location", "id"]
      assert "T" in r.stdout.splitlines()[1].split()[2] and "2026-09-03 (all day)" in r.stdout
  ```
  Also: `test_calendar_list_start_end_days_and_aliases` (`--start 2026-09-01 --end 2026-09-05` → `endDateTime` `2026-09-05T23:59:59+02:00`; `--days 3`; `--after/--before` accepted as aliases; `--start` with `--days` → exit 2); `test_calendar_list_search_client_side` (`--search ada` keeps events whose subject/organizer name/attendee address contains `ada`, case-insensitive); `test_calendar_list_calendar_by_name` (`GET /me/calendars` → id → `/me/calendars/<id>/calendarView`); `test_calendar_list_cancelled_marker_X`; `test_calendar_list_all_cap_200`; `test_calendar_calendars` (`$select=id,name,isDefaultCalendar,canEdit,owner,color`); `test_calendar_get_text_attendees_and_join_url` (`GET /me/events/<id>`; text has `Attendees` lines `name <addr> (accepted)` and `Join URL`; body Markdown unless `--html`); pattern (e) for `calendar get`; `--limit 0`.
  Implement `graph/calendar.py` read functions and `commands/calendar.py` `list_/calendars/get`. Commit `feat(mgraphctl): add calendar list, calendars and get`.
- [ ] **Cluster B2: `create`, `update`, `delete`, `respond`.** Tests: `test_calendar_create_full_body` (`--subject S --start 2026-09-05T14:00 --duration 45m --attendees a@example.com --optional b@example.com --body Hi --location Room --teams --reminder 10 --show-as busy --category Work --category Ops` → `POST /me/events` body `{"subject": "S", "start": {"dateTime": "2026-09-05T14:00:00", "timeZone": "Europe/Warsaw"}, "end": {"dateTime": "2026-09-05T14:45:00", ...}, "isAllDay": false, "attendees": [{"emailAddress": {"address": "a@example.com"}, "type": "required"}, {"emailAddress": {"address": "b@example.com"}, "type": "optional"}], "body": {"contentType": "Text", "content": "Hi"}, "location": {"displayName": "Room"}, "isOnlineMeeting": true, "onlineMeetingProvider": "teamsForBusiness", "reminderMinutesBeforeStart": 10, "showAs": "busy", "categories": ["Work", "Ops"], "transactionId": <uuid4>}`; JSON = returned event incl. `onlineMeeting.joinUrl`; text prints `Created <subject> <start> id: <id>` and the join URL); `test_calendar_create_all_day_defaults_end` (`--all-day --start 2026-09-05` → end `2026-09-06T00:00:00`, `isAllDay: true`); `test_calendar_create_end_and_duration_conflict_exit_2`; `test_calendar_create_calendar_option` (`/me/calendars/<id>/events`); `test_calendar_create_dry_run`; `test_calendar_update_only_given_fields` (`PATCH` body has only `subject`); `test_calendar_update_dry_run`; `test_calendar_delete` (`DELETE` → `{"status": "deleted", "id"}`) + dry-run; `test_calendar_respond_variants` (`accept` → `/accept {"comment": "ok", "sendResponse": true}` → `{"status": "accepted"}`; `decline --no-send` → `sendResponse: false`, `{"status": "declined"}`; `tentative --propose-start 2026-09-05T15:00 --propose-end 2026-09-05T15:30` → `/tentativelyAccept` with `proposedNewTime: {"start": {...}, "end": {...}}` → `{"status": "tentativelyAccepted"}`; `accept --propose-start` → exit 2) + dry-run; `@pytest.mark.scopes(["Calendars.Read"])` gate test on `create`. Implement `EventParams`, `event_body`, `plan_*`. Commit `feat(mgraphctl): add calendar create, update, delete and respond`.
- [ ] **Cluster B3: `availability`, `find-times`.** Tests: `test_calendar_availability_defaults_me` (`GET /me?$select=mail,userPrincipalName` → `POST /me/calendar/getSchedule {"schedules": ["ada@example.com"], "startTime": {"dateTime": "2026-09-02T09:00:00", "timeZone": "Europe/Warsaw"}, "endTime": {"dateTime": "2026-09-02T23:59:59", ...}, "availabilityViewInterval": 30}` with `_now` fixed at 09:07 → floored to 09:00; text per user lists `busy 2026-09-02T10:00+02:00 – 11:00 Standup`, `tentative ...`, `oof ...` blocks and `free 09:00 – 10:00` windows computed from `availabilityView`; `--json` = the raw `value` list envelope); `test_calendar_availability_users_and_interval_bounds` (`--users a@example.com --users b@example.com --interval 15`; `--interval 3` → exit 2); `test_calendar_find_times_body` (`--attendees a@example.com --duration 1h --start 2026-09-03 --end 2026-09-05 --max 3 --domain unrestricted` → `POST /me/findMeetingTimes {"attendees": [{"emailAddress": {"address": ...}, "type": "required"}], "timeConstraint": {"activityDomain": "unrestricted", "timeSlots": [{"start": {...}, "end": {...}}]}, "meetingDuration": "PT1H", "maxCandidates": 3, "returnSuggestionReasons": true}`; text lists suggestions with `confidence` and per-attendee availability, and prints `emptySuggestionsReason` when present); `@pytest.mark.scopes(["Calendars.Read"])` on `find-times` → exit 3. Implement `get_schedule`, `free_windows` (walk `availabilityView` chars: `0` free; merge consecutive free slots into windows of `interval` minutes from `start`), `find_times`. Commit `feat(mgraphctl): add calendar availability and find-times`.
- [ ] **Finish:** full suite, lint, `test_calendar_group_help`.

### Task 10: Group C — `people` + `org` + `groups`   (Phase 1, parallel group P1, depends on: T6)

**Files:** Create `graph/people.py`, `graph/org.py`, `graph/groups.py`, `commands/people.py`, `commands/org.py`, `commands/groups.py`, `tests/test_cli_people.py`, `tests/test_cli_org.py`, `tests/test_cli_groups.py`, `tests/fixtures/{people,org,groups}/*.json`.
**Interfaces:** Consumes Phase 0 incl. `graph.users.get_user/search_users/list_unified_groups/resolve_user/user_path`. Produces: `graph.people.search_people`, `list_contacts(client, *, search, limit, all_)` (400 on `$search` → fetch ≤ 250 and filter client-side on displayName/email), `get_contact`, `download_photo(client, upn, size, dest)`; `graph.org.manager(client, upn)`, `reports(client, upn, *, limit, all_)`, `chain(client, upn, *, max_levels)`; `graph.groups.list_groups(client, *, unified, limit, all_)`, `list_members(client, group_id, *, limit, all_)`, `resolve_group(client, value)`.

Verbs (spec §8.5 lines 474–483, §8.6 lines 485–491, §8.16 lines 609–614):

| Verb | Tier | Line | Scopes | W |
|---|---|---|---|---|
| `people search Q` | P0 | 478 | `People.Read` | |
| `people contacts` | P0 | 479 | `Contacts.Read` | |
| `people contact ID` | P1 | 480 | `Contacts.Read` | |
| `people users Q` | P2 | 481 | `User.ReadBasic.All` | |
| `people user UPN\|ID` | P0 | 482 | `User.Read` | |
| `people photo [UPN]` | P1 (P2 others) | 483 | `User.Read`; others `gate(["User.ReadBasic.All"])` | |
| `org manager [UPN]` | P0 (P2 others) | 489 | `User.Read`; others `gate(["User.Read.All"])` | |
| `org reports [UPN]` | P0 (P2 others) | 490 | same | |
| `org chain [UPN]` | P1 | 491 | `User.Read`; iterative fallback `gate(["User.Read.All"])` | |
| `groups list` | P1 | 613 | `User.Read` | |
| `groups members GROUP` | P1 | 614 | `Group.Read.All` | |

- [ ] **Cluster C1: `people search`, `contacts`, `contact`, `users`, `user`, `photo`.** Full test:
  ```python
  @covers("people search")
  def test_people_search_query_and_columns(invoke, graph):
      routes = mock_graph(graph, "people/search")
      r = invoke("people", "search", "Ada", "--json")
      assert r.exit_code == 0, r.stderr
      req = routes[0].calls.last.request
      assert dict(req.url.params) == {"$search": '"Ada"', "$top": "50",
          "$select": "id,displayName,scoredEmailAddresses,jobTitle,department,companyName,personType,userPrincipalName"}
      assert json.loads(r.stdout)["count"] == 1
      assert invoke("people", "search", "Ada").stdout.splitlines()[0].split() == ["id", "name", "email", "title", "department", "type"]
  ```
  Also: `test_people_contacts_search_and_fallback` (`--search bob` → `$search="bob"`; a 400 on that call → second call without `$search` and `$top=250`, client-side filter keeps `Bob Example`); `test_people_contact_get`; `test_people_users_directory_search` (`$search` equals `"displayName:ada" OR "mail:ada"`, `$count=true`, `ConsistencyLevel: eventual`, `$top=100`, `$select` list of line 481); `@pytest.mark.scopes(["User.Read"])` on `people users` → exit 3; `test_people_user_forms` (`me` → `/me`; GUID; UPN → `/users/ada%40example.com`; `$select` of line 482); `test_people_user_name_needs_readbasic` (`people user "Ada Example"` with only `User.Read` → exit 2 message names `User.ReadBasic.All`; with `User.ReadBasic.All` → search + unique); `test_people_photo_self_and_other` (`people photo` → `GET /me/photo/$value`, default output `<upn>.jpg` where upn is the token's `upn` claim — `fixture-user@example.com.jpg` under the fake auth — or the positional UPN; `--output p.jpg` overrides; `people photo bob@example.com --size 96x96` → `/users/bob%40example.com/photos/96x96/$value` after `gate(["User.ReadBasic.All"])`; 404 → exit 4); pattern (e) on `people contact`. Implement. Commit `feat(mgraphctl): add people search, contacts, users, user and photo`.
- [ ] **Cluster C2: `org manager`, `reports`, `chain`.** Tests: `test_org_manager_self_and_other` (`/me/manager?$select=id,displayName,userPrincipalName,mail,jobTitle,department`; `bob@example.com` → `/users/bob%40example.com/manager`; 404 → stderr `error[...]: No manager found` exit 4; `--json` works); `@pytest.mark.scopes(["User.Read"])` → `org manager bob@example.com` exit 3 `needs User.Read.All`, hint `login --scope User.Read.All`; `test_org_reports` (`/me/directReports`); `test_org_chain_expand_then_fallback` (`GET /me?$expand=manager($levels=max;$select=id,displayName,userPrincipalName,jobTitle)&$count=true` with `ConsistencyLevel: eventual` → nested `manager` chain rendered one line per level from self upward; a 400 → iterative `GET /users/<id>/manager` up to `--max`). Commit `feat(mgraphctl): add org manager, reports and chain`.
- [ ] **Cluster C3: `groups list`, `groups members`.** Tests: `test_groups_list_plain_and_unified` (plain: `GET /me/memberOf/microsoft.graph.group?$select=id,displayName,mail,groupTypes,description&$top=100`; `--unified` → `graph.users.list_unified_groups` query with `$filter`, `$count=true`, `ConsistencyLevel`; default limit 20, cap 999); `test_groups_members_by_name` (`GROUP` name → memberOf lookup → `/groups/<id>/members?$select=id,displayName,userPrincipalName,mail,jobTitle&$top=100`); `test_groups_members_missing_scope` (`scopes(["User.Read"])` → 3); pattern (e). Commit `feat(mgraphctl): add groups list and members`.
- [ ] **Finish:** full suite, lint, group-help tests for `people`, `org`, `groups`.

### Task 11: Group D — `teams` + `chats` + `presence`   (Phase 1, parallel group P1, depends on: T6; **J (T17) depends on this task**)

**Files:** Create `graph/teams.py`, `graph/chats.py`, `graph/presence.py`, `commands/teams.py`, `commands/chats.py`, `commands/presence.py`, `tests/test_cli_teams.py`, `tests/test_cli_chats.py`, `tests/test_cli_presence.py`, `tests/fixtures/{teams,chats,presence}/*.json`.
**Interfaces:** Consumes Phase 0 incl. `graph.users.get_user/resolve_user`, `html.to_markdown(mode="teams")`, `html.text_to_html`. Produces: `graph.teams.resolve_team(client, value) -> dict`, `resolve_channel(client, team_id, value) -> dict`, `list_teams`, `get_team`, `list_members`, `list_channels`, `get_channel`, `channel_messages(client, team_id, channel_id, *, with_replies, limit, all_)`, `channel_replies(client, team_id, channel_id, msg_id, *, limit, all_)`, `plan_channel_send(client, team_id, channel_id, *, body, html, subject, reply_to)`, `message_columns(tz, full)`, `render_message_body(m, full) -> str`; `graph.chats.list_chats(client, *, chat_type, limit, all_)`, `chat_title(chat, my_oid) -> str`, `is_unread(chat) -> bool`, `get_chat`, `list_chat_members`, `chat_messages(client, chat_id, *, after, limit, all_)`, `plan_chat_send`, `find_one_on_one(client, user_id) -> dict | None` (pages `/me/chats?$filter=chatType eq 'oneOnOne'&$expand=members&$top=50`, cap 500), `plan_create_chat(client, *, member_ids, topic, my_oid)`, `plan_dm(client, user, existing_chat, *, body, html)`, `run_dm(client, user, *, body, html, my_oid, can_create: Callable[[], None])`, `search_chat_messages(client, q, *, after, before, limit) -> SearchResult`, **`shape_chat_hit(hit: dict) -> dict`** (`{"id", "created", "from", "where": "chat:<chatId>" | "channel:<teamId>/<channelId>", "summary", "webUrl"}` — exported for J), `hosted_content_path(chat_id, msg_id, hc_id) -> str`, `sniff_extension(data: bytes) -> str`; `graph.presence.get_presence(client)`, `get_presences(client, ids)`, `plan_set(client, my_oid, availability, *, expiration, message)`, `plan_clear(client, my_oid)`, `PRESENCE_PAIRS`.

Verbs (spec §8.7 lines 493–503, §8.8 lines 505–517, §8.9 lines 519–525):

| Verb | Tier | Line | Scopes | W |
|---|---|---|---|---|
| `teams list` | P0 | 497 | `Team.ReadBasic.All\|Group.Read.All` | |
| `teams get TEAM` | P1 | 498 | `Team.ReadBasic.All\|Group.Read.All` | |
| `teams members TEAM` | P2 | 499 | `TeamMember.Read.All` | |
| `teams channels TEAM` | P0 | 500 | `Channel.ReadBasic.All\|Group.Read.All` | |
| `teams channel get TEAM CHANNEL` | P1 | 501 | `Channel.ReadBasic.All\|Group.Read.All` | |
| `teams channel messages TEAM CHANNEL` | P0 | 502 | `ChannelMessage.Read.All` | |
| `teams channel send TEAM CHANNEL` | P0 | 503 | `ChannelMessage.Send` | W |
| `chats list` | P0 | 509 | `Chat.Read` | |
| `chats get CHAT` | P1 | 510 | `Chat.Read` | |
| `chats members CHAT` | P1 | 511 | `Chat.Read` | |
| `chats messages CHAT` | P0 | 512 | `Chat.Read` | |
| `chats send CHAT` | P0 | 513 | `ChatMessage.Send` | W |
| `chats dm USER` | P0 (create P2) | 514 | `Chat.Read`, `ChatMessage.Send`; creation `gate(["Chat.Create"])` | W |
| `chats create` | P2 | 515 | `Chat.Create` | W |
| `chats search Q` | P0 | 516 | `Chat.Read` (chat hits), `ChannelMessage.Read.All` (channel hits) — declare `["Chat.Read"]` | |
| `chats hosted-content` | P0 | 517 | `Chat.Read` (chat URL) / `ChannelMessage.Read.All` (channel URL) — declare `["Chat.Read"]`, `gate(["ChannelMessage.Read.All"])` for channel URLs | |
| `presence get [USER...]` | P2 | 523 | `Presence.Read`; others `gate(["Presence.Read.All"])` | |
| `presence set STATE` | P2 | 524 | `Presence.ReadWrite` | W |
| `presence clear` | P2 | 525 | `Presence.ReadWrite` | W |

Resolution (§6.6 lines 359–361): `TEAM` GUID else case-insensitive `displayName` in `/me/joinedTeams`; `CHANNEL` `19:` prefix else `displayName` in `/teams/{t}/channels`; `CHAT` `19:` prefix else contains `@` → the 1:1 chat with that UPN (`find_one_on_one` after `users.get_user`). Text mode prints messages chronologically (oldest first) with Markdown bodies capped at 300 chars unless `--full`; JSON keeps Graph order (spec §10 quirk 17).

- [ ] **Cluster D1: `teams list/get/members/channels/channel get/channel messages/channel send`.** Full test:
  ```python
  @covers("teams channel messages")
  def test_channel_messages_by_names_chronological_markdown(invoke, graph):
      routes = mock_graph(graph, "teams/channel_messages")   # joinedTeams → channels → messages (newest first, 3 items incl. one deleted + one unknownFutureValue)
      r = invoke("teams", "channel", "messages", "Engineering", "General")
      assert r.exit_code == 0, r.stderr
      assert routes[2].calls.last.request.url.params["$top"] == "50"
      lines = [l for l in r.stdout.splitlines() if l.strip()]
      assert lines[0].startswith("2026-08-30T") and lines[1].startswith("2026-08-31T")          # oldest first
      assert "@Ada Example" in r.stdout and "[image: hostedContents/aWQ=]" in r.stdout and "deleted" not in r.stdout
      doc = json.loads(invoke("teams", "channel", "messages", "Engineering", "General", "--json").stdout)
      assert [m["id"] for m in doc["items"]] == ["3", "2"]                                        # Graph order kept
  ```
  Also: `test_teams_list_no_odata_params` (`GET /me/joinedTeams` with empty query; columns `id name description`); `test_teams_get`; `test_teams_members_scope_gate` (`scopes(["Group.Read.All"])` → exit 3) and `test_teams_members`; `test_teams_channels_select` (`$select=id,displayName,description,membershipType`); `test_teams_team_ambiguous_exit_2` / `test_teams_channel_missing_exit_4`; `test_channel_messages_with_replies_expand` (`$expand=replies`); `test_channel_replies_paged_with_limit` (`--replies <id> --limit 3` → `/messages/<id>/replies?$top=50`, 3 rendered); `test_channel_messages_full_lifts_300` ; `test_channel_send_text_and_html_and_reply` (`POST .../messages {"body": {"contentType": "text", "content": "Hi <b>"}}` — no escaping; `--html` → `"html"`; `--subject` adds `subject`; `--reply-to <id>` → `/messages/<id>/replies`) + dry-run; pattern (e) on `teams get`. Commit `feat(mgraphctl): add teams and channel commands`.
- [ ] **Cluster D2: `chats list/get/members/messages/send/dm/create`.** Tests: `test_chats_list_query_unread_and_titles` (`$top=50`, `$expand=members,lastMessagePreview`, `$orderby=lastMessagePreview/createdDateTime desc`, `$select=id,topic,chatType,lastUpdatedDateTime,viewpoint,webUrl`; 1:1 title = other member's `displayName` (my oid from the synthetic token `oid`); group title = topic or first three member names; `--unread` keeps only `viewpoint.lastMessageReadDateTime < lastMessagePreview.createdDateTime`; text marker `*`; `--type group` → `$filter=chatType eq 'group'`); `test_chats_get_and_members`; `test_chats_messages_after_filter_and_order` (`$orderby=createdDateTime desc`, `--after 2026-08-01` → `$filter=createdDateTime gt 2026-08-01T00:00:00+02:00`; text chronological); `test_chats_send_text` + dry-run; `test_chats_dm_existing_chat` (`GET /users/bob%40example.com?$select=id,displayName` → page `/me/chats?$filter=chatType eq 'oneOnOne'&$expand=members&$top=50` until a chat whose members include that id → `POST /chats/<id>/messages`); `test_chats_dm_creates_chat` (no match → `POST /chats {"chatType": "oneOnOne", "members": [{"@odata.type": "#microsoft.graph.aadUserConversationMember", "roles": ["owner"], "user@odata.bind": "https://graph.microsoft.com/v1.0/users('<my oid>')"}, {... "<user id>"}]}` → then send; JSON = sent message + `"chatId"`); `test_chats_dm_create_requires_chat_create` (`scopes([...default without Chat.Create])`, no existing chat → exit 3 after the lookups, no `POST /chats`); `test_chats_dm_dry_run_shows_both_steps` (plan lists `POST /chats` with note `only when no 1:1 chat exists` and `POST /chats/{chatId}/messages`); `test_chats_create_group_and_one_on_one` (`--members a --members b --topic T` → group; single member no topic → oneOnOne) + dry-run + gate test; `test_chats_chat_by_upn_resolves_one_on_one`. Commit `feat(mgraphctl): add chats list, messages, send, dm and create`.
- [ ] **Cluster D3: `chats search`, `chats hosted-content`, `presence get/set/clear`.** Tests: `test_chats_search_labels_chat_and_channel_hits` (`POST /search/query {"requests": [{"entityTypes": ["chatMessage"], "query": {"queryString": "budget"}, "from": 0, "size": 25}]}`; fixture returns one hit with `resource.chatId` and one with `resource.channelIdentity` → text `where` column `chat:19:c@thread.v2` / `channel:<teamId>/<channelId>`; `--after/--before` filter client-side on `createdDateTime`; `--all` pages while `moreResultsAvailable` up to 200); `test_shape_chat_hit_unit` (direct call; keys `id created from where summary webUrl`); `test_hosted_content_triplet_and_url` (`chats hosted-content 19:c@thread.v2 1 aWQ= --output x.png` → `GET /chats/19%3Ac%40thread.v2/messages/1/hostedContents/aWQ%3D/$value`; a full `https://graph.microsoft.com/v1.0/teams/.../channels/.../messages/1/hostedContents/aWQ=/$value` URL used verbatim; default name `teams_hosted_aWQ=.png` sniffed from PNG magic bytes; `Downloaded ...`); `test_presence_get_self_and_others` (`GET /me/presence`; `presence get bob@example.com` → `get_user` then `POST /communications/getPresencesByUserId {"ids": [...]}`; `scopes([...without Presence.Read.All])` with a user → exit 3); `test_presence_set_pairs_expiration_and_message` (`presence set dnd --expiration 2h --message "Heads down"` → `POST /users/<my oid>/presence/setUserPreferredPresence {"availability": "DoNotDisturb", "activity": "DoNotDisturb", "expirationDuration": "PT2H"}` then `POST .../presence/setStatusMessage {"statusMessage": {"message": {"content": "Heads down", "contentType": "text"}}}`; default expiration `PT1H`; `offline` → `Offline/OffWork`; `brb` → `BeRightBack`) + dry-run; `test_presence_clear` + dry-run; gate test on `presence set` with `scopes(["Presence.Read"])`. Commit `feat(mgraphctl): add chats search, hosted content and presence`.
- [ ] **Finish:** full suite, lint, group-help tests for `teams`, `teams channel`, `chats`, `presence`.

### Task 12: Group E — `meetings`   (Phase 1, parallel group P1, depends on: T6)

**Files:** Create `graph/meetings.py`, `commands/meetings.py`, `tests/test_cli_meetings.py`, `tests/fixtures/meetings/*.json`.
**Interfaces:** Consumes Phase 0 incl. `html.vtt_to_text` and `auth.decode_jwt(auth.get_access_token())["oid"]` (my `oid` for the `insights` path, derived exactly as `presence set` derives it — no `/me` call). Produces: `graph.meetings.list_online_events(client, *, start, end, subject, limit, tz) -> list[dict]` (its own `GET /me/calendarView` with `$select=id,subject,start,end,organizer,isOnlineMeeting,onlineMeeting`, `$top=50`, `Prefer` tz; keeps `isOnlineMeeting and onlineMeeting.joinUrl`; `--subject` case-insensitive substring), `resolve_meetings(client, events) -> dict[event_id, meeting]` (`$batch` of `GET /me/onlineMeetings?$filter=JoinWebUrl eq '<escaped url>'`), `transcripts_for(client, meeting_ids) -> dict[id, list]`, `select_meeting(client, meeting, join_url, event) -> dict` (exactly one selector, else `UsageError`), `list_transcripts`, `get_transcript_content(client, meeting_id, transcript_id, *, fmt) -> str` (VTT via `$format=text/vtt`; text = `vtt_to_text`; a 403 with code `SpeakerAttributionNotAllowed` → retry with `Accept: application/vnd.microsoft.graph.transcript+text`), `insights(client, oid, meeting_id) -> tuple[list[dict], str | None]` (v1.0 first, `/beta` on 404, per-item detail GET on the base that answered, item errors keep the list entry; returns `(items, note)`), `list_recordings`, `download_recording`.

Verbs (spec §8.10 lines 527–536):

| Verb | Tier | Line | Scopes | W |
|---|---|---|---|---|
| `meetings list` | P0 | 531 | `Calendars.Read`; `--resolve` `gate(["OnlineMeetings.Read"])`; `--with-transcripts` `gate(["OnlineMeetingTranscript.Read.All"])` | |
| `meetings get [MEETING]` | P1 | 532 | `OnlineMeetings.Read` | |
| `meetings transcripts [MEETING]` | P0 | 533 | `OnlineMeetingTranscript.Read.All` | |
| `meetings transcript [MEETING] TRANSCRIPT_ID` | P0 | 534 | `OnlineMeetingTranscript.Read.All` | |
| `meetings insights [MEETING]` | P0 | 535 | `OnlineMeetingAiInsight.Read.All` | |
| `meetings recordings [MEETING]` | P2 | 536 | `OnlineMeetingRecording.Read.All` (on-demand) | |

Selector rule (§6.6 line 371): positional `MEETING` id, or `--join-url URL` → `$filter=JoinWebUrl eq '<odata_str(url)>'`, or `--event ID` → `GET /me/events/<id>?$select=onlineMeeting` then the same filter. `--with-transcripts` implies `--resolve`.

- [ ] **Cluster E1: `list`, `get`.** Full test:
  ```python
  @covers("meetings list")
  def test_meetings_list_default_window_resolve_and_transcripts(invoke, graph, monkeypatch):
      from mgraphctl import render
      fixed = datetime(2026, 9, 2, 15, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
      monkeypatch.setattr(render, "_now", lambda zone: fixed.astimezone(zone))
      routes = mock_graph(graph, "meetings/list_resolve")   # calendarView (2 online, 1 not), $batch, transcripts x2
      r = invoke("meetings", "list", "--resolve", "--with-transcripts", "--json")
      assert r.exit_code == 0, r.stderr
      view = routes[0].calls.last.request
      assert view.url.params["startDateTime"] == "2026-08-26T00:00:00+02:00" and view.url.params["endDateTime"] == "2026-09-02T23:59:59+02:00"
      batch = json.loads(routes[1].calls.last.request.content)
      assert [b["url"] for b in batch["requests"]] == ["/me/onlineMeetings?$filter=JoinWebUrl%20eq%20%27https%3A%2F%2Fteams.example.com%2Fl%2F1%27",
                                                       "/me/onlineMeetings?$filter=JoinWebUrl%20eq%20%27https%3A%2F%2Fteams.example.com%2Fl%2F2%27"]
      doc = json.loads(r.stdout)
      assert doc["count"] == 2 and doc["items"][0]["meetingId"] == "MSpk-1" and doc["items"][0]["transcriptIds"] == ["tr-1"]
      text = invoke("meetings", "list", "--resolve", "--with-transcripts").stdout.splitlines()
      assert text[0].split() == ["start", "subject", "event_id", "meeting_id", "transcripts"]
  ```
  Also: `test_meetings_list_subject_filter_and_window_options`; `test_meetings_list_resolve_requires_online_meetings_scope` (`scopes(["Calendars.Read"])` + `--resolve` → exit 3 before the batch); `test_meetings_get_by_id_join_url_event` (three selector forms; `--event` → `GET /me/events/<id>?$select=onlineMeeting` then the filter); `test_meetings_get_selector_conflict_exit_2`; pattern (e) on `meetings get`. Commit `feat(mgraphctl): add meetings list and get`.
- [ ] **Cluster E2: `transcripts`, `transcript`, `insights`, `recordings`.** Tests: `test_meetings_transcripts_list` (`GET /me/onlineMeetings/<id>/transcripts`; columns `id created`); `test_meetings_transcript_text_vtt_output` (`GET .../transcripts/<t>/content?$format=text/vtt` → text `[00:00:01] Ada Example: Hello there`; `--format vtt` prints raw VTT; `--output f` writes; JSON `{"meetingId", "transcriptId", "format", "text"}`); `test_meetings_transcript_speaker_attribution_fallback` (403 body code `SpeakerAttributionNotAllowed` → second request with `Accept: application/vnd.microsoft.graph.transcript+text`); `test_meetings_insights_v1_then_beta_and_soft_paths` (`GET /v1.0/copilot/users/<oid>/onlineMeetings/<id>/aiInsights` 404 → `/beta/...` 200 with two items → per-item `GET .../aiInsights/<iid>` on `/beta`; one item detail 500 keeps the list entry; 403 on both → stdout `AI insights require a Microsoft 365 Copilot license...`, exit 0, JSON `{"items": [], "count": 0, "truncated": false, "note": "..."}`; empty → soft message exit 0); `test_meetings_recordings_and_download` (`GET .../recordings`; `--download <rid> --output f` → `.../recordings/<rid>/content` bytes); `test_meetings_recordings_on_demand_scope_hint` (`scopes(config.DEFAULT_SCOPES)` → exit 3, hint contains `login --scope OnlineMeetingRecording.Read.All`). Commit `feat(mgraphctl): add meeting transcripts, insights and recordings`.
- [ ] **Finish:** full suite, lint, `test_meetings_group_help`.

### Task 13: Group F — `onedrive`   (Phase 1, parallel group P1, depends on: T6, T7)

**Files:** Create `graph/onedrive.py`, `commands/onedrive.py`, `tests/test_cli_onedrive.py`, `tests/fixtures/onedrive/*.json`.
**Interfaces:** Consumes Phase 0 incl. every `graph.files.*` function (T7). Produces: `graph.onedrive.base_for(drive_id: str | None) -> str` (`"/me/drive"` or `odata.p("drives", drive_id)`), `shared_with_me(client, *, limit)`, `recent(client, *, limit)`; everything else delegates to `graph.files`.

Verbs (spec §8.11 lines 538–554; every verb accepts `--drive DRIVE_ID`):

| Verb | Tier | Line | Scopes | W |
|---|---|---|---|---|
| `onedrive ls [PATH]` | P0 | 542 | `Files.Read` | |
| `onedrive search Q` | P1 | 543 | `Files.Read` | |
| `onedrive get ID\|PATH` | P0 | 544 | `Files.Read` | |
| `onedrive download ID\|PATH` | P0 | 545 | `Files.Read` | |
| `onedrive upload FILE` | P0 | 546 | `Files.ReadWrite` | W |
| `onedrive mkdir PATH` | P1 | 547 | `Files.ReadWrite` | W |
| `onedrive move ID\|PATH` | P1 | 548 | `Files.ReadWrite` | W |
| `onedrive rename ID\|PATH NAME` | P1 | 549 | `Files.ReadWrite` | W |
| `onedrive delete ID\|PATH` | P1 | 550 | `Files.ReadWrite` | W |
| `onedrive share ID\|PATH` | P1 | 551 | `Files.ReadWrite` | W |
| `onedrive shared-with-me` | P1 | 552 | `Files.Read.All\|Sites.Read.All` | |
| `onedrive recent` | P1 | 553 | `Files.Read` | |
| `onedrive link URL` | P1 | 554 | `Files.Read` | |

- [ ] **Cluster F1: `ls`, `search`, `get`, `download`, `shared-with-me`, `recent`, `link`.** Full test:
  ```python
  @covers("onedrive ls")
  def test_onedrive_ls_root_and_path(invoke, graph):
      routes = mock_graph(graph, "onedrive/ls")     # /me/drive/root/children and /me/drive/root:/Docs%20Q3:/children
      r = invoke("onedrive", "ls", "--json")
      assert r.exit_code == 0, r.stderr
      assert dict(routes[0].calls.last.request.url.params) == {"$top": "200", "$orderby": "name",
          "$select": "id,name,size,lastModifiedDateTime,file,folder,webUrl,parentReference"}
      assert json.loads(r.stdout)["count"] == 2
      r = invoke("onedrive", "ls", "Docs Q3")
      assert routes[1].called and r.stdout.splitlines()[0].split() == ["type", "id", "size", "modified", "name"]
      assert r.stdout.splitlines()[1].startswith("d  01ABCDEFGHIJKLMNOPQRSTUV")
  ```
  Also: `test_onedrive_ls_drive_option` (`--drive b!abc` → `/drives/b!abc/root/children`); `test_onedrive_search_own_and_shared`; `test_onedrive_get_by_id_and_path`; `test_onedrive_download_default_name_and_output` (metadata GET, `/content` 302 → bytes; `Downloaded report.pdf (12 B) to <path>`; `--json` FileResult keys); pattern (e) on `onedrive get`; `test_onedrive_shared_with_me_note` (`GET /me/drive/sharedWithMe`; stderr note mentions the endpoint being degraded after Nov 2026; columns include `remoteItem.parentReference.driveId` / `remoteItem.id`); `test_onedrive_recent`; `test_onedrive_link_info_and_download` (`GET /shares/u!.../driveItem`; `--download` → `.../driveItem/content`). Commit `feat(mgraphctl): add onedrive browsing and downloads`.
- [ ] **Cluster F2: `upload`, `mkdir`, `move`, `rename`, `delete`, `share`.** Tests: `test_onedrive_upload_small_put` (`PUT /me/drive/root:/Docs/a.txt:/content?@microsoft.graph.conflictBehavior=replace` with the bytes and `Content-Type: text/plain`; JSON = item); `test_onedrive_upload_large_session` (5 MiB → `createUploadSession` + one 5 MiB chunk PUT `bytes 0-5242879/5242880`); `test_onedrive_upload_dest_folder_and_conflict` (`--dest Docs/` → basename appended; `--conflict fail`); `test_onedrive_upload_dry_run` (large: `{"createUploadSession": ..., "upload": {"$file": ..., "bytes": ..., "contentType": ...}, "chunkSize": 10485760}`); `test_onedrive_mkdir` + dry-run; `test_onedrive_move_by_path_and_id` + dry-run; `test_onedrive_rename` + dry-run; `test_onedrive_delete` + dry-run; `test_onedrive_share_prints_web_url` (`createLink {"type": "edit", "scope": "anonymous", "expirationDateTime": "2026-12-31T23:59:59+01:00"}`; text = `link.webUrl`; a 403 → exit 3 with the FORBIDDEN hint) + dry-run; `@pytest.mark.scopes(["Files.Read"])` on `upload` → exit 3. Commit `feat(mgraphctl): add onedrive upload and item writes`.
- [ ] **Finish:** full suite, lint, `test_onedrive_group_help`.

### Task 14: Group G — `sharepoint`   (Phase 1, parallel group P1, depends on: T6, T7)

**Files:** Create `graph/sharepoint.py`, `commands/sharepoint.py`, `tests/test_cli_sharepoint.py`, `tests/fixtures/sharepoint/*.json`.
**Interfaces:** Consumes Phase 0 incl. `graph.files.*`, `odata.site_ref/share_id`, `client.search`. Produces: `graph.sharepoint.resolve_site(client, value) -> dict` (`looks_like_id(value, "site")` — a URL, a `host:/path` reference or a composite id — → `GET {odata.site_ref(value)}?$select=id,displayName,name,webUrl,description`; anything else is a display name → `GET /sites?search=<value>` + `pick_unique(items, "displayName", value, what="site")`), `list_sites(client, *, search, limit)` (followed sites; `--search` or empty list → `GET /sites?search=<q or *>&$top=<limit>`), `list_drives(client, site_id)`, `resolve_drive(client, site_id, value) -> str` (`b!` id or `name` in `/sites/{id}/drives`), `drive_base(site_id, drive_id | None) -> str` (`/sites/{id}/drive` or `/drives/{d}`), `search_site_drive(client, site_id, q, *, limit)`, `search_all(client, q, *, limit) -> SearchResult`, `resolve_url(client, url) -> Resolution` (`Resolution(site_id, drive_id, path, item)` per the line 567 algorithm: 1) `GET /shares/{share_id}/driveItem`; on 4xx 2) parse host + `sites|teams|personal` segment skipping `/:x:/r/` prefixes, `GET /sites/{host}:/{kind}/{name}`, `GET /sites/{id}/drives`, pick the drive whose `webUrl` is the deepest prefix of the file path, `GET /drives/{d}/root:/{rel}` metadata; fallback `GET /sites/{id}/drive/root:/{rel}` with and without the first segment; only 404 moves on), `download_url(client, url, dest) -> tuple[Resolution, DownloadResult]`, `list_lists(client, site_id)` (system lists hidden: entries whose `list.hidden` is true are dropped; document libraries are kept), `list_items(client, site_id, list_id, *, fields, filter_, limit, all_)` (`$expand=fields($select=…)`, `$top=200`, `Prefer: HonorNonIndexedQueriesWarningMayFailRandomly` with `--filter`), `resolve_list(client, site_id, value)`.

Verbs (spec §8.12 lines 556–569):

| Verb | Tier | Line | Scopes | W |
|---|---|---|---|---|
| `sharepoint sites` | P0 | 560 | `Sites.Read.All` | |
| `sharepoint site REF` | P0 | 561 | `Sites.Read.All` | |
| `sharepoint drives SITE` | P1 | 562 | `Sites.Read.All` | |
| `sharepoint ls SITE [PATH]` | P0 | 563 | `Sites.Read.All` | |
| `sharepoint search Q` | P1 | 564 | `Sites.Read.All` | |
| `sharepoint download SITE ITEM\|PATH` | P0 | 565 | `Sites.Read.All` | |
| `sharepoint upload SITE FILE` | P1 | 566 | `Sites.ReadWrite.All` | W |
| `sharepoint url URL` | P0 | 567 | `Sites.Read.All` | |
| `sharepoint lists SITE` | P1 | 568 | `Sites.Read.All` | |
| `sharepoint items SITE LIST` | P1 | 569 | `Sites.Read.All` | |

Resolution (§6.6 lines 363–364): `SITE` URL/`host:/a/b`/composite id via `odata.site_ref`, else `GET /sites?search=<name>` unique `displayName`; `--drive` `b!` id or `name` in `/sites/{id}/drives`.

- [ ] **Cluster G1: `sites`, `site`, `drives`, `ls`, `search`, `download`, `lists`, `items`.** Full test:
  ```python
  @covers("sharepoint site")
  def test_sharepoint_site_forms(invoke, graph):
      routes = mock_graph(graph, "sharepoint/site")   # /sites/contoso.example:/sites/Eng ; /sites/contoso.example ; /sites/<composite> ; /sites?search=Eng
      for ref, idx in (("https://contoso.example/sites/Eng/Shared%20Documents/a.docx", 0), ("contoso.example:/sites/Eng", 0),
                       ("https://contoso.example/", 1),
                       ("contoso.example,11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222", 2), ("Eng", 3)):
          r = invoke("sharepoint", "site", ref, "--json")
          assert r.exit_code == 0, (ref, r.stderr)
          assert routes[idx].called and json.loads(r.stdout)["displayName"] == "Eng"
      assert routes[0].calls[0].request.url.params["$select"] == "id,displayName,name,webUrl,description"
  ```
  Also: `test_sharepoint_sites_followed_then_search_fallback` (`GET /me/followedSites?$select=id,displayName,webUrl`; empty → `GET /sites?search=*&$top=20`; `--search x` → `search=x`); `test_sharepoint_site_ambiguous_exit_2`; `test_sharepoint_drives`; `test_sharepoint_ls_site_drive_and_named_drive` (`/sites/<id>/drive/root/children`; `--drive Documents` → drives lookup → `/drives/b!x/root:/Sub:/children`; ids printed); `test_sharepoint_search_site_and_global` (`/sites/<id>/drive/root/search(q='x')` vs `POST /search/query` with `entityTypes: ["driveItem"]`, size 25, cap 200); `test_sharepoint_download_uses_site_drive` (`/sites/<id>/drive/items/<item>/content` or `/drives/<d>/root:/<path>:/content`); `test_sharepoint_lists_hides_hidden` (`$select=id,displayName,webUrl,list`); `test_sharepoint_items_fields_filter_and_prefer` (`$expand=fields($select=Title,Status)`, `$top=200`, `$filter=fields/Status eq 'Open'`, header `Prefer: HonorNonIndexedQueriesWarningMayFailRandomly`; text shows one column per field, first 8); pattern (e) on `sharepoint site`. Commit `feat(mgraphctl): add sharepoint sites, drives, browsing, lists and items`.
- [ ] **Cluster G2: `url`, `upload`.** Tests: `test_sharepoint_url_share_link_first` (`GET /shares/u!…/driveItem` 200 → `--info` prints `siteId, driveId, path, item` and JSON `{"resolution": {...}, "item": {...}}`; without `--info` → `.../driveItem/content` download named by basename); `test_sharepoint_url_node_algorithm_fallback` (`/shares` 403 → `GET /sites/contoso.example:/sites/Eng` → `GET /sites/<id>/drives` (two drives; deepest `webUrl` prefix wins) → `GET /drives/<d>/root:/Folder/a.docx` → `.../content`; URL contains `/:w:/r/` prefix which is skipped); `test_sharepoint_url_fallback_without_first_segment` (drive path 404 → `/sites/<id>/drive/root:/Folder/a.docx` 404 → `/sites/<id>/drive/root:/a.docx` 200); `test_sharepoint_url_personal_hint` (`/personal/` URL with 403 → exit 3, hint mentions the owner's share); `test_sharepoint_upload_site_drive` (`PUT /sites/<id>/drive/root:/Docs/a.txt:/content?...` small; large session) + dry-run; `scopes(["Sites.Read.All"])` on `upload` → exit 3. Commit `feat(mgraphctl): add sharepoint url resolution and upload`.
- [ ] **Finish:** full suite, lint, `test_sharepoint_group_help`.

### Task 15: Group H — `onenote`   (Phase 1, parallel group P1, depends on: T6)

**Files:** Create `graph/onenote.py`, `commands/onenote.py`, `tests/test_cli_onenote.py`, `tests/fixtures/onenote/*.json`.
**Interfaces:** Consumes Phase 0 incl. `html.to_markdown(mode="onenote")`, `html.text_to_html`. Produces: `graph.onenote.list_notebooks`, `resolve_notebook(client, value)`, `list_sections(client, notebook_id | None, *, limit)`, `resolve_section(client, value)` (id form or `displayName` among `/me/onenote/sections`), `list_pages(client, section_id, *, limit, all_)`, `resolve_page(client, value)` (id form or `title` among `/me/onenote/pages?$top=100`), `get_page(client, page_id) -> tuple[dict, str]` (metadata + `GET .../content?includeIDs=true` HTML), `plan_create_page(client, section_id, *, title, body, html)` (`Content-Type: text/html`, body string `<!DOCTYPE html><html><head><title>{escaped}</title></head><body>{text_to_html(body) or raw}</body></html>`), `search_pages(client, q, *, limit)`.

Verbs (spec §8.13 lines 571–580):

| Verb | Tier | Line | Scopes | W |
|---|---|---|---|---|
| `onenote notebooks` | P0 | 575 | `Notes.Read` | |
| `onenote sections [NOTEBOOK]` | P0 | 576 | `Notes.Read` | |
| `onenote pages SECTION` | P0 | 577 | `Notes.Read` | |
| `onenote read PAGE` | P0 | 578 | `Notes.Read` | |
| `onenote create` | P0 | 579 | `Notes.ReadWrite` | W |
| `onenote search Q` | P0 | 580 | `Notes.Read` | |

Resolution (§6.6 line 367): `NOTEBOOK/SECTION/PAGE` id when `looks_like_id(v, "onenote")`, else `displayName`/`title` among the parent listing.

- [ ] **Cluster H1: all six verbs.** Full test:
  ```python
  @covers("onenote read")
  def test_onenote_read_markdown_and_json(invoke, graph):
      routes = mock_graph(graph, "onenote/read")   # GET /me/onenote/pages/<id>?$select=id,title,lastModifiedDateTime,links ; GET .../content?includeIDs=true (text/html)
      r = invoke("onenote", "read", "1-abc!12")
      assert r.exit_code == 0, r.stderr
      assert routes[1].calls.last.request.url.query.decode() == "includeIDs=true"
      assert "# Meeting notes" in r.stdout and "- action one" in r.stdout
      doc = json.loads(invoke("onenote", "read", "1-abc!12", "--json").stdout)
      assert set(doc) == {"id", "title", "html", "markdown"} and doc["html"].startswith("<html")
      assert invoke("onenote", "read", "1-abc!12", "--html").stdout.startswith("<html")
  ```
  Also: `test_onenote_notebooks` (`$top=100`, `$select=id,displayName,lastModifiedDateTime,links`); `test_onenote_sections_all_and_by_notebook_name` (`/me/onenote/sections` vs notebook lookup → `/me/onenote/notebooks/<id>/sections`); `test_onenote_pages_by_section_name` (`$orderby=lastModifiedDateTime desc`, `$top=100`, cap 500); `test_onenote_read_by_title_resolves`; `test_onenote_read_output_writes_markdown`; `test_onenote_create_escapes_unless_html` (`POST /me/onenote/sections/<id>/pages` with `Content-Type: text/html`; body contains `<title>Q3 &lt;plan&gt;</title>` and `<p>a &lt;b&gt;</p>`; `--html` passes the body raw); `test_onenote_create_dry_run` (body shown as the HTML string); `scopes(["Notes.Read"])` on `create` → exit 3; `test_onenote_search_passthrough_hint` (`GET /me/onenote/pages?$search=budget&$top=100&$select=id,title,createdDateTime,parentSection`; a 400 → exit 1 with hint containing `search budget --type driveItem`); pattern (e) on `onenote read`; `--limit 0` on `pages`. Commit `feat(mgraphctl): add onenote notebooks, sections, pages, read, create and search`.
- [ ] **Finish:** full suite, lint, `test_onenote_group_help`.

### Task 16: Group I — `planner` + `todo`   (Phase 1, parallel group P1, depends on: T6)

**Files:** Create `graph/planner.py`, `graph/todo.py`, `commands/planner.py`, `commands/todo.py`, `tests/test_cli_planner.py`, `tests/test_cli_todo.py`, `tests/fixtures/{planner,todo}/*.json`.
**Interfaces:** Consumes Phase 0 incl. `graph.users.list_unified_groups/get_user`, `client.batch`. Produces: `graph.planner.list_plans(client) -> list[dict]` (`/me/planner/plans` ∪ `$batch` of `/groups/{id}/planner/plans` per unified group, deduped by id, each plan annotated with `_groupName` for text only), `resolve_plan(client, value)`, `get_plan(client, id) -> dict` (`{...plan, "details": {...}}`), `list_buckets`, `resolve_bucket(client, plan_id, value)`, `list_tasks(client, plan_id, *, bucket_id, include_completed, limit)`, `my_tasks(client, *, include_completed, limit)` (+ `$batch` of `/planner/plans/{id}` for ≤ 20 distinct plan titles), `get_task(client, id)` (+ `/details`, errors swallowed), `plan_create_task(client, ...)`/`run_create_task` (`GET /users/{upn}?$select=id` per assignee; `POST /planner/tasks`; `--description` → `GET .../details` etag → `PATCH .../details` `If-Match`), `plan_update_task`/`run_update_task` (`GET` etag → `PATCH` `If-Match` + `Prefer: return=representation`; 412 → re-read once and retry), `plan_delete_task`/`run_delete_task`; `graph.todo.list_lists`, `resolve_list(client, value)` (`looks_like_id(v, "todo_list")`, well-known `defaultList`/`flaggedEmails` → `wellknownListName` match, else `displayName`), `list_tasks(client, list_id, *, include_completed, limit, all_)`, `get_task`, `task_body(...)`, `plan_create`, `plan_update`, `plan_complete`, `plan_delete`, `fetch_message_for_task(client, msg_id) -> dict` (`GET /me/messages/{id}?$select=subject,webLink,bodyPreview,from,receivedDateTime` — implemented here, not imported from group A, so the groups stay independent), `plan_from_mail(client, list_id, message, *, title, due, importance, tz)`.

Verbs (spec §8.14 lines 582–594, §8.15 lines 596–607):

| Verb | Tier | Line | Scopes | W |
|---|---|---|---|---|
| `planner plans` | P0 | 586 | `Tasks.ReadWrite`, `Group.Read.All` | |
| `planner plan PLAN` | P1 | 587 | `Tasks.ReadWrite` | |
| `planner buckets PLAN` | P0 | 588 | `Tasks.ReadWrite` | |
| `planner tasks [PLAN]` | P0 | 589 | `Tasks.ReadWrite` | |
| `planner task ID` | P0 | 590 | `Tasks.ReadWrite` | |
| `planner create` | P0 | 591 | `Tasks.ReadWrite` | W |
| `planner update ID` | P1 | 592 | `Tasks.ReadWrite` | W |
| `planner complete ID` | P0 | 593 | `Tasks.ReadWrite` | W |
| `planner delete ID` | P1 | 594 | `Tasks.ReadWrite` | W |
| `todo lists` | P0 | 600 | `Tasks.ReadWrite` | |
| `todo tasks LIST` | P0 | 601 | `Tasks.ReadWrite` | |
| `todo task LIST ID` | P1 | 602 | `Tasks.ReadWrite` | |
| `todo create LIST` | P0 | 603 | `Tasks.ReadWrite` | W |
| `todo update LIST ID` | P1 | 604 | `Tasks.ReadWrite` | W |
| `todo complete LIST ID` | P0 | 605 | `Tasks.ReadWrite` | W |
| `todo delete LIST ID` | P1 | 606 | `Tasks.ReadWrite` | W |
| `todo from-mail LIST MSGID` | P1 | 607 | `Tasks.ReadWrite`, `Mail.Read` | W |

Planner paths carry no OData query parameters; slicing is client-side. Resolution (§6.6 lines 368–369): `PLAN/BUCKET` ids match `^[A-Za-z0-9_-]{28}$`, else `title`/`name` among plans / plan buckets; todo `LIST` `AQMk…`/`AAMk…`/40+ chars or well-known or `displayName`.

- [ ] **Cluster I1: `planner plans/plan/buckets/tasks/task`.** Full test:
  ```python
  @covers("planner plans")
  def test_planner_plans_union_via_batch(invoke, graph):
      routes = mock_graph(graph, "planner/plans")   # /me/planner/plans (1 plan) ; memberOf unified (2 groups) ; $batch (2 sub GETs, one plan overlaps)
      r = invoke("planner", "plans", "--json")
      assert r.exit_code == 0, r.stderr
      batch = json.loads(routes[2].calls.last.request.content)
      assert [b["url"] for b in batch["requests"]] == ["/groups/11111111-1111-1111-1111-111111111111/planner/plans",
                                                       "/groups/22222222-2222-2222-2222-222222222222/planner/plans"]
      doc = json.loads(r.stdout); assert doc["count"] == 2 and "_groupName" not in doc["items"][0]
      text = invoke("planner", "plans").stdout
      assert text.splitlines()[0].split() == ["id", "title", "group"] and "Engineering" in text
  ```
  Also: `test_planner_plan_with_details` (JSON `{..., "details": {...}}`); `test_planner_buckets_by_plan_title`; `test_planner_tasks_hides_completed_and_names_buckets` (`percentComplete == 100` hidden unless `--include-completed`; buckets fetched for names; `--bucket Backlog` filters; columns `id % priority due bucket title`); `test_planner_tasks_my_with_plan_titles_batch` (`/me/planner/tasks` + `$batch` of `GET /planner/plans/<id>` for the distinct plan ids; column `plan`); `test_planner_task_details_error_swallowed` (details 403 → task still printed); `test_planner_no_odata_params` (every planner request has an empty query); `test_planner_tasks_limit_client_side`; pattern (e) on `planner task`. Commit `feat(mgraphctl): add planner plans, buckets and tasks`.
- [ ] **Cluster I2: `planner create/update/complete/delete`.** Tests: `test_planner_create_assign_and_description` (`--plan Roadmap --title T --bucket Backlog --due 2026-09-10 --assign ada@example.com --priority 3 --description D` → plans lookup, buckets lookup, `GET /users/ada%40example.com?$select=id`, `POST /planner/tasks {"planId", "bucketId", "title": "T", "dueDateTime": "2026-09-10T00:00:00+02:00", "priority": 3, "assignments": {"<oid>": {"@odata.type": "#microsoft.graph.plannerAssignment", "orderHint": " !"}}}` → `GET /planner/tasks/<id>/details` (`@odata.etag`) → `PATCH .../details` with `If-Match` and `{"description": "D"}`); `test_planner_create_dry_run_shows_etag_placeholder` (`If-Match: {etag}`); `test_planner_update_etag_and_412_retry` (fixture with `responses` for `/planner/tasks/<id>`: GET etag-1 → PATCH 412 → GET etag-2 → PATCH 200; header `Prefer: return=representation`; `--percent 50 --unassign bob@example.com` → `assignments: {"<oid>": null}`); `test_planner_complete_is_percent_100` + dry-run; `test_planner_delete_with_if_match` + dry-run; `test_planner_update_dry_run`. Commit `feat(mgraphctl): add planner task writes with etag handling`.
- [ ] **Cluster I3: `todo lists/tasks/task/create/update/complete/delete/from-mail`.** Tests: `test_todo_lists_wellknown` (`$top=100`; columns `id wellknown name`); `test_todo_tasks_filter_and_list_resolution` (`todo tasks Groceries` → lists lookup → `/me/todo/lists/<id>/tasks?$top=100&$filter=status ne 'completed'`; `defaultList` → the list whose `wellknownListName == "defaultList"`; `--include-completed` drops the filter; `Prefer` tz); `test_todo_task_expand` (`$expand=checklistItems,linkedResources`); `test_todo_create_full_body` (`POST .../tasks {"title": "T", "body": {"content": "B", "contentType": "text"}, "importance": "high", "dueDateTime": {"dateTime": "2026-09-10T00:00:00", "timeZone": "Europe/Warsaw"}, "reminderDateTime": {...}, "isReminderOn": true, "startDateTime": {...}}`) + dry-run; `test_todo_update_and_status`; `test_todo_complete` (`PATCH {"status": "completed"}`) + dry-run; `test_todo_delete` + dry-run; `test_todo_from_mail` (`GET /me/messages/AAMk-msg-0001?$select=subject,webLink,bodyPreview,from,receivedDateTime` → `POST .../tasks {"title": <subject>, "body": {"content": "From: Ada Example <ada@example.com>\nReceived: 2026-08-31T10:15+02:00\n\n<bodyPreview>", "contentType": "text"}, "linkedResources": [{"webUrl": <webLink>, "applicationName": "Microsoft Outlook", "displayName": <subject>, "externalId": "AAMk-msg-0001"}]}`; `--title` overrides) + dry-run (`{msg}` fields shown after the GET is executed even in dry-run — the GET is a read and is allowed; assert the plan's single POST); `scopes(["Tasks.Read"])` gate test on `todo create` → exit 3; pattern (e) on `todo task`. Commit `feat(mgraphctl): add to do lists, tasks and writes`.
- [ ] **Finish:** full suite, lint, group-help tests for `planner`, `todo`.

### Task 17: Group J — `search`   (Phase 1, depends on: T6 **and T11** — imports `graph.chats.shape_chat_hit`)

**Files:** Create `graph/search.py`, `commands/search.py` (exposes `command`, kind `command` in the registry), `tests/test_cli_search.py`, `tests/fixtures/search/*.json`.
**Interfaces:** Consumes Phase 0 incl. `client.search`, `render.kql_date/parse_dt/fmt_dt`, and `mgraphctl.graph.chats.shape_chat_hit` (T11). Produces: `graph.search.SCOPES_BY_TYPE = {"message": ["Mail.Read"], "event": ["Calendars.Read"], "driveItem": ["Sites.Read.All"], "site": ["Sites.Read.All"], "list": ["Sites.Read.All"], "chatMessage": ["Chat.Read"], "person": ["People.Read"]}`, `search(client, *, entity_type, q, after, before, limit, all_, fields, tz) -> SearchResult` (message: `--after/--before` appended to the KQL as `received>=`/`received<=`; other types filtered client-side on `receivedDateTime`/`start.dateTime`/`lastModifiedDateTime`/`createdDateTime`), `columns_for(entity_type, tz) -> list[Column]`, `shape_hit(entity_type, hit) -> dict` (chatMessage → `shape_chat_hit`).

Verb (spec §8.17 line 620): `search Q` `--type message|event|driveItem|site|list|chatMessage|person` (message), `--after DT`, `--before DT`, `--limit 25`, `--all` (cap 200), `--fields a,b`; scopes per type (declared statically as `[]` on the decorator and gated at runtime with `gate(SCOPES_BY_TYPE[type])` **before** the request, because the scope depends on `--type`); P1.

- [ ] **Cluster J1: `search`.** Full test:
  ```python
  @covers("search")
  def test_search_message_kql_dates_and_paging(invoke, graph):
      routes = mock_graph(graph, "search/message")   # two POST /search/query responses (moreResultsAvailable then not)
      r = invoke("search", "budget", "--after", "2026-08-01", "--before", "2026-08-31", "--all", "--json")
      assert r.exit_code == 0, r.stderr
      first = json.loads(routes[0].calls[0].request.content)
      assert first == {"requests": [{"entityTypes": ["message"], "query": {"queryString": "budget received>=2026-08-01 received<=2026-08-31"}, "from": 0, "size": 25}]}
      assert json.loads(routes[0].calls[1].request.content)["requests"][0]["from"] == 25
      doc = json.loads(r.stdout); assert doc["count"] == 30 and doc["truncated"] is False
      assert doc["items"][0]["resource"]["subject"] == "Budget review"
      text = invoke("search", "budget").stdout
      assert text.splitlines()[0].split() == ["id", "received", "subject", "from", "webUrl"]
  ```
  Also: `test_search_type_columns` (event → `id start subject organizer webUrl`; driveItem → `id modified name author webUrl`; person → `id name email title`); `test_search_chat_message_uses_shape_chat_hit` (`where` column `chat:…`/`channel:…`); `test_search_client_side_dates_for_events` (`--type event --after …` filters on `start.dateTime`); `test_search_fields_option` (`"fields": ["subject", "from"]`); `test_search_scope_gate_by_type` (`scopes(["Mail.Read"])`: `--type driveItem` → exit 3 `needs Sites.Read.All`, no request; `--type message` → ok); `test_search_limit_and_cap` (`--limit 5` → one call, 5 items, `truncated: true` when `moreResultsAvailable`; `--all` stops at 200); `--limit 0` → 2; `test_search_is_a_top_level_command` (`invoke("search")` → exit 2 usage: missing Q). Commit `feat(mgraphctl): add unified search command`.
- [ ] **Finish:** full suite, lint.

## Phase 2 — docs (K ‖ L; both run after every Phase 1 task has merged, because they enumerate the real verb list)

### Task 18: K — `SKILL.md`, `reference/commands.md`   (Phase 2, parallel with T19, depends on: T8–T17)

**Files:** Create `plugins/mgraphctl/skills/mgraphctl/SKILL.md`, `plugins/mgraphctl/skills/mgraphctl/reference/commands.md`.
**Interfaces:** Consumes the registered command tree (`uv run mgraphctl --help`, `uv run mgraphctl <noun> --help`) and spec §8, §6.5, §6.6, §3, §4.1, §4.5, §9, §12. Produces the two documents T20's `test_docs.py` checks.

- [ ] **Step 1: Enumerate the surface.** From `$SCRIPTS`: `uv run python -c "from mgraphctl.cli import build_app; import typer.main; g = typer.main.get_group(build_app()); [print(k) for k in sorted(g.commands)]"` and `uv run mgraphctl <noun> --help` for each noun (and `mail drafts`, `mail rules`, `mailbox oof`, `teams channel`); this list is the source of truth for both files (every registered verb must appear in `commands.md` verbatim as `noun verb` or `noun sub verb`).
- [ ] **Step 2: Write `reference/commands.md`.** One `##` section per noun in registry order plus `## Top-level` first (`login logout status claims me version api search`); per verb a `###` heading with the exact command form, a table `Option | Default | Meaning` (all options from §8 incl. `--json`/`--dry-run`), the Graph call(s) as in §8, `Scopes:` line (the declared list, `A|B` shown as "A or B", on-demand scopes marked), `Tier:` (P0/P1/P2), and `Notes:`; then `## Argument resolution` reproducing §6.6's table (lines 356–371) and `## Paging defaults` reproducing §5.3's table (lines 229–242), `## Exit codes` (§6.5 table) and `## Environment variables` (§3 table). No shell variables other than `${CLAUDE_PLUGIN_ROOT}`; every example is the full canonical path.
- [ ] **Step 3: Write `SKILL.md`** (≤ 400 lines; `wc -l` must print ≤ 400). Frontmatter verbatim from spec §12 (lines 726–743: `name`, the multi-line `description`, `allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/mgraphctl *)`, `metadata.author`, `metadata.version: "0.1.0"`). Sections in this order, each stating the rule spec §12 assigns to it (lines 745–759): **Setup** (uv is the only prerequisite; first run 10–40 s with a stderr notice; every example spells out `${CLAUDE_PLUGIN_ROOT}/mgraphctl <noun> <verb>`; no aliases or shell variables because `allowed-tools` matches the literal prefix and env does not persist between Bash calls); **Login and status** (always run `status` first; exit 3 = not logged in; on `NOT_LOGGED_IN`/`CONSENT_REQUIRED` tell the user the exact command to run in their own terminal, stop and wait; never run `login`; never retry in a loop; relay `MISSING_SCOPE` hints verbatim); **Command cheat-sheet** (one block per noun listing verbs with the 1–2 most common flag combinations; link to `reference/commands.md`); **Recipes** (inbox triage; schedule a meeting; find a file; DM someone; transcript to summary incl. `meetings insights` when Copilot-licensed; to-do from mail; post to a channel; the two §1 recipes: org summary composed from `org manager` + `org reports` + `people search`, and `transcripts --insights` by date/subject via `meetings list --subject … --resolve` then `meetings insights MID`); **Guardrails** (the seven rules of §12 verbatim, incl. the full list of write verbs that require `--dry-run` → show → confirm → run); **Output conventions** (JSON envelopes; text chronological for messages vs JSON Graph order; datetimes carry offsets; `truncated` note on stderr); **Exit codes** (§6.5 table verbatim); **Environment variables** (§3 user-facing rows); **Scopes and consent** (`default` vs `extended`; the P2 verb list; admin-consent note; on-demand scopes with `--scope`); **Differences from the `msgraph` (Node) skill** (§9 highlights: mode flags → noun verb, `sharepoint --file-url` → `sharepoint url`, `transcripts` → `meetings`, `mail list` defaults to Inbox — `--folder all` for Node's behaviour, exit codes differ).
- [ ] **Step 4: Verify.** `wc -l plugins/mgraphctl/skills/mgraphctl/SKILL.md` ≤ 400; `grep -c 'CLAUDE_PLUGIN_ROOT' SKILL.md` ≥ 20; `python3 scripts/scan_secrets.py` from `$ROOT` green; `claude plugin validate .` from `$ROOT` passes (frontmatter parses).
- [ ] **Step 5: Commit.** `git add plugins/mgraphctl/skills/mgraphctl/SKILL.md plugins/mgraphctl/skills/mgraphctl/reference/commands.md && git commit -m "docs(mgraphctl): add SKILL.md and command reference"`.

### Task 19: L — `README.md`, `CHANGELOG.md`, marketplace entry   (Phase 2, parallel with T18, depends on: T8–T17)

**Files:** Create `plugins/mgraphctl/README.md`, `plugins/mgraphctl/CHANGELOG.md`; modify `/.claude-plugin/marketplace.json`. Verify (do not edit) `plugins/mgraphctl/.claude-plugin/plugin.json` (T1).
**Interfaces:** Consumes spec §2.1, §13, the house style of `plugins/msgraph/README.md` and `plugins/msgraph/CHANGELOG.md`.

- [ ] **Step 1: Write `README.md`** in the style of `plugins/msgraph/README.md` (short paragraphs, `##` sections): what it is (Python re-implementation of `msgraph` with the §1 extensions; original design, no upstream); **Install** (`claude plugin marketplace add svd/mgraphctl`, `claude plugin install mgraphctl@mgraphctl`); **Prerequisite: uv** (`curl -LsSf https://astral.sh/uv/install.sh | sh`, `brew install uv`, `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`); **First run and login** (`status`, `login`, browser flow, `--device-code`, the Windows/no-bash invocation from §2.5 line 100); **Where things live** (venv under `${CLAUDE_PLUGIN_DATA}` or `~/.cache/mgraphctl/venv`; token cache `~/.mgraphctl/token_cache.json` 0600); **Scopes** (`default`, `extended`, on-demand, admin-consent URL); **Differences from `msgraph`**; **Troubleshooting** (`uv` missing; first-run slowness; `CONSENT_REQUIRED`; device code blocked by Conditional Access; proxies via `HTTPS_PROXY`; `MGRAPHCTL_TZ`); **Development** (`cd plugins/mgraphctl/skills/mgraphctl/scripts && uv sync && uv run pytest`, `uv run ruff check src tests`); **Provenance and licence** (original to this repository; MIT, `LICENSE` at the repo root).
- [ ] **Step 2: Write `CHANGELOG.md`** (house style: `# Changelog`, `## [Unreleased]`, flat bullets, no sub-headings):
  ```markdown
  # Changelog

  ## [Unreleased]

  - Initial Python implementation of the `msgraph` skill as `mgraphctl`: a typer CLI run with `uv`
    (msal sign-in, httpx with retries and paging, offline pytest suite).
  - Parity with every `msgraph` mode: mail, calendar, availability, SharePoint (sites, browse, download,
    `url`), OneDrive, Teams chats and channels, hosted content, people, contacts, org chart, OneNote,
    Planner, To Do, meetings and transcripts, AI insights.
  - Extensions: mail triage (`mark`, `move`, `delete`, `folders`, drafts, rules, categories), mailbox
    settings and automatic replies, `getSchedule`/`findMeetingTimes`, chats find-or-create DM, presence,
    SharePoint lists and upload, OneDrive item writes and sharing links, unified `search`, raw `api`.
  - Every write verb supports `--dry-run`; stable exit codes (0/1/2/3/4); data commands never open a browser.
  ```
- [ ] **Step 3: Add the marketplace entry** to `/.claude-plugin/marketplace.json` after the `msgraph` entry (spec §2.1):
  ```json
  {
    "name": "mgraphctl",
    "source": "./plugins/mgraphctl",
    "description": "Work with Microsoft 365 — Outlook mail and calendar, Teams chats and channels, presence, meetings and transcripts, SharePoint, OneDrive, OneNote, Planner, To Do, people and org chart — through the Microsoft Graph API (Python CLI run with uv).",
    "category": "productivity"
  }
  ```
- [ ] **Step 4: Validate.** From `$ROOT`: `python3 scripts/validate_marketplace.py`, `python3 scripts/scan_secrets.py`, `claude plugin validate .` — all green; `diff <(python3 -c "import json;print(json.load(open('plugins/mgraphctl/.claude-plugin/plugin.json'))['version'])") <(cd plugins/mgraphctl/skills/mgraphctl/scripts && uv run python -c "import mgraphctl;print(mgraphctl.__version__)")` empty.
- [ ] **Step 5: Commit.** `git add plugins/mgraphctl/README.md plugins/mgraphctl/CHANGELOG.md .claude-plugin/marketplace.json && git commit -m "docs(mgraphctl): add README, changelog and marketplace entry"`.

## Phase 3 — integration (single task)

### Task 20: Integration verification   (Phase 3, sequential, depends on: T18, T19)

**Files:** Create `tests/test_docs.py`; no other file changes unless a check fails (fix in place, keep the commit focused).
**Interfaces:** Consumes everything.

- [ ] **Step 1: Write `tests/test_docs.py`:**
  ```python
  """Every registered verb is documented in reference/commands.md and SKILL.md stays within 400 lines."""

  from pathlib import Path

  from test_surface import walk

  SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "mgraphctl"


  def test_every_verb_in_commands_md(app):
      text = (SKILL_DIR / "reference" / "commands.md").read_text()
      missing = [v for v in walk(app) if f"`{v}" not in text and f" {v} " not in text]
      assert not missing, missing


  def test_skill_md_length_and_prefix():
      lines = (SKILL_DIR / "SKILL.md").read_text().splitlines()
      assert len(lines) <= 400
      assert sum("${CLAUDE_PLUGIN_ROOT}/mgraphctl" in line for line in lines) >= 20
  ```
- [ ] **Step 2: Full suite.** `cd $SCRIPTS && uv run pytest -q` → all pass (includes `test_surface.py` coverage and `--json` checks, `test_docs.py`).
- [ ] **Step 3: Lint and lock.** `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv lock --check` (lock up to date with `pyproject.toml`), `git status --short` shows nothing untracked under `scripts/` except intended files.
- [ ] **Step 4: Shim end-to-end (offline replay).** `rm -rf /tmp/mgraphctl-venv-e2e`; then with `UV_PROJECT_ENVIRONMENT=<that path>` and `MGRAPHCTL_FIXTURE_DIR=$SCRIPTS/tests/fixtures/replay` exported: `$SCRIPTS/mgraphctl status` → stdout `Logged in as: fixture-user@example.com` (plus `Token expires`, `Scopes: default (23)`, `Cache:` lines), exit 0, stderr contains the first-run notice; `$SCRIPTS/mgraphctl status --json` → `"loggedIn": true`; `$SCRIPTS/mgraphctl me --json` → JSON with `"userPrincipalName": "fixture-user@example.com"`, exit 0; `$SCRIPTS/mgraphctl me --json` a second time → exit 0 again (replay cursors are per process); `$SCRIPTS/mgraphctl mail list` → `error[FIXTURE_MISSING]: no fixture for GET /v1.0/me/mailFolders/inbox/messages?...` exit 1; `$SCRIPTS/mgraphctl` → help exit 0; `$SCRIPTS/mgraphctl mail` → help exit 0; `$SCRIPTS/mgraphctl --version` → `mgraphctl 0.1.0`. Confirm `find $SCRIPTS -name __pycache__ -not -path '*/.venv/*'` prints nothing and no file under `$SCRIPTS` changed (`git status --short`).
- [ ] **Step 5: Validators.** From `$ROOT`: `python3 scripts/validate_marketplace.py`, `python3 scripts/scan_secrets.py`, `claude plugin validate .` — all green.
- [ ] **Step 6: Version and changelog check.** `plugin.json`, `pyproject.toml`, `__init__.py` all say `0.1.0`; `CHANGELOG.md` has exactly one `## [Unreleased]` block with the five bullets; `SKILL.md` frontmatter `metadata.version: "0.1.0"`.
- [ ] **Step 7: Commit.** `git add plugins/mgraphctl/skills/mgraphctl/scripts/tests/test_docs.py && git commit -m "test(mgraphctl): check command reference coverage and skill length"`. If any earlier step required a fix, commit it separately as `fix(mgraphctl): <what>` before this one. Release itself (dating the changelog, `claude plugin tag`) is out of scope for this plan and follows `.claude/skills/releasing-a-version/SKILL.md`.

## Execution notes for the coordinator

**Dispatch order and batches.**
- Phase 0: T1 → T2 → {T3 ‖ T4 ‖ T5} → {T6 ‖ T7}. T6 and T7 touch disjoint files (`graph/__init__.py` may be created by either with the identical one-line docstring). T6 is the gate for Phase 1.
- Phase 1: {T8 ‖ T9 ‖ T10 ‖ T11 ‖ T12 ‖ T13 ‖ T14 ‖ T15 ‖ T16} then T17 (needs T11's `shape_chat_hit`). Each agent works in its own worktree branch from the Phase 0 merge commit; merges are conflict-free by construction (disjoint files; `commands/__init__.py` already lists every noun). Merge in any order; run `uv run pytest -q` after each merge — `test_surface.py` starts covering the newly registered verbs automatically.
- Phase 2: {T18 ‖ T19} after all of Phase 1 has merged.
- Phase 3: T20.

**What each subagent must read before starting** (in this order): (1) `docs/specs/2026-09-02-mgraphctl-design.md` §1–§7 in full, then the §8 rows and other sections cited in its task; (2) this plan's Global Constraints, Phase 0 contract, Shared patterns (a)–(e), and its own task text; (3) the real Phase 0 sources it consumes — `cli.py`, `http.py`, `render.py`, `errors.py`, `odata.py`, `resolve.py`, `auth.py` (only `require_scopes`, `get_access_token`, `decode_jwt`, `synthetic_token`), `graph/users.py`, `graph/files.py` (F, G), `tests/helpers.py`, `tests/conftest.py`, and one finished Phase 1 module as a worked example when available (`graph/mail.py` + `commands/mail.py` + `tests/test_cli_mail.py`); (4) `CONTRIBUTING.md` ground rules. Subagents write no `.md` files except T18/T19.

**Two-stage review per task** (reviewer is a separate agent; findings go back to the implementer; the coordinator does not fix):
1. *Spec compliance* — every §8 row of the task implemented with the exact path, query keys/values, headers (`Prefer`, `ConsistencyLevel`, `If-Match`), body shape, scopes and tier; `--dry-run` on every write; exit codes; JSON envelope shapes; text columns as listed; resolution rules per §6.6; paging numbers per §5.3; datetimes per §6.3; every verb has a `@covers` test, one P2 scope-gate test, one `--json` list and one `--json` object test; fixtures synthetic (`example.com`, `contoso.example`, `AAMk-…`, `19:…@thread.v2`), no real names/hosts/tokens.
2. *Code quality* — commands are thin (≤ ~40 lines, no HTTP, no JSON shaping beyond columns, return a `render` result, never print); no duplicated retry/paging/batch/upload logic outside `http.py` (every list goes through `client.paginate`, every multi-id write through `client.batch`, every download through `client.download`, every plan step through `client.execute`); `plan_`/`run_` pairs exist for writes; no cross-group imports beyond the allowed three; no `from __future__ import annotations` in `commands/*.py` or `cli.py`; no env reads outside `config.py`/`render.local_tz`; `ruff check` and `ruff format --check` clean; commit messages `type(mgraphctl): summary`, imperative, no trailers; nothing written under `scripts/` at runtime (no `__pycache__`, no stray files in `git status`).

**Verb coverage ledger** (all 118 registered verbs; each appears in exactly one task): T6 — `login logout status claims me version api` (7). T8 — mail `list read attachments send reply forward folders mark move delete`, `drafts list`, `drafts create`, `drafts send`, `rules list`, `categories`; mailbox `settings`, `oof get`, `oof set`, `focused` (19). T9 — calendar `list calendars get create update delete respond availability find-times` (9). T10 — people `search contacts contact users user photo`; org `manager reports chain`; groups `list members` (11). T11 — teams `list get members channels`, `channel get`, `channel messages`, `channel send`; chats `list get members messages send dm create search hosted-content`; presence `get set clear` (19). T12 — meetings `list get transcripts transcript insights recordings` (6). T13 — onedrive `ls search get download upload mkdir move rename delete share shared-with-me recent link` (13). T14 — sharepoint `sites site drives ls search download upload url lists items` (10). T15 — onenote `notebooks sections pages read create search` (6). T16 — planner `plans plan buckets tasks task create update complete delete`; todo `lists tasks task create update complete delete from-mail` (17). T17 — `search` (1). Total 7+19+9+11+19+6+13+10+6+17+1 = 118.
