# msgraph (Node.js) — feature inventory

Date: 2026-09-02
Source read: the `msgraph` Node plugin checkout (`plugins/msgraph` in its marketplace repo; original checkout,
including the **uncommitted** working-tree changes to `skills/msgraph/scripts/msgraph.js` and the
**untracked** `tests/` directory). Purpose: source of truth for a Python re-implementation that must
reach feature parity — command surface, stdout shape, Graph calls, and quirks.

Files inventoried:

| File | Size | Tracked in git? |
|---|---|---|
| `.claude-plugin/plugin.json` | small | yes |
| `README.md`, `CHANGELOG.md` | small | yes |
| `skills/msgraph/SKILL.md` | 509 lines | yes |
| `skills/msgraph/README.md`, `skills/msgraph/LICENSE` | small | yes |
| `skills/msgraph/scripts/msgraph.js` | 2291 lines (HEAD: 2191) | yes, **modified (uncommitted)** |
| `skills/msgraph/evals/evals.json` | 6 evals | yes |
| `tests/helpers.js`, `tests/compat.test.js`, `tests/fixture-mode.test.js` | 3 files | **untracked** |
| `tests/fixtures/compat/<slug>/<hash>.json` (13 fixtures), `tests/fixtures/snapshots/*.snap` (25 snapshots) | — | **untracked** |
| `.gitignore` (repo root) | — | **modified (uncommitted)**: ignores `plugins/msgraph/tests/fixtures/live/` |

No `package.json` exists anywhere (plugin, skill, scripts, or repo root).

---

## 1. Launch, dependencies, platform

| Aspect | Value |
|---|---|
| Entry point | `node ${CLAUDE_PLUGIN_ROOT}/skills/msgraph/scripts/msgraph.js <command> [--flags]` (every SKILL.md example uses this form) |
| Shebang | `#!/usr/bin/env node` (file mode 644 — not executable; always launched via `node`) |
| Node version | Comment says `node >= 18`. Uses `node:`-prefixed built-ins, optional chaining, `??`, `base64url` Buffer encoding, `Buffer.subarray`. Verified working on Node 26.7.0. |
| npm dependencies | **Zero.** Built-ins only: `crypto`, `http`, `https`, `fs`, `path`, `os`, `child_process.execFile`. |
| Module shape | Single 2291-line CommonJS script; `'use strict'`; `main()` runs unconditionally at load → the file **cannot be `require()`d** (tests spawn it as a subprocess). |
| Platform assumptions | Home dir via `os.homedir()`; browser launch: darwin `open <url>`, win32 `cmd /c start "" <url>`, else `xdg-open <url>`. Loopback HTTP server on `localhost` random port. Unicode box-drawing + emoji in text output. ANSI colour only in `claims` when stdout is a TTY. |
| Proxy support | None (Node `https` ignores `HTTPS_PROXY`). |
| CI | `.gitlab-ci.yml` runs only the two Python validators; the Node tests are **not** run in CI. |

---

## 2. CLI surface

### 2.1 Argument parser (`parseArgs`)

- `argv[0]` is the command; the rest is parsed.
- Any token starting with `--` is a flag. Key = text after `--`, kebab-case → camelCase (`--team-id` → `teamId`, `--hosted-content` → `hostedContent`, `--dry-run` → `dryRun`, `--my-tasks` → `myTasks`, `--teams-list` → `teamsList`, `--file-url` → `fileUrl`, `--attachment-id` → `attachmentId`, `--resolve-site` → `resolveSite`, `--site-file` → `siteFile`, `--lookup-user` → `lookupUser`, `--chat-id` → `chatId`, `--message-id` → `messageId`, `--channel-id` → `channelId`, `--plan-id` → `planId`, `--bucket-id` → `bucketId`, `--task-id` → `taskId`, `--list-id` → `listId`).
- **Boolean set** (never consumes a value): `json unread sites chats teamsList contacts manager reports availability notebooks list vtt help force plans buckets tasks myTasks lists insights all full attachments dryRun`.
- Any other flag consumes the next token as its value **unless** there is no next token or the next token starts with `--`, in which case the value is `true`. (`--messages` is deliberately *not* boolean: `teams --messages CHAT_ID` takes a value; `channels --messages` alone resolves to `true`.)
- Tokens not starting with `--` go to `args._` (never used by any command).
- Not supported: `--key=value`, short aliases, negative/`--`-prefixed values, repeated flags (last wins), unknown-flag errors (silently accepted). `--help` is parsed but no command honours it.
- Numeric flags use `parseInt(x) || default` — non-numeric or `0` falls back to the default.

### 2.2 Commands (18 entries in `COMMANDS`)

`login`, `logout`, `status`, `claims`, `me`, `emails`, `calendar`, `sharepoint`, `teams`, `channels`, `onedrive`, `people`, `org`, `onenote`, `planner`, `todo`, `transcripts`, `help`.

No arguments at all → help, exit 0. Unknown command → `Unknown command: X` on stderr + help on stdout, exit 1.
Within a command, mode selection is by **flag presence in a fixed order** (documented per command below); when no mode matches, most commands print a short usage block to **stdout** and exit **0**.

### 2.3 Output formats

- Default: human text (aligned columns via `padEnd`/`pad()`, `─`/`═` rules, emoji markers). Column widths are load-bearing for the snapshot tests (see per-command notes).
- `--json`: `JSON.stringify(x, null, 2)` on stdout, exactly one document. Supported on most read modes; **not** on: `login`, `logout`, `status`, `emails --send`, `emails --read --attachment-id`, `calendar --create`, `calendar --availability`, `teams --lookup-user`, `teams --dm`, all `--send`s, `onedrive --upload/--download`, `org` (flag documented in help but ignored), `planner --create/--complete`, `todo --create/--complete`, `transcripts --meeting --transcript`.
- Diagnostics (pagination notes, errors, mismatch notes) go to **stderr**.
- No `--table`/`--csv`/`--yaml`; no quiet/verbose flags.

### 2.4 Exit codes

