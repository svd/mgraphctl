# mgraphctl command reference

Every verb the CLI registers, with its options, the Graph call it makes and the scopes it needs.
The verbs live one file per noun under `commands/`; this page holds the conventions they share and
the index that points at them. `SKILL.md` links here rather than repeating the option tables.

## How to read this file

Headings give the command *form* — `mail list`, `teams channel send`, `mailbox oof set`. To run
one, put the canonical path in front of it:

```bash
${CLAUDE_PLUGIN_ROOT}/mgraphctl mail list --unread --limit 10
${CLAUDE_PLUGIN_ROOT}/mgraphctl teams channel send TEAM CHANNEL --body "hi" --dry-run
```

There is no alias and no shorter spelling: `${CLAUDE_PLUGIN_ROOT}` is the only variable that ever
appears in a command line.

- **Scopes** — the scopes the local gate checks before the first request. "A or B" means either
  satisfies the gate. A scope marked *on-demand* is in neither named set; request it with
  `login --scope <name>`.
- **Beyond `default`** — this verb, or the part of it the line names, needs more than the
  `default` scope set: `login --scopes extended`, or the scope the **Scopes** line marks
  *on-demand*, requested with `login --scope <name>`. A verb without the line works with `default`.
- **Graph** — the call as sent. `{x}` is a resolved and URL-encoded id.
- Every verb accepts `--json`. Every verb that writes accepts `--dry-run`, which prints the
  request(s) it would send. `--dry-run` withholds the write; the GET lookups that turn names into
  ids (folder, calendar, team/channel, chat by UPN, section, plan/bucket, To Do list, assignee UPN,
  and the message read by `todo from-mail`) still run — pass ids (`id:`, GUID, `19:…`) for a fully
  offline dry run. `chats dm --dry-run` alone makes no request. A few read verbs post a query
  rather than fetch it (`calendar availability`, `calendar find-times`, `presence get USER`);
  they write nothing and have no `--dry-run`.
- `--limit` must be at least 1, and cannot be combined with `--all`. The default limit and the
  `--all` cap per verb are in **Paging defaults** at the end of this file.

## Global options

These come *before* the noun: `mgraphctl --tz Europe/Warsaw calendar list`.

| Option | Default | Meaning |
|---|---|---|
| `--debug`, `-d` | off | Log one line per request to stderr. Repeat (`-dd`) to add truncated bodies. |
| `--tz IANA` | `MGRAPHCTL_TZ`, else the config file, else the detected local zone | Time zone for `Prefer: outlook.timezone`, for naive datetime input, and for rendering. |
| `--config PATH` | `MGRAPHCTL_CONFIG`, else `~/.mgraphctl/config.toml` | The config file to read (see **Configuration** at the end of this file). |
| `--beta` | off | Send every relative path to `/beta` instead of `/v1.0`. |
| `--version` | — | Print `mgraphctl <version>` and exit 0. |
| `--help` | — | Help at every level. Running a noun with no verb prints that noun's help and exits 0. |

## Command files

Open the one file the task needs rather than reading every verb. Each file holds that noun's
verbs with their options, Graph call and scopes; the conventions above and the sections
below apply to all of them.

