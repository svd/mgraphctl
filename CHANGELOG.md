# Changelog

## [Unreleased]

- An MCP server, `mgraphctl mcp serve`, exposing the CLI's verbs as tools to any MCP client. The
  tool set is generated from the command tree, so a new verb is a new tool; `mcp tools` prints
  what would be exposed. Needs the optional dependency `mgraphctl[mcp]`.
  - `--capabilities mail,calendar,teams` picks the command groups to expose, because all 123 verbs
    at once would cost the client a great deal of context. Default:
    `core,mail,calendar,people,chats`. `all` covers everything but `api`.
  - Read-only unless `--allow-write`. Tools carry the MCP behaviour annotations too, but those are
    hints to the host, not the gate.
  - `--json` has no tool equivalent: `output_format` chooses the compact table or the full payload
    as structured content, and `output_file` writes the result under `--output-dir` and links it.
    Results past `--max-inline-bytes` are written and linked regardless, so one wide fetch cannot
    flood the client. Written files are readable back as MCP resources.
  - Protocol revision `2026-07-28`, plus the earlier revisions the SDK negotiates. No deprecated
    feature is implemented: no HTTP+SSE transport, no protocol sessions, no GET stream, no
    resumable streams.
  - `--transport http` binds loopback only and requires a bearer token and an allowed `Origin`.
    The server acts as one signed-in user and cannot authenticate callers, so it does not pretend
    to be an OAuth resource server; `stdio` is the recommended transport. README explains why.
  - Every path a tool argument names is confined to `--output-dir`, including files a verb reads
    (`--attach`, `--body-file`) rather than writes, and the server runs from inside that directory
    so a verb's own default destination cannot land elsewhere. A downloaded file that is not text
    reads back through `resources/read` as a blob.
  - The root flags carry into the server: `mgraphctl -dd mcp serve` logs every tool call's Graph
    request to stderr, and `--tz` / `--beta` apply the same way they do on the command line.
- `render.emit` splits into `to_text`, `notes` and `to_json`, so a caller that does not own stdout
  can render a result. The CLI's output is unchanged.
- `auth.app()` and `auth.save_cache()` take a lock. The CLI is single-threaded, but the MCP server
  runs tool calls on worker threads, where a racing lazy build could bind an msal app to a cache
  that is never written back — silently dropping a refreshed token.

## [0.3.0] — 2026-09-07

- Add a Codex plugin manifest and repository marketplace. Claude Code and Codex share the
  bundled CLI and skill, with host-specific command-path instructions and one release version.

## [0.2.1] — 2026-09-06

- The skill's command reference is one file per noun. `reference/commands.md` keeps the
  conventions every verb shares — argument resolution, the list envelope, paging defaults, exit
  codes, environment variables — and indexes `reference/commands/<noun>.md`, so answering a
  question about one noun reads roughly a tenth of what the single 87 KB file cost. `api` and
  `search` move from the `config` section to `top-level.md`, where they belong.
- SKILL.md documents the `config` verbs, which the cheat-sheet had omitted, and no longer
  compares the CLI with the Node `msgraph` skill: the "Differences from" section is gone, as are
  the P0/P1/P2 parity tiers. Where a verb needs more than the `default` scope set it now says so
  in place, as `Beyond \`default\`:`; a verb without that line works with `default`.
- The README links the skill's command documentation.

## [0.2.0] — 2026-09-06

- The plugin runs under the Claude desktop app. The supported Python floor drops to 3.10
  (`requires-python = ">=3.10,<3.14"`), so the shim and the PyPI package install on a 3.10
  interpreter, which is what the desktop app offers. The two stdlib features that pinned 3.11
  are gone: `tomllib` is imported from the `tomli` backport below 3.11, and `datetime.UTC`
  became `datetime.timezone.utc`. CI runs the suite on 3.10 through 3.13; `main`'s required
  checks now include `test (3.10)`.

## [0.1.0] — 2026-09-05

- `login`, `status` and every silent token acquisition stop with `error[CONFIG]: client_id is
  not set` (exit 2) and a hint naming `config set client_id` / `MGRAPHCTL_CLIENT_ID` when the
  client id is still the placeholder, instead of surfacing Entra's AADSTS700016. The README
  now says a client id must be configured before the first login.
- The msal token cache lives in the OS keychain (macOS Keychain, Windows Credential Locker,
  Linux Secret Service) as one `mgraphctl` item when a backend is available, via `keyring`.
  `token_store = auto | keyring | file` in the config file, or `MGRAPHCTL_TOKEN_STORE`, picks;
  `auto` is the default and uses the `0600` file silently where no keychain exists. An existing
  `token_cache.json` is imported on the first run and deleted once the keychain holds it. A
  keychain that fails at runtime falls back to the file for that run with one warning.
  `logout` clears both. `login`, `status` and `logout` print which store is in use and carry a
  `store` field in JSON. Windows caps a credential at 2560 bytes, so the item is split there;
  that path is covered by tests but has not been exercised on a Windows machine.