| Code | When |
|---|---|
| 0 | Success; help; usage block printed for a missing mode; `status` in *any* state (including `NOT_LOGGED_IN` / `TOKEN_EXPIRED`); AI-insights 403 (prints licence message and returns) |
| 1 | Any thrown error (HTTP or otherwise, via `main()`'s handler); explicit `process.exit(1)` validations (missing `--start/--end`, missing `--team-id`/`--channel-id`, missing `--section`, `--site-file` without `--path`, bad `--file-url`, bad `--hosted-content`, missing upload file, missing Planner etag, no DM chat found, output dir missing); unknown command |
| 2 | `claims` when no cached token (`NOT_LOGGED_IN — run: node msgraph.js login`) — the **only** place exit 2 is used, despite SKILL.md's table |

### 2.5 Central error rendering (`main()` catch)

| Condition | stderr text |
|---|---|
| `err.statusCode === 401` | `Error: Authentication expired. Run: node msgraph.js login` |
| 403 | `Error: Permission denied (<url>)` + `You may need additional OAuth scopes.` |
| 404 | `Error: Resource not found (<url>)` |
| other status | `HTTP Error <n>: <first 200 chars of body>` |
| no status | `Error: <message>` |

Error objects carry `statusCode`, `responseBody`, `responseUrl` (set by `httpsRequest` and `graphDownload`).

---

## 3. Authentication

| Aspect | Value |
|---|---|
| Flow | OAuth 2.0 **Authorization Code + PKCE (S256)**, public client, system browser, loopback redirect (RFC 8252). Not device-code, not client-credentials. Rationale in header comment: lets Enterprise SSO extension (macOS/Intune) / WAM (Windows) attach device claims for Conditional Access. |
| Client ID | `00000000-0000-0000-0000-000000000000` (hard-coded; not overridable) |
| Tenant | `common` → `https://login.microsoftonline.com/common/oauth2/v2.0/authorize` and `/token` |
| Redirect URI | `http://localhost:<random port>` — `http.createServer().listen(0, 'localhost')`; app registration must allow loopback |
| Scopes (23, space-joined, sent on authorize, code exchange **and** refresh) | `User.Read Mail.Read Mail.Send Calendars.Read Calendars.ReadWrite Files.Read Files.ReadWrite Sites.Read.All Sites.ReadWrite.All Chat.Read Chat.ReadWrite ChannelMessage.Read.All ChannelMessage.Send OnlineMeetingTranscript.Read.All OnlineMeetings.Read People.Read Contacts.Read offline_access Notes.Read Notes.ReadWrite OnlineMeetingAiInsight.Read.All Tasks.ReadWrite Group.Read.All` |
| Authorize params | `client_id, response_type=code, redirect_uri, scope, state (16 random bytes hex), code_challenge, code_challenge_method=S256, prompt=select_account` (`prompt=login` with `login --force`) |
| PKCE | verifier = 32 random bytes base64url; challenge = sha256(verifier) base64url |
| Browser | URL always printed; opener failure only warns (`Warning: could not open browser automatically: …`) |
| Callback server | Waits up to `TIMEOUT_MS` = 5 min → `Authentication timed out (5 minutes). Run login again.`; ignores requests without `code`/`error` (404); responds 200 HTML success page (`✓ Authentication successful`, `window.close()`) or failure page (escaped `error` / `error_description`); state mismatch → `State mismatch — possible CSRF. Login aborted.` |
| Code exchange | POST token: `client_id, grant_type=authorization_code, code, redirect_uri, code_verifier, scope`. Missing `access_token` → `Token exchange failed: <json>` |
| Post-login | `GET /me?$select=userPrincipalName,displayName,id`; prints `Logged in as: <displayName> <<upn>>`, `User ID     : <id>`, `Token cached: <path>` |
| Cache file | `~/.ms_graph_token_cache.json`, written with mode `0600`, pretty JSON: `{ access_token, refresh_token, expires_at (unix seconds = now + expires_in, default 3600), username }`. Plaintext; single account; no keychain. |
| Validity check | token considered valid while `now < expires_at - 60` |
| Refresh | POST token `client_id, grant_type=refresh_token, refresh_token, scope`; on success rewrites cache (keeps old refresh token if none returned). Any failure is swallowed (`catch {}`) → returns null. |
| `getAccessToken()` (all data commands) | valid cache → token; else refresh; **else falls through to a full interactive `pkceLogin()`** (opens a browser from any command). |
| `tryGetToken()` (`status` only) | same but returns `null` instead of prompting |
| `login` | already valid and no `--force` → `Already logged in as: <username>` / `Use --force to re-authenticate.` |
| `logout` | deletes the cache file only (`Logged out. Cache removed: <path>` or `No cached credentials found.`); no server-side revocation |
| `status` | prints `Logged in as: <username>` + `Cache file: <path>`; or `NOT_LOGGED_IN` + `\nTo login, run:\n  node msgraph.js login`; or `TOKEN_EXPIRED` + `Account: <username>` + re-auth hint. Always exit 0. |
| `claims [--json]` | Decodes the cached JWT payload locally (no signature check). Text mode: boxed header with UPN, sections IDENTITY (UPN/`unique_name`, oid, tid, iat, exp + `(expires in Nm)`/`(EXPIRED)`), DEVICE CLAIMS (`deviceid`/`device_id` ✓/✗ with warning text, `join_type`, `mdm_compliance_url`), AUTH METHODS (`amr`), SCOPES (`scp` sorted, 2 columns × 26 chars). Colours only when TTY. |
| 401 mid-command | No automatic refresh/retry — rendered as "Authentication expired", exit 1. |
| Fixture replay (uncommitted) | `getAccessToken`/`tryGetToken` return `fixture-mode-dummy-token`; `status` prints `Logged in as: fixture-user@example.com`. |

---

## 4. HTTP layer (shared helpers)

| Helper | Behaviour |
|---|---|
| `httpsRequest(url, {method, headers}, body)` | Raw `https.request`; buffers whole body as UTF-8; status ≥ 400 → rejects with `Error('HTTP <n>')` + `statusCode/responseBody/responseUrl`; resolves `{status, body, headers}`. **No timeout, no retry, no 429/Retry-After handling, no 5xx backoff.** |
| `oauthPost(url, params)` | form-urlencoded POST, returns parsed JSON |
| `graphGet(endpoint, token, params)` | `GET ${GRAPH_BASE}${endpoint}?${URLSearchParams(params)}`; endpoint path is interpolated **verbatim (not URL-encoded)**; returns parsed JSON |
| `graphGetAll(endpoint, token, params, cap=200)` | Follows `@odata.nextLink` until exhausted or `cap` items; returns `{items (sliced to cap), truncated (true if stopped with a nextLink pending)}`. Used only by `emails` and `calendar`. |
| `graphPost(endpoint, token, body)` | JSON POST with `Content-Length`; empty body → `{}` |
| `graphPatch(endpoint, token, body, extraHeaders)` | JSON PATCH (used for Planner with `If-Match`, To Do); empty body → `{}` |
| `graphDownload(endpoint\|absoluteUrl, token)` | `https.get`; follows 301/302/303/307/308 up to 5 hops and **drops the Authorization header on redirect** (Graph pre-authenticated storage URLs 401 with a bearer); any ≥300 without `Location` → error (body truncated to 2000 chars); returns a `Buffer` (whole file in memory) |
| `graphUpload(endpoint, token, buffer, contentType='application/octet-stream')` | single `PUT` (simple upload; no upload session → Graph's 4 MB simple-upload limit applies) |
| Base URLs | `GRAPH_BASE = https://graph.microsoft.com/v1.0`; `GRAPH_BETA = https://graph.microsoft.com/beta` (beta used **only** as the aiInsights fallback) |
| Query encoding | Node `URLSearchParams` (form-urlencoded): space → `+`, `$` → `%24`, `,` → `%2C`, `'` → `%27`, `"` → `%22`, `~` → `%7E`, **`*` left as-is**. Python `urllib.parse.urlencode` differs: encodes `*` → `%2A`, leaves `~`. This matters for `sharepoint --sites` fallback (`search=*`) and for fixture-hash parity. |
| Not used anywhere | `$batch`, delta queries, `$count`, `Prefer: outlook.timezone`, `Prefer: outlook.body-content-type`, ETags except Planner, streaming downloads, upload sessions |

---

## 5. Command reference (Graph coverage)

Column key: **Mode** = flag combination selecting the branch (listed in the order the code tests them); **Endpoint** = path under `/v1.0` unless stated; **Notes** = output shape, defaults, caveats.

### 5.1 `login` / `logout` / `status` / `claims`

| Mode | Args/flags | Endpoint | Notes |
|---|---|---|---|
| `login` | `[--force]` | `POST login.microsoftonline.com/common/oauth2/v2.0/token`; `GET /me?$select=userPrincipalName,displayName,id` | See §3. |
| `logout` | — | none | Deletes cache file. |
| `status` | — | token refresh only (if expired) | See §3. |
| `claims` | `[--json]` | none | Local JWT decode; exit 2 if not logged in, 1 if undecodable. |

### 5.2 `me`

| Mode | Args/flags | Endpoint | Notes |
|---|---|---|---|
| default | `[--json]` | `GET /me` (no `$select`) | Text: `Name/Email/Job Title/Department/Office/Phone/User ID` (labels padded to 11 chars, `N/A` fallbacks; phone = `businessPhones[0] \|\| mobilePhone`). JSON: only the keys `displayName,userPrincipalName,id,mail,jobTitle,department,officeLocation,businessPhones,mobilePhone` that are non-null. |

### 5.3 `emails`

Mode order: `--send` → `--read` (`--attachment-id` → `--attachments` → body) → list.

| Mode | Args/flags | Endpoint / params | Notes |
|---|---|---|---|
| send | `--send TO --subject S --body B` | `POST /me/sendMail` body `{message:{subject, body:{contentType:'Text',content}, toRecipients:[{emailAddress:{address}}]}}` | Subject default `(no subject)`, body default `''`. **One** recipient, text only, no cc/bcc/attachments/saveToSentItems flag. Prints `Email sent to <to>`. No `--json`. `--send` wins over `--read` if both given. |
| read one attachment | `--read ID --attachment-id AID [--output FILE]` | `GET /me/messages/{id}/attachments/{aid}` | If `contentBytes` (fileAttachment): `--output` → writes decoded bytes (**no** `assertOutputDir`), prints `Attachment saved to <f> (<name>, <size>)`; else if `contentType` starts `text/` or name ends `.txt/.md/.csv/.json/.vtt` → prints UTF-8 content; else prints `<name>  <contentType>  <size>  (binary — pass --output FILE to save)`. No `contentBytes` → `Non-file attachment: {name, contentType}` JSON. No `--json` handling. |
| list attachments | `--read ID --attachments [--json]` | `GET /me/messages/{id}/attachments?$select=id,name,contentType,size,isInline` | Text rows: `<id>  <name padEnd 40>  <contentType[0:30] padEnd 30>  <size>[  (inline)]`; `No attachments.` |
| read body | `--read ID [--full] [--output FILE] [--json]` | `GET /me/messages/{id}?$select=id,subject,from,toRecipients,ccRecipients,receivedDateTime,isRead,hasAttachments,body,bodyPreview,conversationId,webLink` | JSON → raw message. Text: `Subject  :`, `From     : <name> <<addr>>`, `To       :` (comma-joined addresses), `Cc       :` (only if any), `Date     :` (`fmtDt`), `Read     : Yes/No`, `Attach   : Yes (--attachments to list)/No`, blank line + 60×`─`, then body: `body.content` if `contentType==='text'` else `stripHtml(html)`. `--output` → writes **full** text (`Full body saved to <f> (<n> chars)`, no dir check); else prints first 2000 chars unless `--full`, then `\n… truncated (<n> chars total; use --full for the whole body).` |
| list | `[--limit N=10] [--folder NAME] [--search Q] [--from ADDR] [--to ADDR] [--after DATE] [--before DATE] [--unread] [--all] [--json]` | endpoint `/me/messages` or `/me/mailFolders/{folder}/messages` (folder verbatim: well-known name or id). `$select=id,subject,from,toRecipients,ccRecipients,receivedDateTime,isRead,hasAttachments,importance,bodyPreview`. **Search mode** (any of `--from/--to/--search`): `$search="<terms joined ' AND '>"` with terms `<q>`, `from:<addr>`, `to:<addr>`, `received>=<YYYY-MM-DD>`, `received<=<YYYY-MM-DD>`; `$top=min(limit,25)`; no `$orderby`. **Filter mode**: `$top=min(limit,25)`, `$orderby=receivedDateTime desc`, `$filter` = `receivedDateTime ge <iso>` / `receivedDateTime le <iso>` / `isRead eq false` joined ` and `. | Pagination: `graphGetAll` when `--all` or `limit>25` or (search mode + `--unread`); cap = 500 if `--all` or unread-search, else `limit`. Otherwise single page; `truncated` = nextLink present. Unread-in-search-mode is filtered **client-side** then sliced to `limit` (unless `--all`). stderr when truncated: `(hit the 500-item pagination cap — narrow the date window to see more)` with `--all`, else `(more results available — rerun with --all to paginate through everything)`. Text: blank line, header `ID` padEnd 36 + 2sp + `Date` padEnd 16 + `  Rd  Subject`, 80×`─`, rows `<id[0:36]>  <fmtDt padEnd 16>  <✓|●>   <📎|2sp> <subject[0:45] or '(no subject)'>  (<from.name[0:20]>)`. `No emails found.` |

### 5.4 `calendar`

Mode order: `--create` → `--availability` → list.

| Mode | Args/flags | Endpoint / params | Notes |
|---|---|---|---|
| create | `--create TITLE --start DT --end DT [--timezone TZ=UTC] [--location L] [--body B] [--attendees a@x,b@y]` | `POST /me/events` `{subject, start:{dateTime,timeZone}, end:{…}, location:{displayName}?, body:{contentType:'Text',content}?, attendees:[{emailAddress:{address}, type:'required'}]?}` | Missing start/end → stderr `Error: --create requires --start and --end (format: YYYY-MM-DDTHH:MM)` exit 1. Prints `Event created: <subject>` + `ID: <id>`. No `--json`, no online-meeting flag, no reminders/recurrence. `--attendees`/`--body` undocumented in SKILL.md/help. |
| availability | `--availability [--start DT] [--end DT]` | `GET /me/calendarView?startDateTime&endDateTime&$select=subject,start,end,showAs&$orderby=start/dateTime` (no `$top` → server default page) | Defaults: start = `now.toISOString().slice(0,19)` (UTC, no `Z`); end = local today 23:59 converted to UTC ISO, sliced to 19 chars. Prints `You're free between <s[0:16]> and <e[0:16]>.` or `Busy slots (<n> events):` + `  <fmtDt start> — <fmtDt end>: <subject>`. Ignores `showAs` (free/tentative count as busy). No `--json`. Does not use `getSchedule`/`findMeetingTimes`. |
| list | `[--limit N=10] [--after DATE] [--before DATE] [--search KW] [--all] [--json]` | `GET /me/calendarView` with `startDateTime/endDateTime`, `$select=id,subject,start,end,location,organizer,attendees,isOnlineMeeting,onlineMeeting,isCancelled,bodyPreview,lastModifiedDateTime`, `$orderby=start/dateTime`, `$top` | Window: with `--after`/`--before`: `toIsoBound(after \|\| '2000-01-01')` … `toIsoBound(before \|\| '2100-01-01', endOfDay)`; else now (UTC) … Jan 1 of next local year (UTC ISO, `Z` appended). Fetch: if `--all`/`--after`/`--before`/`--search` → `graphGetAll` with `$top=25`, cap = 500 if (`--all` or `--search`) else `max(limit,50)`; else single `GET` with `$top=limit`. `--search` filters **client-side** (case-insensitive substring on subject, organizer name, attendee name/address). Sliced to `limit` when not `--all` and (`--limit` given explicitly or no window). Truncation notes as for emails. Text: header `Date & Time` padEnd 20 + 4sp + `Title`, 80×`─`, rows `<fmtDt(start.dateTime) padEnd 20>  <🎥|2sp>  <subject[0:45]>  (<organizer.name[0:20]>)[  @ <location[0:20]>][  [CANCELLED]]`. `No events found.` **No `Prefer: outlook.timezone`** → Graph returns zone-less UTC strings, which `fmtDt` parses as *local* time (see §9). |

### 5.5 `sharepoint` (`--limit` default 20)

Mode order: `--file-url` → `--resolve-site` → `--sites` → `--site` → `--download` → `--site-file` → usage.

| Mode | Args/flags | Endpoint / params | Notes |
|---|---|---|---|
| file-url | `--file-url 'URL' [--output PATH] [--dry-run] [--json]` | 1) `GET /sites/{host}:/sites/{name}` (or `/teams/`, `/personal/`, or bare `/sites/{host}` for root-site URLs) `$select=id,displayName,webUrl`; 2) `GET /sites/{siteId}/drives?$select=id,name,webUrl`; 3) `GET /drives/{driveId}/root:/{encoded path}:/content` or fallback `GET /sites/{siteId}/drive/root:/{encoded path}:/content` (with and then without the first segment) | `parseSharePointFileUrl`: https only; drops query/hash; decodes each segment separately; skips sharing prefixes (`/:w:/r/` etc.) by finding the first `sites|teams|personal` segment; builds `siteRef = host:/<kind>/<name>`. Library chosen by matching drive `webUrl` segments as a strict prefix of the file path (deepest wins) — never by library name (localisation). Only a 404 moves to the next attempt. `--dry-run` prints JSON `{siteRef, siteId, siteName, driveName, driveId, relPath, output, libraryMatched, fallbackAttempts}` and makes no download. Default output = file basename. 403 on `/personal/` → hint about sharing + `onedrive --download`. Text success: `Downloaded <n> bytes to <out>  (<size>)` + `  site: <name>   library: <drive\|(default)>   path: <rel>`; `--json` → `{siteId, siteName, driveId, driveName, path, output, bytes}` only. `--file-url` with no value → exit 1 with quoting hint. |
| resolve-site | `--resolve-site HOST:/sites/NAME [--json]` | `GET /sites/{ref}?$select=id,displayName,webUrl` (ref verbatim) | Text `ID  :`, `Name:`, `URL :`. |
| sites | `--sites [--json]` | `GET /me/followedSites?$select=id,displayName,webUrl`; if empty → `GET /sites?search=*&$top=<limit>` | Text: header `ID` padEnd 50 + `  Name`, 80×`─`, per site `<id padEnd 50>  <displayName>` + `  URL: <webUrl>`; sliced to `limit`. |
| site browse | `--site SITE_ID [--path P] [--json]` | `GET /sites/{id}/drive/root/children` or `/sites/{id}/drive/root:/{P}:/children` (`P` verbatim, not encoded) `$top=<limit>&$select=id,name,size,lastModifiedDateTime,file,folder` | Text: `Files in site <id> / <p>:`, 60×`─`, rows `  <📁|📄> <name pad 40> <size pad 10> <fmtDt modified>` — **item IDs are not printed** in text mode. |
| download | `--download ITEM_ID [--output FILE]` | `GET /me/drive/items/{id}/content` | **Uses the signed-in user's OneDrive drive, not a site drive.** Default name `downloaded_<id[0:8]>`; `assertOutputDir`; prints `Downloaded <bytes> bytes to <path>`. |
| site-file | `--site-file SITE_ID --path FILE_PATH [--output LOCAL]` | `GET /sites/{id}/drive/root:/{path}:/content` (path verbatim) | Missing `--path` → exit 1. Default name = basename(path). |
| usage | — | — | 5 lines starting `SharePoint: --resolve-site HOSTNAME_PATH`, exit 0. |