| File | Commands |
|---|---|
| [`commands/top-level.md`](commands/top-level.md) | `login`, `logout`, `status`, `claims`, `me`, `version`, `api`, `search` |
| [`commands/config.md`](commands/config.md) | `config path`, `config show`, `config init`, `config set`, `config unset` |
| [`commands/mail.md`](commands/mail.md) | `mail list`, `mail read`, `mail attachments`, `mail send`, `mail reply`, `mail forward`, `mail folders`, `mail mark`, `mail move`, `mail delete`, `mail drafts list`, `mail drafts create`, `mail drafts send`, `mail rules list`, `mail categories` |
| [`commands/mailbox.md`](commands/mailbox.md) | `mailbox settings`, `mailbox oof get`, `mailbox oof set`, `mailbox focused` |
| [`commands/calendar.md`](commands/calendar.md) | `calendar list`, `calendar calendars`, `calendar get`, `calendar create`, `calendar update`, `calendar delete`, `calendar respond`, `calendar availability`, `calendar find-times` |
| [`commands/people.md`](commands/people.md) | `people search`, `people contacts`, `people contact`, `people users`, `people user`, `people photo` |
| [`commands/org.md`](commands/org.md) | `org manager`, `org reports`, `org chain` |
| [`commands/groups.md`](commands/groups.md) | `groups list`, `groups members` |
| [`commands/teams.md`](commands/teams.md) | `teams list`, `teams get`, `teams members`, `teams channels`, `teams channel get`, `teams channel messages`, `teams channel send` |
| [`commands/chats.md`](commands/chats.md) | `chats list`, `chats get`, `chats members`, `chats messages`, `chats send`, `chats dm`, `chats create`, `chats search`, `chats hosted-content` |
| [`commands/presence.md`](commands/presence.md) | `presence get`, `presence set available`, `presence clear` |
| [`commands/meetings.md`](commands/meetings.md) | `meetings list`, `meetings get`, `meetings transcripts`, `meetings transcript`, `meetings insights`, `meetings recordings` |
| [`commands/onedrive.md`](commands/onedrive.md) | `onedrive ls`, `onedrive search`, `onedrive get`, `onedrive download`, `onedrive upload`, `onedrive mkdir`, `onedrive move`, `onedrive rename`, `onedrive delete`, `onedrive share`, `onedrive shared-with-me`, `onedrive recent`, `onedrive link` |
| [`commands/sharepoint.md`](commands/sharepoint.md) | `sharepoint sites`, `sharepoint site`, `sharepoint drives`, `sharepoint ls`, `sharepoint search`, `sharepoint download`, `sharepoint upload`, `sharepoint url`, `sharepoint lists`, `sharepoint items` |
| [`commands/onenote.md`](commands/onenote.md) | `onenote notebooks`, `onenote sections`, `onenote pages`, `onenote read`, `onenote create`, `onenote search` |
| [`commands/planner.md`](commands/planner.md) | `planner plans`, `planner plan`, `planner buckets`, `planner tasks`, `planner task`, `planner create`, `planner update`, `planner complete`, `planner delete` |
| [`commands/todo.md`](commands/todo.md) | `todo lists`, `todo tasks`, `todo task`, `todo create`, `todo update`, `todo complete`, `todo delete`, `todo from-mail` |

## Argument resolution

Positional resource arguments take an id or a human name. A name that matches nothing is
`error[NOT_FOUND]`, exit 4; a name that matches two or more is `error[AMBIGUOUS]`, exit 2, with the
candidates listed on stderr — narrow it, or pass the id. `id:<value>` forces the value to be read
as an id; a leading `/` forces a drive path.

| Argument | Read as an id when | Otherwise looked up as |
|---|---|---|
| `mail --folder` | `all` (the whole mailbox), a well-known name (`inbox`, `drafts`, `sentitems`, `deleteditems`, `junkemail`, `archive`, `outbox`, `clutter`, `conversationhistory`, `msgfolderroot`), or 40+ characters with no spaces | exact `displayName` among `/me/mailFolders` and one level of child folders |
| `TEAM` | a GUID | case-insensitive `displayName` in `/me/joinedTeams` |
| `CHANNEL` | starts with `19:` | `displayName` in the team's channels |
| `CHAT` | starts with `19:` | a value containing `@` finds the 1:1 chat with that user |
| `USER` / `UPN` | a GUID, a value containing `@`, or `me` | a directory search, which needs `User.ReadBasic.All` |
| `SITE` | an `https://…` URL, a `host:/sites/name` reference, or a composite id containing `,` | `GET /sites?search=<name>`, matched on `displayName` |
| `--drive` | a drive id (`b!…`) | `name` among the site's drives |
| `--calendar` | 40+ characters with no spaces | case-insensitive `name` in `/me/calendars` |
| drive `ID\|PATH` | an `id:` prefix, or 20+ id characters with no `.` or `/` | a path in the drive |
| `NOTEBOOK` / `SECTION` / `PAGE` | contains `!`, or starts with a digit and a dash | `displayName` or `title` in the parent listing |
| `PLAN` / `BUCKET` | a 28-character Planner id | `title` or `name` among your plans, or the plan's buckets |
| `todo LIST` | an `AQMk…`/`AAMk…` prefix, or 40+ characters | `defaultList`, `flaggedEmails`, or `displayName` in `/me/todo/lists` |
| `GROUP` | a GUID | `displayName` among the groups you belong to |
| `MEETING` | the positional online-meeting id | `--join-url URL` filters on `JoinWebUrl`; `--event ID` reads the event's join URL first |