- An optional config file, `~/.mgraphctl/config.toml` (`--config PATH` or `MGRAPHCTL_CONFIG`
  to relocate it). Every `MGRAPHCTL_*` setting except the fixture knobs can be set there under
  its lower-cased name; a flag beats an environment variable, which beats the file.
  `config init` writes a commented template, `config set KEY VALUE` / `config unset KEY` edit
  one key in place (comments survive), `config show` prints each effective value with its
  source, `config path` prints the location. Invalid TOML fails every command with
  `error[CONFIG]`.
- Initial Python implementation of the `msgraph` skill as `mgraphctl`: a typer CLI run with `uv`
  (msal sign-in, httpx with retries and paging, offline pytest suite).
- Parity with every `msgraph` mode: mail, calendar, availability, SharePoint (sites, browse,
  download, `url`), OneDrive, Teams chats and channels, hosted content, people, contacts, org
  chart, OneNote, Planner, To Do, meetings and transcripts, AI insights.
- Extensions: mail triage (`mark`, `move`, `delete`, `folders`, drafts, rules, categories),
  mailbox settings and automatic replies, `getSchedule`/`findMeetingTimes`, chats find-or-create
  DM, presence, SharePoint lists and upload, OneDrive item writes and sharing links, Microsoft 365
  groups (`groups list`, `groups members`), unified `search`, raw `api`.
- Every write verb supports `--dry-run`; stable exit codes (0/1/2/3/4); data commands never open
  a browser.
- `mail list` search mode now re-filters the page on `receivedDateTime` when `--after`/`--before`
  carry a time of day, so a bound like `--after 2026-09-02T14:00` no longer returns the whole of
  2026-09-02. Date-only bounds are unaffected.
- `teams channel messages` takes `--after`/`--before`, so a channel hit from `search` or
  `chats search` can be followed up over a time window. The window is applied client-side on the
  reply chain's last-modified time, and paging stops at the first message older than `--after`;
  Graph documents no `$filter` support on that endpoint, and an unsupported one is either rejected
  or silently ignored.
- `chats messages` takes `--before`, symmetric to `--after`.
- `chats list` takes `--since`, stopping the fetch at the first chat whose last message predates
  it. Text mode then shows a `lastMessage` column with the timestamp the bound is measured against.
- Every `--json` listing now carries `fetched` (items Graph returned before any client-side pass),
  `cap` (the bound the fetch ran under) and `query` (the server-side query actually sent), and the
  commands that accept a time window carry `window: {after, before}` — present even when both
  bounds are unset, absent on commands with no date options. `cap`, `fetched` and `truncated`
  describe the fetch, never the filtered list. Text output is unchanged.
- `meetings transcript --speakers` renders the transcript as speaker turns, merging each
  speaker's consecutive cues into one `**Speaker:** …` paragraph.
- `meetings transcript --json` now reports `createdDateTime`, looked up best-effort and left
  `null` when the lookup fails.
- Chat messages carry `chatId`, and channel messages and replies carry `teamId`/`channelId`,
  which Graph omits when they are fetched through their own collection — so a message in JSON can
  be routed back to the thread it came from.
- `chats search` hits carry structured `kind`/`chatId`/`teamId`/`channelId` beside the `where`
  text column, so a hit can be followed into `teams channel messages --after …` without parsing
  `where` apart. A hit with no routing reports `kind: "unknown"`.
- `MGRAPHCTL_RETRIES`, `MGRAPHCTL_TIMEOUT_MS` and `MGRAPHCTL_RETRY_BASE_MS` tune retrying and
  timeouts; `MGRAPHCTL_RETRIES=0` disables the 429/503/504 and connection-failure retries (a
  401 still re-authenticates once, which is not a retry). An unusable value takes the
  default rather than failing the command. The long timeout for uploads and downloads keeps its
  multiplier off whatever base is configured.
- An eval suite at `skills/mgraphctl/evals/evals.json`, covering triggering and the surfaces
  above.

### Fixed

- `fmt_dtz` printed a literal `(None)` beside an unformatted Graph timestamp when the
  `dateTimeTimeZone` object carried no `timeZone`. An absent or empty zone now reads as UTC,
  which is Graph's documented default when no `Prefer: outlook.timezone` was sent — reachable
  through `calendar availability`, search event hits and the mailbox out-of-office block. A
  Windows zone name still renders verbatim.
- `meetings transcript` reported the format that was asked for rather than the one it got. The
  speaker-attribution fallback answers in plain text even to a vtt request, so `--format vtt`
  could label plain text as `vtt`; the format is now sniffed from the body, on the `--output` path
  too. The JSON field `text` is renamed `content`, matching the Node skill.

- `chats messages --after` never actually filtered. It sent `$filter=createdDateTime gt …`
  alongside `$orderby=createdDateTime desc`, but Graph supports `gt` on chat messages only for
  `lastModifiedDateTime` and ignores a `$filter` whose property `$orderby` does not name. Both now
  use `lastModifiedDateTime`, so the bounds mean when a message was last touched.