### 5.6 `teams` (`--limit` default 20)

Mode order: `--hosted-content` → `--search` → `--chats` → `--lookup-user` → `--dm`+`--send` → `--messages` → `--send`+`--chat-id` → `--teams-list` → usage.

| Mode | Args/flags | Endpoint / params | Notes |
|---|---|---|---|
| hosted content | `--hosted-content 'URL'` or `--hosted-content ID --chat-id C --message-id M`; `[--output FILE] [--json]` | `GET <path from URL after /v1.0 or /beta, verbatim>` (must contain `/hostedContents/`; `/$value` appended if missing) or `GET /chats/{c}/messages/{m}/hostedContents/{id}/$value` via `graphDownload` | Host must be `graph.microsoft.com`. Extension sniffed from magic bytes (`.png .jpg .gif .webp .pdf .svg`, else `.bin`). Default name `teams_hosted_<sha1(endpoint)[0:8]><ext>`; ext appended to `--output` lacking one; mismatch → stderr `(note: bytes look like .png, saving as .jpg anyway)` (`.jpeg`≡`.jpg`). Text: `Downloaded <n> bytes to <out>  (<PNG|binary>, <size>)`; `--json` → `{output, bytes, type}`. |
| search | `--search Q [--after DATE] [--before DATE] [--limit N=100 (max 200)] [--json]` | `POST /search/query` `{requests:[{entityTypes:['chatMessage'], query:{queryString}, from, size:25}]}`, looping while `moreResultsAvailable` and `hits.length < fetchCap` (200 when a date bound is given, else `limit`) | Records `{id, chatId (resource.chatId ?? channelIdentity.channelId), createdDateTime, from (emailAddress.name ?? user.displayName ?? 'Unknown'), fromAddress, body: hit.summary, webLink}`. Date filter client-side on `createdDateTime` as instants (records with no date pass). Text: `Teams search "<q>" — <n> result(s)[ (date-filtered)]:`, 80×`─`, `[<fmtDt>] <from>: <summary>` + `  chat: <chatId>  msg: <id>`. Empty → `No Teams messages found for "<q>".` |
| chats | `--chats [--json]` | `GET /me/chats?$top=<limit>&$select=id,topic,chatType,lastUpdatedDateTime` | Header `Chat ID` padEnd 50 + 2sp + `Type` padEnd 10 + `  Topic`, 80×`─`, rows `<id padEnd 50>  <chatType padEnd 10>  <topic \|\| '(direct message)'>`. |
| lookup user | `--lookup-user EMAIL` | `GET /users/{email}?$select=id,displayName,userPrincipalName,jobTitle,department`; `GET /me?$select=id` | Prints Display Name/Email/AAD User ID/Job Title/Department, `Your AAD ID`, and guidance to run `--chats` / `--dm`. No `--json`. |
| dm | `--dm EMAIL --send MSG` | `GET /users/{email}?$select=id,displayName`; `GET /me/chats?$top=50&$select=id,topic,chatType`; `POST /me/chats/{chatId}/messages` `{body:{content}}` (text) | Finds a `oneOnOne` chat whose id contains the user's oid among the **50 most recent chats**; none → stderr + exit 1 (cannot create a chat). Prints `DM sent to <name>. Message ID: <id>`. |
| messages | `--messages CHAT_ID [--full] [--limit N] [--json]` | `GET /me/chats/{id}/messages?$top=<limit>` (no `$select` — Graph 400s) | JSON = raw page (newest first). Text: `Messages in chat <id[0:20]>...:`, 60×`─`, **reversed** (oldest first) `[<fmtDt>] <from.user.displayName \|\| 'System'>: <stripHtml(body)[0:200 unless --full]>`. |
| send | `--send MSG --chat-id ID` | `POST /me/chats/{id}/messages` `{body:{contentType:'html', content}}` | Prints `Message sent. ID: <id>`. HTML, unescaped. |
| teams list | `--teams-list [--json]` | `GET /me/joinedTeams?$select=id,displayName,description` | Rows `<id[0:36]>  <displayName>`. |
| usage | — | — | 4 lines starting `Teams: --chats | --messages CHAT_ID [--full] | --send MSG --chat-id ID`, exit 0. |