## The list envelope

Every `--json` listing is `{"items", "count", "fetched", "cap", "truncated"}`, plus `"window"` and
`"query"` on the commands that have them.

| Key | Meaning |
|---|---|
| `items` | the results |
| `count` | how many `items` holds |
| `fetched` | how many items Graph returned, before any client-side pass. Always present; equal to `count` when nothing was filtered, so nothing has to branch on the key |
| `cap` | the bound the fetch ran under: `--limit`, or the verb's cap under `--all`. `null` where nothing paged |
| `truncated` | whether results the caller asked for were left behind |
| `window` | `{"after", "before"}` as ISO strings or `null`, on every command that accepts a time window — present even when both bounds are unset, absent entirely on commands that accept none |
| `query` | the server-side query actually sent (`$search`/`$filter`/`$orderby`, or the Search API's `entityTypes` and `query`), so a consumer can report its own coverage honestly |

`cap`, `fetched` and `truncated` always describe the **fetch**, never the filtered list. Where a
command filters client-side — `mail list`'s unread and time passes, `chats list --since`,
`chats search`'s date bounds, `teams channel messages`' window — `fetched` exceeds `count`, and a
page can come back shorter than `--limit` while `truncated` is still true. Commands with no date
options (`onedrive`, `sharepoint`, `teams list`, …) emit no `window` key at all.

## Paging defaults

`--limit` bounds a normal run; `--all` replaces it with the cap and is mutually exclusive with it.
Text mode prints `(more results available — rerun with --all)`, `(more results available —
raise --limit)` on a verb with no `--all`, or `(hit the <cap>-item cap — narrow the query)`
after an `--all` run, on stderr; JSON sets `"truncated": true`.

A default of "all" means the verb has no `--limit` and fetches everything up to the cap; a cap of
"—" means the verb has no `--all`. Those verbs still stop at an internal maximum — 200 items for
`onedrive shared-with-me` and `onedrive recent`, 500 for the OneNote lists.

| Verb | Page size | Default `--limit` | `--all` cap |
|---|---|---|---|
| `mail list` (search mode / filter mode) | 25 / 50 | 10 | 500 |
| `mail drafts list` | 50 | 20 | 500 |
| `mail folders` | 100 | all | 500 |
| `mailbox focused` | 50 | 25 | 500 |
| `calendar list` | 50 | 50 | 200 |
| `calendar calendars` | 100 | all | 500 |
| `people search`, `people contacts` | 50 | 20 | 250 |
| `people users`, `groups list`, `groups members` | 100 | 20 | 999 |
| `org reports` | 100 | 20 | 500 |
| `teams list`, `teams channels` | none | all | 999 |
| `teams members` | 50 | 100 | 999 |
| `teams channel messages` | 50 | 20 | 200 |
| `chats list`, `chats messages` | 50 | 20 | 200 |
| `chats search`, `search`, `sharepoint search` | 25 | 25 | 200 |
| `onedrive ls`, `sharepoint ls` | 200 | 50 | 1000 |
| `onedrive search` | 200 | 50 | — |
| `onedrive shared-with-me` | none | 50 | — |
| `onedrive recent` | none | 20 | — |
| `sharepoint sites` | 100 | 20 | — |
| `sharepoint items` | 200 | 50 | 500 |
| `onenote pages` | 100 | 50 | 500 |
| `onenote notebooks`, `onenote sections`, `onenote search` | 100 | 50 | — |
| `todo tasks` | 100 | 50 | 500 |
| `planner plans`, `planner tasks`, `meetings list` | none (sliced client-side) | 50 | — |

## Exit codes

| Exit | Meaning | Sources |
|---|---|---|
| 0 | success | includes empty lists and the `meetings insights` 403 soft path |
| 1 | runtime error | a Graph error other than 401/403/404, local I/O, fixture errors, failed uploads |
| 2 | usage | parse errors, a bad datetime, `--limit 0`, a missing required combination, an ambiguous name |
| 3 | auth or permission | `NOT_LOGGED_IN`, a failed refresh, `MISSING_SCOPE`, `CONSENT_REQUIRED`, `LOGIN_TIMEOUT`, HTTP 401/403 |
| 4 | not found | HTTP 404, and a name that resolved to nothing |

One error per run, on stderr:

```
error[<CODE>]: <message>
  request-id: <id>          (when Graph returned one)
  hint: <one actionable sentence>
```

`<CODE>` is Graph's own `error.code` (`ErrorItemNotFound`, `InefficientFilter`, `Forbidden`, …) or
an internal one: `NOT_LOGGED_IN`, `MISSING_SCOPE`, `CONSENT_REQUIRED`, `AMBIGUOUS`, `NOT_FOUND`,
`USAGE`, `FIXTURE_MISSING`, `UPLOAD_SESSION_LOST`.

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `MGRAPHCTL_CLIENT_ID` | none; required | Entra application (public client) to authenticate as. Unset → `login` and `status` fail with `error[CONFIG]: client_id is not set` (exit 2) and a hint naming `config set client_id`. |
| `MGRAPHCTL_TENANT_ID` | `common` | Authority `https://login.microsoftonline.com/<tenant>`. |
| `MGRAPHCTL_SCOPES` | `default` | `default`, `extended`, or an explicit scope list. `login --scopes` overrides it. |
| `MGRAPHCTL_TOKEN_CACHE` | `~/.mgraphctl/token_cache.json` | The file cache (mode 0600), and the keychain item's account name. |
| `MGRAPHCTL_TOKEN_STORE` | `auto` | `auto` (the OS keychain when one works, else the file), `keyring` (the keychain, falling back to the file with a warning), or `file`. |
| `MGRAPHCTL_TZ` | the detected local zone | IANA zone for `Prefer: outlook.timezone`, naive input, and rendering. `--tz` overrides it. |
| `MGRAPHCTL_DEBUG` | unset | `1` behaves like `--debug`. |
| `MGRAPHCTL_RETRIES` | `4` | Retries after the first attempt on 429/503/504 and connection failures; `0` disables them. A 401 still re-authenticates once. |
| `MGRAPHCTL_TIMEOUT_MS` | `60000` | Read/write timeout. Uploads and downloads get 5× it. |
| `MGRAPHCTL_RETRY_BASE_MS` | `1000` | Base of the exponential backoff, and of its jitter. |
| `MGRAPHCTL_FIXTURE_DIR` | unset | Replay recorded responses and bypass authentication (developer tool). |
| `MGRAPHCTL_RECORD` | unset | `1`, with `MGRAPHCTL_FIXTURE_DIR`, records live responses. |
| `NO_COLOR`, `COLUMNS` | — | Honoured by the text renderer. |
| `HTTPS_PROXY`, `HTTP_PROXY` | — | Honoured by the HTTP client. |
| `MGRAPHCTL_CONFIG` | `~/.mgraphctl/config.toml` | The config file; `--config` overrides it. |

## Configuration file

Every `MGRAPHCTL_*` variable above except `MGRAPHCTL_CONFIG`, `MGRAPHCTL_FIXTURE_DIR` and
`MGRAPHCTL_RECORD` can also be set in the config file, as the variable name without the prefix
in lower case. Precedence is flag, then environment variable, then file, then the default.
`mgraphctl config init` writes a commented template, `config set KEY VALUE` and
`config unset KEY` edit one key, and `config show` prints the effective value and source of
every key.

```toml
# ~/.mgraphctl/config.toml
tenant_id     = "contoso.onmicrosoft.com"
scopes        = "extended"
tz            = "Europe/Warsaw"
token_store   = "auto"
retries       = 2
timeout_ms    = 30000
```