### 5.7 `channels` (`--team-id` required; `--limit` default 20)

Mode order: (no `--team-id` → error exit 1) → `--list` → (no `--channel-id` → error exit 1) → `--messages` → `--replies` → `--send` → usage.

| Mode | Args/flags | Endpoint / params | Notes |
|---|---|---|---|
| list | `--team-id T --list [--json]` | `GET /teams/{t}/channels?$select=id,displayName,description` | Header `ID` padEnd 50 + `  Name`, 80×`─`, rows `<id padEnd 50>  <displayName \|\| 'N/A'>`. |
| messages | `--team-id T --channel-id C --messages [--limit N] [--json]` | `GET /teams/{t}/channels/{c}/messages?$top=<limit>&$expand=replies` | Text reversed, `[<fmtDt>] <sender>: <stripHtml(body)[0:200]>`; **no `--full`**. JSON includes expanded `replies`. |
| replies | `--team-id T --channel-id C --replies MSG_ID [--json]` | `GET /teams/{t}/channels/{c}/messages/{m}/replies?$top=50` | `--limit` is **ignored** (help claims `[--limit N]`). Filters out `messageType==='unknownFutureValue'` and `deletedDateTime` set. Reversed, 200-char bodies. |
| send | `--team-id T --channel-id C --send MSG` | `POST /teams/{t}/channels/{c}/messages` `{body:{contentType:'html', content}}` | `Message sent. ID: <id>`. Cannot reply into a thread (no reply endpoint despite README wording). |
| usage | — | — | 4 lines, exit 0 (but missing `--team-id` prints usage to stdout and exits 1). |

### 5.8 `onedrive` (`--limit` default 20)

Mode order: `--upload` → `--download` → `--info` → list.

| Mode | Args/flags | Endpoint / params | Notes |
|---|---|---|---|
| upload | `--upload FILE [--dest PATH]` | `PUT /me/drive/root:/{dest}:/content` (octet-stream, whole file in memory, dest verbatim) | Missing file → `File not found: <f>` exit 1. Default dest = basename. Prints `Uploaded: <name> (<size>)` + `ID: <id>`. No upload session (>4 MB fails), no `--json`, no conflict behaviour flag. |
| download | `--download ITEM_ID [--output FILE]` | `GET /me/drive/items/{id}/content` | Default `download_<id[0:8]>`; `assertOutputDir`; prints `Downloaded <size> to <path>` (note: formatted size, unlike `sharepoint --download` which prints raw bytes). |
| info | `--info ITEM_ID [--json]` | `GET /me/drive/items/{id}` | Text `Name    :`, `Size    :`, `Modified:`, `URL     :`. |
| list | `[--path P] [--json]` | `GET /me/drive/root/children` or `/me/drive/root:/{P}:/children` (verbatim) `$top=<limit>&$select=id,name,size,lastModifiedDateTime,file,folder&$orderby=name` | Text `OneDrive: /<p>`, 60×`─`, rows `  <📁|📄> <id[0:16]>  <name pad 40> <size pad 10> <fmtDt>[  (<childCount> items)]`. Empty → `No files found in /<p>`. |

### 5.9 `people` (`--limit` default 20)

| Mode | Args/flags | Endpoint / params | Notes |
|---|---|---|---|
| contacts | `--contacts [--search Q] [--json]` | `GET /me/contacts?$top=<limit>&$select=displayName,emailAddresses,mobilePhone,jobTitle,companyName[&$search="Q"]` | Header `Name` padEnd 30 + 2sp + `Email` padEnd 35 + `  Title`, 80×`─`, rows `<name pad 30>  <emailAddresses[0].address \|\| 'N/A' pad 35>  <jobTitle>`. |
| people | `[--search Q] [--json]` | `GET /me/people?$top=<limit>[&$search="Q"]` | Same table using `scoredEmailAddresses[0].address`. `No people found.` |

### 5.10 `org`

| Mode | Args/flags | Endpoint | Notes |
|---|---|---|---|
| manager | `--manager` | `GET /me/manager` | `Manager: <displayName> <<upn>>` + `Title  : <jobTitle>`; 404 → `No manager found (you may be at the top of the org).` |
| reports | `--reports` | `GET /me/directReports?$select=displayName,userPrincipalName,jobTitle` | `Direct Reports (<n>):` + `  <name pad 30>  <upn>`. |
| summary | (none) | `GET /me/manager` (errors swallowed); `GET /me/directReports?$select=displayName`; `GET /me/people?$top=5` | `Manager: <name>`, `Direct Reports: <n>`, `Frequent colleagues:` + 5 names. |
| — | `--json` | — | Listed in help; **ignored** by all three modes. |

### 5.11 `onenote` (`--limit` default 20)

Mode order: `--notebooks` → `--sections` → `--pages` → `--read` → `--search` → `--create` → usage.

| Mode | Args/flags | Endpoint / params | Notes |
|---|---|---|---|
| notebooks | `--notebooks [--json]` | `GET /me/onenote/notebooks?$top&$select=id,displayName,lastModifiedDateTime` | Header `ID` padEnd 36 + 2sp + `Modified` padEnd 18 + `  Name`, 80×`─`. |
| sections | `--sections NOTEBOOK_ID [--json]` | `GET /me/onenote/notebooks/{id}/sections?$top&$select=id,displayName,lastModifiedDateTime` | `Sections in notebook <id[0:20]>...:` + `ID` padEnd 36 + `  Name`, 70×`─`. |
| pages | `--pages SECTION_ID [--json]` | `GET /me/onenote/sections/{id}/pages?$top&$select=id,title,lastModifiedDateTime` | `Pages in section <id[0:20]>...:`, header ID/Modified/Title, 80×`─`; `(untitled)`. |
| read | `--read PAGE_ID [--json]` | `GET /me/onenote/pages/{id}/content` (raw HTML) | Text → `stripHtml(html)`; JSON → `{"id":…, "content": "<html>"}` (compact, not pretty). |
| search | `--search Q [--json]` | `GET /me/onenote/pages?$search="Q"&$top&$select=id,title,createdDateTime` | `Search results for "<q>" (<n>):`, ID/Title table, 70×`─`. |
| create | `--create TITLE --section SECTION_ID [--body HTML]` | `POST /me/onenote/sections/{id}/pages` with `Content-Type: text/html`, body `<!DOCTYPE html><html><head><title>TITLE</title></head><body>BODY</body></html>` | Title/body **not escaped**. Missing `--section` → exit 1. Prints `Page created: <title>` + `ID:`. |
| usage | — | — | 3 lines. |

### 5.12 `planner` (`--limit` default 20; **no OData params at all** — Planner returns 400 for `$top/$select/$filter`; lists are sliced client-side)

Mode order: `--plans` → `--my-tasks` → `--plan-id`+`--buckets` → `--plan-id`+`--create` → `--plan-id`+`--tasks` → `--complete` → `--task-id` → usage.

| Mode | Args/flags | Endpoint | Notes |
|---|---|---|---|
| plans | `--plans [--json]` | `GET /me/planner/plans` (needs `Group.Read.All`) | `Plan ID` padEnd 30 + `  Title`, 70×`─`. |
| my tasks | `--my-tasks [--json]` | `GET /me/planner/tasks` | Header `Task ID` padEnd 30 + 2sp + `%` padEnd 4 + 2sp + `Due` padEnd 16 + `  Title`, 80×`─`, rows `<id pad 30>  <percentComplete pad 4>  <fmtDt(due) pad 16>  <title>`. Only `planId/bucketId` ids, no names. |
| buckets | `--plan-id P --buckets [--json]` | `GET /planner/plans/{p}/buckets` | `Bucket ID` padEnd 30 + `  Name`. |
| create | `--plan-id P --create TITLE [--bucket-id B] [--due YYYY-MM-DD] [--assign USER_OID]` | `POST /planner/tasks` `{planId, title, bucketId?, dueDateTime:'<due>T00:00:00Z'?, assignments:{[oid]:{'@odata.type':'#microsoft.graph.plannerAssignment', orderHint:' !'}}?}` | `Task created: <title>` + `ID:`. Only when `--create` has a string value. |
| tasks | `--plan-id P --tasks [--json]` | `GET /planner/plans/{p}/tasks` | Same table as my-tasks. |
| complete | `--complete TASK_ID` | `GET /planner/tasks/{id}` → `@odata.etag`; `PATCH /planner/tasks/{id}` `{percentComplete:100}` with `If-Match: <etag>` | No etag → exit 1. `Task marked complete: <title>`. |
| task detail | `--task-id ID [--json]` | `GET /planner/tasks/{id}`; `GET /planner/tasks/{id}/details` (errors swallowed) | JSON `{...task, details}`. Text `Title      :`, `% Complete :`, `Due        :`, `Bucket ID  :`, `Plan ID    :`, optional `\nDescription:\n<text>`. |
| usage | — | — | 4 lines. |

### 5.13 `todo` (`--limit` default 20)

Mode order: `--lists` → (no `--list-id` → usage) → `--create` → `--complete` → `--tasks` → short usage.

| Mode | Args/flags | Endpoint | Notes |
|---|---|---|---|
| lists | `--lists [--json]` | `GET /me/todo/lists?$top=<limit>` | `List ID` padEnd 50 + `  Name`, 80×`─`. |
| create | `--list-id L --create TITLE [--body TEXT] [--due YYYY-MM-DD]` | `POST /me/todo/lists/{l}/tasks` `{title, body:{content, contentType:'text'}?, dueDateTime:{dateTime:'<due>T00:00:00.000000', timeZone:'UTC'}?}` | `Task created:` + `ID:`. |
| complete | `--list-id L --complete TASK_ID` | `PATCH /me/todo/lists/{l}/tasks/{t}` `{status:'completed'}` (no etag) | `Task marked complete: <id>`. |
| tasks | `--list-id L --tasks [--json]` | `GET /me/todo/lists/{l}/tasks?$top=<limit>` | Header `Task ID` padEnd 50 + 2sp + `Status` padEnd 12 + `  Title`, rows append `  (due <fmtDtTz>)`. |

### 5.14 `transcripts`

Mode order: `--insights` (any) → list (when `--list` or neither `--meeting` nor `--download`) → `--meeting` alone → `--meeting`+`--transcript` → usage.

| Mode | Args/flags | Endpoint / params | Notes |
|---|---|---|---|
| insights, direct | `--meeting MID --insights [--json]` | `GET /me?$select=id` (oid); `GET /copilot/users/{oid}/onlineMeetings/{mid}/aiInsights` (v1.0, **falls back to `/beta`** on 404); then per insight `GET …/aiInsights/{id}` (falls back to list item on error) | 403 → stderr `AI insights require a Microsoft 365 Copilot license (and transcription/recording enabled for the meeting).` **exit 0**; 404 → `No AI insights available for this meeting (none generated yet, or unsupported meeting type).`; empty → `No AI insights yet. Insights generate after the meeting ends and can take up to 4 hours.` Text per insight: 60×`═`, `AI Insight <id>  (<fmtDt created>)`, `Meeting Notes:` (`  • title` / `    text` / `      – subpoint title` / `        text`), `Action Items:` (`  ☐ title  (owner: X)`), `Mentions:` (`  @ <fmtDt eventDateTime> <speaker.user.displayName>: <transcriptUtterance[0:200]>`). JSON → array of full insight objects. |
| insights, resolved | `[--start D] [--end D] [--subject KW] --insights [--json]` | `GET /me/calendarView?startDateTime=<start>T00:00:00Z&endDateTime=<end>T23:59:59Z&$select=subject,start,isOnlineMeeting,onlineMeeting&$top=50&$orderby=start/dateTime`; per event `GET /me/onlineMeetings?$filter=joinWebUrl eq '<joinUrl>'`; then as above | Defaults: `start` = today−7d (date), **`end` = `start`** (single day). Keeps only `isOnlineMeeting && onlineMeeting.joinUrl`; `--subject` substring filter. Prints `Meeting: <subject>  (<fmtDt start>)  — <meetingId>` before each. `No matching online meetings found in range.` |
| list meetings | `[--start D] [--end D] [--subject KW] [--list] [--json]` | same calendarView call with `$select=id,subject,start,end,isOnlineMeeting,onlineMeeting`; with `--subject`: per meeting `GET /me/onlineMeetings?$filter=joinWebUrl eq '…'` and `GET /me/onlineMeetings/{id}/transcripts` | Without `--subject`: JSON = raw online events; text `Online meetings (<start> – <end>):`, 80×`─`, `  <fmtDt start padEnd 20>  <subject>`; `No online meetings found in range.` With `--subject`: text `Meeting: …`, `Start  : …`, `Meeting ID: …`, `Transcript ID: <id>  Created: <fmtDt>` / `No transcripts available for this meeting.` / error lines; JSON = `[{subject, start, meetingId, transcripts:[{id, createdDateTime}], error}]`; no match → `[]` / `No online meetings matching "<kw>" on <start>.` |
| list transcripts | `--meeting MID [--json]` | `GET /me/onlineMeetings/{mid}/transcripts` | `Transcripts for meeting <mid[0:30]>...:`, 60×`─`, `ID: <id>  Created: <fmtDt>`; `No transcripts found for this meeting.` |
| content | `--meeting MID --transcript TID [--output FILE] [--vtt]` | `GET /me/onlineMeetings/{mid}/transcripts/{tid}/content` with `Accept: text/plain` (or `text/vtt`) | Prints body or writes it (`Transcript saved to <f>`, no dir check). No `--json`. |
| usage | (e.g. `--download` without `--meeting`) | — | 3 lines. `--download` is referenced in the branch condition but never implemented. |

### 5.15 `help`

Prints the full usage text (reproduced in `printHelp()`, includes `Add --json to any command for machine-readable output.`), exit 0.

---

## 6. Cross-cutting behaviour

### 6.1 Configuration / environment

| Variable | Effect |
|---|---|
| `HOME` (via `os.homedir()`) | location of `~/.ms_graph_token_cache.json` |
| `MSGRAPH_FIXTURE_DIR` (**uncommitted**) | replay recorded responses instead of network; bypasses auth |
| `MSGRAPH_RECORD=1` (**uncommitted**, with `MSGRAPH_FIXTURE_DIR`) | real network, records each non-token response |
| `GENERATE_SNAPSHOTS=1` (tests only) | rewrite snapshot files instead of asserting |
| `CLAUDE_PLUGIN_ROOT` | used only in SKILL.md command strings |
| Not supported | client id / tenant / scopes / cache path overrides, proxy, timezone preference, verbosity |

### 6.2 Error handling, retries, timeouts
- Single central handler (§2.5). No retry on 429 or 5xx, no `Retry-After` parsing, no exponential backoff, no request timeout on Graph/OAuth calls (only the 5-minute login-callback timer). A hung request hangs the CLI.
- Some branches swallow errors deliberately: refresh failure, `org` summary manager lookup, Planner `/details`, per-insight fetch, meeting-id resolution (prints a line and continues).
- Validation failures print to stderr and `process.exit(1)` before any Graph call where the author cared (see `assertOutputDir`, which exists precisely because there is **no `mkdir` anywhere**).

### 6.3 Logging / verbosity
None. No debug flag, no request logging. stderr carries only errors and the pagination/mismatch notes.

### 6.4 HTML → text (`stripHtml`)
`(s||'').replace(/<[^>]*>/g,'')` → decode only `&nbsp; &amp; &lt; &gt;` → collapse blank lines (`\r?\n\s*\r?\n` → `\n`) → trim. Consequences: `<style>`/`<script>` **contents survive** as text; `<br>`, `<p>`, `<div>`, `<li>` produce no line breaks (HTML mail with no source newlines becomes one paragraph); `&quot; &#39; &#x27;` and numeric entities are left encoded. Used for mail bodies (when `body.contentType !== 'text'`), Teams/channel message bodies, OneNote page content.

### 6.5 Date / time handling
| Helper | Behaviour |
|---|---|
| `toIsoBound(input, endOfDay)` | `YYYY-MM-DD` → `YYYY-MM-DDT00:00:00Z` / `T23:59:59Z`; input containing `T` passed through, with `Z` appended if no zone suffix. |
| `toDateOnly(input)` | first 10 chars (for KQL `received>=`/`<=`, which compare on calendar date only). |
| `fmtDt(iso)` | `new Date(iso).toISOString().slice(0,16).replace('T',' ')` → `YYYY-MM-DD HH:MM` in **UTC**; `N/A` when empty. Because Graph calendar/transcript/insight `start.dateTime` values are zone-less (`2026-07-08T09:00:00.0000000`), V8 parses them as **local time**, so displayed times are shifted by the machine's UTC offset (verified: `09:00` renders as `06:00` at UTC+3, `07:00` in Europe/Berlin, `09:00` under `TZ=UTC`). |
| `fmtDtTz({dateTime,timeZone})` | appends `Z` when `timeZone==='UTC'` and no suffix, then `fmtDt` — used **only** for To Do due dates. |
| Defaults | `calendar` upcoming window = now → Jan 1 next local year; `transcripts` window = today−7d → **same day**; `calendar --availability` = now → local 23:59. |
| User timezone | Never read from Graph (`mailboxSettings`) and no `Prefer: outlook.timezone` header; `calendar --create` default `--timezone UTC`. SKILL.md ends with: "IMPORTANT: you must work with current date (get it from sh/bash)". |

### 6.6 Attachments, downloads, uploads, size limits
| Topic | Behaviour |
|---|---|
| Mail attachments | list (`$select=id,name,contentType,size,isInline`) and fetch one (`contentBytes` base64 → Buffer). Item/reference attachments not downloadable. No sending attachments. |
| Teams inline images | `hostedContents/{id}/$value` via `graphDownload`; type sniffed. Teams `reference` attachments are SharePoint files → `sharepoint --file-url '<contentUrl>'`. |
| Downloads | whole file buffered in memory; redirects followed without auth; `assertOutputDir` applied in `downloadToFile`, `onedrive --download`, `sharepoint --file-url`, `teams --hosted-content` — **not** in `emails --read --output`, `--attachment-id --output`, `transcripts --output`. `outputPath(value, fallback)` guards against a bare `--output` (parsed as `true`). |
| Upload | OneDrive only, simple PUT (Graph limit 4 MB), no session, no SharePoint upload. |
| Text truncation | mail body 2000 chars (`--full` lifts), Teams/channel message 200 chars (`--full` only for `teams --messages`), subject 45, sender 20, location 20, mention utterance 200, error body 200/2000. |
| Fetch caps | mail `$top ≤ 25` per page, `--all` cap 500, `graphGetAll` default cap 200; calendar `$top=25` pages, cap 500 / `max(limit,50)`; Teams search page 25, max 200; calendarView for transcripts `$top=50`; channel replies `$top=50`; `--dm` scans 50 chats; org summary 5 people. |
| Caching | token cache only; no response caching; fixture files in test mode. |

### 6.7 OData feature usage summary
| Feature | Where |
|---|---|
| `$select` | almost every GET (see tables) |
| `$filter` | mail date/isRead (filter mode); `/me/onlineMeetings` by `joinWebUrl` |
| `$search` | mail (KQL, quoted), `/me/people`, `/me/contacts`, `/me/onenote/pages` |
| `$orderby` | mail `receivedDateTime desc`; calendarView `start/dateTime`; OneDrive `name` |
| `$top` | most lists; never on Planner (400) or channel replies beyond fixed 50 |
| `$expand` | `channels --messages` → `replies` |
| `@odata.nextLink` | `emails`, `calendar` only |
| Microsoft Search API | `POST /search/query` (`chatMessage`) with `from/size` paging |
| `$batch`, delta, `$count`, `$skip` | none |
| beta | `/copilot/users/{oid}/onlineMeetings/{id}/aiInsights` fallback only |

---

## 7. SKILL.md (how Claude is instructed)

- **Frontmatter**: `name: msgraph`; long trigger `description` listing every service and phrases ("emails, inbox, unread messages, meetings, calendar, Teams messages or chats, channel messages, SharePoint documents, OneDrive files, OneNote notes or notebooks, Planner plans or tasks, 'my tasks', to-do lists, action items, meeting summaries, colleagues, manager, direct reports"), "Invoke proactively any time the user mentions Outlook, Teams, SharePoint, OneDrive, OneNote, Planner, Microsoft To Do"; `metadata: author` (upstream team), `version: "0.1.0"`.
- **Setup & Authentication**: always run `status` first; interpret `Logged in as` / `NOT_LOGGED_IN` / `TOKEN_EXPIRED`; exact user-facing message to relay for login (browser opens; URL printed as fallback); `login --force`.
- **Available Commands**: one section per family with copy-paste examples using `node ${CLAUDE_PLUGIN_ROOT}/skills/msgraph/scripts/msgraph.js …`, plus blockquote notes explaining: KQL vs `$filter` for mail and the date-only precision of `received`; calendar upcoming-vs-windowed semantics and `lastModifiedDateTime` as change fingerprint; `--file-url` resolution mechanics; Teams inline images not in `attachments[]`, single-quoting `$value`, `reference` attachments → `sharepoint --file-url`; Teams `--search` via Microsoft Search with client-side date filter; Planner `Group.Read.All` + etag; `--my-tasks` returns ids only; AI insights need Copilot licence, 403/empty meanings.
- **Workflow Patterns** (14 recipes): show emails; calendar today/week; find SharePoint file; check Teams messages; date-windowed sweep across emails/Teams/calendar (with `--all --json`, `--full --output`); OneNote browse/search; transcript for yesterday's standup; all transcripts for today; post to a channel (teams-list → channels list → send); manager/reports; Planner + To Do tasks; add a task; mark task done; summarise meeting / action items via `--insights`.
- **Error Handling** table: exit 0 success, 1 API error, 2 `NOT_LOGGED_IN` (inaccurate: only `claims` uses 2); "Permission denied" = scope not granted / org restriction.
- **Dependencies**: none; Node ≥ 18; "IMPORTANT: you must work with current date (get it from sh/bash)".
- **Guardrails**: **none** about confirming before `--send` (mail, chat, channel, DM), creating events, uploading, or completing tasks. No scoping rule beyond "Microsoft 365 only" (the Slack eval checks that).
- **Documented vs implemented gaps**: not mentioned in SKILL.md — `claims`, `calendar --attendees/--body`, `teams --lookup-user`, `teams --dm`, `channels --replies`, `sharepoint --resolve-site/--site-file` (only in a fallback note), `people --contacts --search`, `org` summary mode, `onedrive --limit`. Mentioned in SKILL.md but not true — transcripts "defaults to last 7 days"; exit code 2 for `NOT_LOGGED_IN`.

---

## 8. Tests and evals

### 8.1 `tests/` (untracked; Node built-in runner)
- Framework: `node:test` + `node:assert/strict`; CLI executed out-of-process with `spawnSync(process.execPath, [msgraph.js, …])` because the script runs `main()` at load.
- `helpers.js`: duplicates the fixture hashing scheme (`"<METHOD> <pathname><search>"` → sha256 hex[0:16] → `<dir>/<hash>.json`); `writeFixture(dir, method, urlOrPath, entries)`, `jsonFixture(status, obj)`, `makeFixtureDir()` (os.tmpdir), `runCli(argv, fixtureDir, extraEnv)` (sets `MSGRAPH_FIXTURE_DIR`, `MSGRAPH_RECORD=''`).
- `compat.test.js` (14 tests): "compatibility baseline" — for each documented command shape writes the fixture into the **checked-in** `tests/fixtures/compat/<slug>/` (rewriting it on every run), runs plain and `--json`, asserts exit 0 and `stdout === tests/fixtures/snapshots/<name>.snap`. Shapes: `status`; `emails` list / `--search "invoice Q4"` / `--read AAMk-msg-0001`; `calendar --after 2026-07-01 --before 2026-07-21`; `teams --chats` / `--search PPG` / `--messages chat-0002`; `channels --team-id team-0001 --list`; `sharepoint --resolve-site contoso.sharepoint.com:/sites/Engineering` / `--site <id>`; `transcripts --start 2026-07-08` / `--meeting meeting-0001`; `onedrive` list. All data synthetic (`example.com`, `contoso.sharepoint.com`). `GENERATE_SNAPSHOTS=1` regenerates.
- `fixture-mode.test.js` (5 tests): single fixture replay (`me --json`); array fixture consumed sequentially across `graphGetAll` pagination (`emails --all --json` with a self-referencing nextLink); missing fixture → exit 1 + `No fixture recorded for GET /v1.0/me (hash …)`; `status` bypasses cache; fixture `status: 404` surfaces as `Error: Resource not found`.
- How to run: `cd plugins/msgraph && node --test tests/compat.test.js tests/fixture-mode.test.js` (on Node 26 `node --test tests/` fails — the directory is treated as a test file; bare `node --test` also discovers `**/*.test.js`). Not wired into CI or any npm script.
- Results observed: **19/19 pass** on the author's machine (UTC+3). Under `TZ=UTC` **2 fail** (`calendar`, `transcripts --start`) because the snapshots baked in the local-time rendering of zone-less datetimes (`09:00` → `06:00`). `status.snap` embeds the author's absolute `~/.ms_graph_token_cache.json` path, so it fails for any other user/home.

### 8.2 `skills/msgraph/evals/evals.json` (tracked)
Skill-creator-style prompt evals, `skill_name: msgraph`, 6 cases with `prompt`, `expected_output`, `files: []`, `assertions[{name, description}]`:
1. unread inbox this morning → checks-status-first, uses-email-command
2. create "Design Review" event tomorrow 10:00–10:30 in Teams → calendar-create, includes-event-details
3. Slack message → rejects-slack, states-scope
4. Planner tasks assigned to me → uses-planner-my-tasks, checks-status-first
5. summarise yesterday's standup + action items → uses-transcripts-insights, handles-license-requirement
6. post to #announcements in Engineering → uses-channels-send, resolves-team-and-channel
No runner in the repo; intended for `skill-creator` / `claude plugin eval` style grading.

---

## 9. plugin.json, README, CHANGELOG, LICENSE

| File | Content |
|---|---|
| `.claude-plugin/plugin.json` | `$schema` json.schemastore claude-code-plugin; `name: msgraph`; `version: 0.1.0`; description (Outlook mail/calendar, Teams, SharePoint, OneDrive, OneNote, Planner, To Do, org chart); author Sviatoslav Sviridov <sviridov@gmail.com>; keywords `microsoft-365 graph-api outlook teams sharepoint onedrive`. |
| `CHANGELOG.md` | `[0.1.0] - 2026-09-02`: initial release; skill copied verbatim from the `feat/msgraph-search-filter` branch of the upstream skills fork. |
| `README.md` (plugin) | Install (`claude plugin marketplace add svd/mgraphctl`, `claude plugin install msgraph@<marketplace>`); first run = `status`; requirements (M365 access; Copilot licence + transcription for AI insights; `Group.Read.All` for Planner); **Provenance/TODO**: vendored because `feat/msgraph-search-filter` is not merged upstream; once merged, switch the marketplace entry to a pinned upstream ref. Claims "no Python and no extra packages, only Node.js". |
| `skills/msgraph/README.md` | "Use it for" bullets, example prompts, "What it needs" (login on first run, Copilot licence, `Group.Read.All`). |
| `skills/msgraph/LICENSE` | proprietary internal-use notice (ownership retained, no warranty); `msgraph.js` header repeats it. |

---

## 10. Uncommitted diff to `msgraph.js` (HEAD 2191 → working tree 2291 lines)

Adds an offline **fixture record/replay mode** (+100 lines, no behaviour change when the env vars are unset):

- Constants: `FIXTURE_DIR = process.env.MSGRAPH_FIXTURE_DIR || null`; `FIXTURE_RECORD = FIXTURE_DIR && MSGRAPH_RECORD === '1'`; `FIXTURE_REPLAY = FIXTURE_DIR && !FIXTURE_RECORD`; `FIXTURE_TOKEN = 'fixture-mode-dummy-token'`; `FIXTURE_USERNAME = 'fixture-user@example.com'`.
- Keying: `fixtureKey(method, url)` = `"<METHOD> <pathname><search>"` (host-agnostic); `fixtureHash` = sha256 hex first 16 chars; file `<dir>/<hash>.json`.
- `isTokenEndpoint(url)`: hostname `login.microsoftonline.com` is never replayed or recorded.
- `readFixture`: file holds one `{status, headers, body}` or an array consumed **sequentially per file within one process** (`_fixtureCursors` map; last entry repeats once exhausted); missing file → `Error('No fixture recorded for <key> (hash <h>). Create <file> — …')`.
- `recordFixture`: `mkdir -p`, appends to an existing array (or promotes a single object to an array), strips `authorization` from recorded response headers, writes pretty JSON.
- `httpsRequest`: in replay mode returns the fixture (status ≥ 400 → same error shape as a live error, with `responseUrl`); in record mode performs the real request then records `{status, headers, body}` before the ≥400 check. `method` hoisted to a local.
- `getAccessToken` / `tryGetToken`: return `FIXTURE_TOKEN` immediately in replay mode (no cache read, no browser).
- `cmdStatus`: in replay mode prints `Logged in as: fixture-user@example.com` + `Cache file: <CACHE_FILE>` and returns.
- Not covered by replay: `graphDownload` (uses `https.get` directly, so `--download`, `--file-url`, `--hosted-content` still hit the network in fixture mode).
- Companion uncommitted change to repo `.gitignore`: ignore `plugins/msgraph/tests/fixtures/live/` (recorded real traffic).
- The untracked `tests/` tree (helpers, 19 tests, 13 fixtures, 25 snapshots) depends on this diff.

---

## 11. Gaps, bugs, quirks (parity decisions for the Python port)

1. **Zone-less datetimes rendered in local time.** `fmtDt` parses Graph's `…T09:00:00.0000000` (calendar, transcripts, insights, Planner `dueDateTime` is Z-suffixed so fine) as local and prints "UTC", shifting by the machine offset. Snapshots encode the author's UTC+3 result; `TZ=UTC` breaks 2 tests. Parity requires either reproducing the bug or regenerating snapshots.
2. **`transcripts` default window is one day, a week ago** (`end` defaults to `start`), contradicting SKILL.md ("last 7 days").
3. **`sharepoint --download ITEM_ID` reads `/me/drive/items/{id}`** (user's OneDrive), not a site drive; and `sharepoint --site` text output omits item ids, so the documented "browse then `--download`" workflow cannot work without `--json` and would still hit the wrong drive.
4. **Path segments are never URL-encoded** except in `--file-url` (`--path`, `--dest`, `--folder`, `--site-file --path`, site refs, message/chat ids). Spaces or `#` in a path make Node throw `Request path contains unescaped characters`.
5. **No 429/5xx retry, no `Retry-After`, no timeouts, no proxy.**
6. **Any data command may open a browser**: `getAccessToken` falls back to interactive PKCE login when the cache is missing or refresh fails — hazardous when Claude runs the CLI non-interactively. `status` exits 0 even when `NOT_LOGGED_IN`; only `claims` uses exit 2, contrary to SKILL.md.
7. **`stripHtml` is naive**: `<style>`/`<script>` bodies leak into text, no block-tag newlines, only four entities decoded.
8. **Help/SKILL promise flags that are ignored or missing**: `org --json`; `channels --replies --limit` (fixed `$top=50`); `channels --messages` has no `--full`; `transcripts --download` referenced but unimplemented; `--help` and `--list` are parsed no-ops.
9. **Send paths are minimal and inconsistent**: `emails --send` = one To, text body, no cc/bcc/attachments; `teams --send` and `channels --send` post `contentType:'html'` without escaping, while `--dm` posts plain text; `--send` silently takes precedence over `--read`.
10. **`teams --dm`** only inspects the 50 most recent chats and matches by `chatId.includes(oid)`; cannot create a chat.
11. **Inconsistent output-dir checks**: `emails --read --output`, `--attachment-id --output`, `transcripts --output` write without `assertOutputDir`; `onedrive --download` prints a formatted size while `sharepoint --download` prints raw bytes; default names differ (`download_` vs `downloaded_`).
12. **`calendar --availability`** has no `$top` (server default page ~10), treats `showAs: free/tentative` as busy, mixes UTC and local when computing the default end, and has no `--json`.
13. **Parser limits**: no `--k=v`, values may not start with `--`, unknown flags accepted silently, `--limit 0` or non-numeric silently becomes the default, bare `--output` becomes `true` (guarded only where `outputPath()` is used).
14. **`onenote --create`** injects unescaped title/body into HTML; `--read --json` emits compact JSON (every other `--json` is pretty-printed).
15. **OneDrive upload** is a single PUT with the whole file in memory (fails above 4 MB); no SharePoint upload despite `Sites.ReadWrite.All` being requested.
16. **Teams search** returns only the hit `summary` snippet as `body`; for channel hits `chatId` is actually the channel id (not usable with `teams --messages`); `--limit` semantics differ from other commands (default 100, max 200).
17. **`teams --messages` / `channels --messages`** text output is reversed (oldest first) while `--json` is Graph order (newest first).
18. **Token cache is plaintext JSON** (`0600`) with a rotating refresh token; the same scopes string is re-sent on refresh; the client id/tenant are unconfigurable.
19. **Fixture replay does not cover `graphDownload`**, and the compat tests overwrite their own checked-in fixtures on each run; `status.snap` hard-codes the author's home path; tests are untracked and not in CI.
20. **Query-string encoding** must match Node's `URLSearchParams` (space → `+`, `*` unencoded, `~` → `%7E`) to keep fixture hashes and `search=*` byte-identical; Python's `urlencode` differs on `*`/`~`.
21. Minor: `graphGetAll` always emits `?` even with empty params; `graphPost`/`graphPatch` return `{}` on empty bodies; insights 403 is a soft message with exit 0; `me` uses no `$select`; `emails --unread` in search mode is client-side over up to 500 items; `sharepoint --sites` falls back to `/sites?search=*` (non-`$` param) only when the followed-sites list is empty; the hosted-content branch rewrites `/beta` URLs onto the v1.0 base; `people --contacts --search` relies on `$search` being accepted by `/me/contacts`.
