# mgraphctl command reference

Every verb the CLI registers, with its options, the Graph call it makes, the scopes it needs, and
its parity tier. `SKILL.md` links here rather than repeating the option tables.

## How to read this file

Headings give the command *form* — `mail list`, `teams channel send`, `mailbox oof set`. To run
one, put the canonical path in front of it:

```bash
${CLAUDE_PLUGIN_ROOT}/mgraphctl mail list --unread --limit 10
${CLAUDE_PLUGIN_ROOT}/mgraphctl teams channel send TEAM CHANNEL --body "hi" --dry-run
```

There is no alias and no shorter spelling: `${CLAUDE_PLUGIN_ROOT}` is the only variable that ever
appears in a command line.

- **Tier** — P0: parity with the Node `msgraph` skill. P1: new, works with the `default` scope set.
  P2: needs `login --scopes extended` or an on-demand `--scope`.
- **Scopes** — the scopes the local gate checks before the first request. "A or B" means either
  satisfies the gate. A scope marked *on-demand* is in neither named set; request it with
  `login --scope <name>`.
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

## Top-level

### `login`

The only command that may open a browser. Run it yourself in your own terminal.

| Option | Default | Meaning |
|---|---|---|
| `--scopes SET` | `MGRAPHCTL_SCOPES`, else `default` | `default`, `extended`, or a space/comma-separated scope list. |
| `--scope X` | — | One extra on-demand scope. Repeatable. |
| `--force` | off | Sign in again even when a token is cached. |
| `--device-code` | off | Device-code flow, for a host with no browser. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** the msal token endpoint, then `GET /me?$select=id,displayName,userPrincipalName`.
- **Scopes:** none checked (this is what obtains them).
- **Tier:** P0
- **Notes:** already signed in and no new scopes asked for → prints `Already logged in as: <upn>`,
  exit 0. Interactive login times out after 300 s (`error[LOGIN_TIMEOUT]`, exit 3). Re-running with
  `--scopes extended` on a consented account adds scopes with one consent prompt, no re-login.

### `logout`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** none.
- **Scopes:** none.
- **Tier:** P0
- **Notes:** deletes `~/.mgraphctl/token_cache.json`. Exit 0 whether or not a cache existed.

### `status`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** none — a silent token acquisition, which may refresh.
- **Scopes:** none.
- **Tier:** P0
- **Notes:** run this first. Logged in → `Logged in as`, `Token expires`, `Scopes`, `Cache`, exit 0.
  Not logged in → `error[NOT_LOGGED_IN]` on stderr, exit 3. With `--json` stdout carries
  `{"loggedIn": …}` in both states, so it can be parsed without checking the exit code first.

### `claims`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print the raw token payload. |

- **Graph:** none — a local JWT decode, no network call.
- **Scopes:** none.
- **Tier:** P0
- **Notes:** sections IDENTITY, DEVICE, AUTH METHODS, SCOPES. It cannot refresh an expired token;
  no cached token → exit 3.

### `me`

| Option | Default | Meaning |
|---|---|---|
| `--photo PATH` | — | Save the profile photo to this file instead of printing the profile. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me?$select=id,displayName,userPrincipalName,mail,jobTitle,department,officeLocation,businessPhones,mobilePhone,preferredLanguage`;
  `--photo`: `GET /me/photo/$value` (streamed).
- **Scopes:** `User.Read`
- **Tier:** P0
- **Notes:** a mailbox with no photo returns 404 → exit 4.

### `version`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** none.
- **Scopes:** none.
- **Tier:** P1
- **Notes:** prints `mgraphctl <version>` with the Python, msal and httpx versions it runs on.

## `config`

The optional TOML file at `~/.mgraphctl/config.toml` (or `--config PATH` / `MGRAPHCTL_CONFIG`).
Nothing in it is secret; the token cache stays a separate file.

### `config path`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | `{"path", "exists"}`. |

- **Graph:** none.
- **Scopes:** none.
- **Tier:** P1
- **Notes:** prints the path the other commands read, whether or not it exists.

### `config show`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | `{"path", "settings": {key: value}, "sources": {key: flag|env|file|default}, "unknownKeys"}`. |

- **Graph:** none.
- **Scopes:** none.
- **Tier:** P1
- **Notes:** one row per key with its effective value and where it came from. Keys in the file
  that mgraphctl does not know are listed, not rejected. A file that is not valid TOML fails
  this and every other command with `error[CONFIG]` (exit 2).

### `config init`

| Option | Default | Meaning |
|---|---|---|
| `--force` | off | Overwrite an existing file. |
| `--json` | off | `{"path", "overwritten"}`. |

- **Graph:** none.
- **Scopes:** none.
- **Tier:** P1
- **Notes:** writes a template with every key commented out at its default, mode `0600` in a
  `0700` directory. Refuses to overwrite without `--force` (`error[USAGE]`).

### `config set KEY VALUE`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | `{"path", "key", "value"}`. |

- **Graph:** none.
- **Scopes:** none.
- **Tier:** P1
- **Notes:** replaces the key's line in place (uncommenting a template line), or appends it;
  every comment survives. Creates the file when there is none. `KEY` must be one of the config
  keys; `debug`, `retries`, `timeout_ms` and `retry_base_ms` take non-negative integers and `tz`
  an IANA name — anything else is `error[USAGE]` and the file is untouched.

### `config unset KEY`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | `{"path", "key", "removed"}` — `removed` is false when the key was not set. |

- **Graph:** none.
- **Scopes:** none.
- **Tier:** P1
- **Notes:** comments the key's line out, so the environment variable or the default applies.

### `api METHOD PATH`

The escape hatch: one raw Graph request. `PATH` may be relative (`/me/messages`) or absolute.

| Option | Default | Meaning |
|---|---|---|
| `--query k=v` | — | Query parameter. Repeatable. |
| `--body JSON\|@FILE` | — | JSON request body, or `@FILE` holding it. |
| `--header k:v` | — | Extra request header. Repeatable. |
| `--beta` | off | Send this call to `/beta`. |
| `--all` | off | Follow `@odata.nextLink` and merge every page's `value`. |
| `--raw` | off | Treat the response as bytes, not JSON. |
| `--output FILE` | — | Write the `--raw` bytes to this file. |
| `--outlook-tz` | off | Send `Prefer: outlook.timezone` for mail/calendar paths. Hidden from `--help`. |
| `--dry-run` | off | Show the request; send nothing. |
| `--json` | off | Accepted, no-op — the body is printed as returned. |

- **Graph:** exactly the request given.
- **Scopes:** none declared; the local gate is skipped and Graph decides.
- **Tier:** P1
- **Notes:** the response body is printed as-is; a non-JSON body prints as text unless `--raw`.
  Any non-GET `api` call is a write — dry-run it and confirm first.

### `search Q`

| Option | Default | Meaning |
|---|---|---|
| `--type TYPE` | `message` | `message`, `event`, `driveItem`, `site`, `list`, `chatMessage`, or `person`. |
| `--after DT` | — | Only hits after this time. |
| `--before DT` | — | Only hits before this time. |
| `--limit N` | 25 | Maximum items. |
| `--all` | off | Fetch every page, cap 200. |
| `--fields a,b` | — | Comma-separated Graph fields to fetch. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /search/query {requests:[{entityTypes:[type], query:{queryString}, from, size:25, fields?}]}`,
  paging on `moreResultsAvailable`.
- **Scopes:** checked per `--type` after parsing: `message` → `Mail.Read`; `event` → `Calendars.Read`;
  `driveItem`/`site`/`list` → `Sites.Read.All`; `chatMessage` → `Chat.Read`; `person` → `People.Read`.
- **Tier:** P1
- **Notes:** for `message` the date window is appended to the KQL as `received>=`/`received<=`; for
  every other type it is applied client-side. Hits carry a `summary` snippet, not the whole item.
  `chatMessage` hits are labelled `chat:<id>` or `channel:<teamId>/<channelId>`, exactly as
  `chats search` labels them.

## `mail`

### `mail list`

| Option | Default | Meaning |
|---|---|---|
| `--folder NAME\|ID\|all` | `inbox` | Folder name, well-known name, id, or `all` for the whole mailbox. |
| `--unread` | off | Only unread messages. |
| `--from ADDR` | — | Sender address. Repeatable. |
| `--to ADDR` | — | Recipient address. Repeatable. |
| `--search KQL` | — | KQL query. |
| `--after DT` | — | Only messages received after this. |
| `--before DT` | — | Only messages received before this. |
| `--select a,b` | — | `$select` override. |
| `--limit N` | 10 | Maximum items. |
| `--all` | off | Fetch every page, cap 500. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/mailFolders/{folder}/messages` (`--folder all` reads `GET /me/messages`).
  **Search mode** (any of `--search`/`--from`/`--to`): `$search=` KQL, `$top=25`, no `$orderby`.
  **Filter mode**: `$filter=receivedDateTime ge/le …[ and isRead eq false]`,
  `$orderby=receivedDateTime desc`, `$top=50`. Both send
  `$select=id,subject,from,toRecipients,ccRecipients,receivedDateTime,isRead,hasAttachments,importance,bodyPreview,conversationId,webLink,inferenceClassification`
  and `Prefer: outlook.timezone`.
- **Scopes:** `Mail.Read`
- **Tier:** P0
- **Notes:** in search mode `--unread` is applied client-side, because KQL has no `isRead` term.
  So are `--after`/`--before` when they carry a time of day: KQL's `received` compares on the
  calendar date only, so `--after 2026-09-02T14:00` reaches Graph as `received>=2026-09-02` and the
  earlier part of that day is dropped here. A date-only bound needs no such pass and gets none.
  Both passes run after paging, so a filtered page can be shorter than `--limit` while
  `truncated` is still true.
  Columns: id, received, flags (`*` unread, `A` attachment, `!` high importance), from, subject.
  Node's `emails` mode listed the whole mailbox — pass `--folder all` for that.

### `mail read ID`

| Option | Default | Meaning |
|---|---|---|
| `--html` | off | Show the HTML body verbatim instead of text. |
| `--full` | off | Do not truncate the body at 4000 characters. |
| `--headers` | off | Also show the internet message headers. |
| `--output FILE` | — | Write the full body to this file. |
| `--save-attachments DIR` | — | Save every file attachment into this directory. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/messages/{id}?$select=…,body,uniqueBody,replyTo[,internetMessageHeaders]` with
  `Prefer: outlook.timezone` and `Prefer: outlook.body-content-type="text"` unless `--html`;
  `--save-attachments` adds the attachment list plus `GET …/attachments/{aid}/$value` per file.
- **Scopes:** `Mail.Read`
- **Tier:** P0
- **Notes:** truncation prints a note on stderr. Item and reference attachments cannot be
  downloaded and are skipped with a stderr note.

### `mail attachments ID`

| Option | Default | Meaning |
|---|---|---|
| `--download ATTID` | — | Attachment id to download. |
| `--output FILE` | — | Where to write the `--download` file. |
| `--all-attachments` | off | Download every file attachment. |
| `--output-dir DIR` | — | Directory for `--all-attachments`. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/messages/{id}/attachments?$select=id,name,contentType,size,isInline`;
  download: `GET …/attachments/{aid}/$value` (streamed).
- **Scopes:** `Mail.Read`
- **Tier:** P0
- **Notes:** downloading a single itemAttachment or referenceAttachment fails (exit 1); under
  `--all-attachments` they are skipped with a stderr note.

### `mail send`

| Option | Default | Meaning |
|---|---|---|
| `--to ADDR` | — | Recipient. Repeatable, comma-separated. At least one required. |
| `--cc ADDR` | — | Copy recipient. Repeatable. |
| `--bcc ADDR` | — | Blind copy. Repeatable. |
| `--subject TEXT` | `(no subject)` | Subject line. |
| `--body TEXT` | — | Message body. |
| `--body-file FILE\|-` | — | Body file, or `-` for stdin. |
| `--html` | off | The body is HTML, not plain text. |
| `--attach FILE` | — | File to attach. Repeatable. |
| `--importance LEVEL` | `normal` | `low`, `normal` or `high`. |
| `--save-to-sent` / `--no-save-to-sent` | on | Keep a copy in Sent Items. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** **inline path** when the attachments total 2.5 MiB or less: `POST /me/sendMail`.
  **Draft path** otherwise: `POST /me/messages`, then per attachment `POST …/attachments`
  (under 3 MiB) or `POST …/attachments/createUploadSession` plus chunks, then
  `POST /me/messages/{id}/send`.
- **Scopes:** `Mail.Send`; the draft path additionally checks `Mail.ReadWrite` before its first
  request.
- **Tier:** P0 (draft path P2)
- **Notes:** write. JSON `{"status":"sent"}`, plus `"draftId"` on the draft path. The dry run names
  the path it would take.

### `mail reply ID`

| Option | Default | Meaning |
|---|---|---|
| `--body TEXT` | — | Message body. |
| `--body-file FILE\|-` | — | Body file, or `-` for stdin. |
| `--html` | off | The body is HTML. |
| `--reply-all` | off | Reply to everyone on the message. |
| `--to ADDR` | — | Extra recipient. Repeatable. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/messages/{id}/reply` (or `/replyAll`) with `{comment}`, or
  `{message:{body:{contentType:"HTML"}}}` with `--html`, plus `message.toRecipients` for `--to`.
- **Scopes:** `Mail.Send`
- **Tier:** P1
- **Notes:** write. JSON `{"status":"sent"}`.

### `mail forward ID`

| Option | Default | Meaning |
|---|---|---|
| `--to ADDR` | — | Recipient. Repeatable, comma-separated. At least one required. |
| `--body TEXT` | — | Comment to add above the forwarded message. |
| `--html` | off | The body is HTML. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/messages/{id}/forward {toRecipients, comment}`.
- **Scopes:** `Mail.Send`
- **Tier:** P1
- **Notes:** write.

### `mail folders`

| Option | Default | Meaning |
|---|---|---|
| `--depth N` | 2 | How many levels of the tree to show. |
| `--hidden` | off | Include hidden folders. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/mailFolders?$top=100&$select=id,displayName,parentFolderId,childFolderCount,unreadItemCount,totalItemCount[&includeHiddenFolders=true]`,
  then `…/{id}/childFolders` for each folder with children, down to `--depth`.
- **Scopes:** `Mail.Read`
- **Tier:** P1
- **Notes:** text indents each level by two spaces; JSON nests them under `children`.

### `mail mark ID...`

| Option | Default | Meaning |
|---|---|---|
| `--read` / `--unread` | — | Mark read or unread. |
| `--flag` / `--unflag` / `--flag-complete` | — | Follow-up flag state. |
| `--category X` | — | Category to set. Repeatable. |
| `--clear-categories` | off | Remove every category. |
| `--importance LEVEL` | — | `low`, `normal` or `high`. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `PATCH /me/messages/{id} {isRead, flag:{flagStatus}, categories, importance}`; more than
  one id goes through `POST /$batch` in chunks of 20.
- **Scopes:** `Mail.ReadWrite`
- **Tier:** P2
- **Notes:** write. Takes any number of ids. JSON is the list envelope even for a single id.

### `mail move ID`

| Option | Default | Meaning |
|---|---|---|
| `--folder NAME\|ID` | — | Destination folder. Required. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/messages/{id}/move {destinationId}`.
- **Scopes:** `Mail.ReadWrite`
- **Tier:** P2
- **Notes:** write. Returns the **new** message: the id changes, so any id captured before the move
  is dead. Re-list after moving.

### `mail delete ID`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `DELETE /me/messages/{id}`.
- **Scopes:** `Mail.ReadWrite`
- **Tier:** P2
- **Notes:** write. A soft delete — Outlook moves the message to Deleted Items. JSON
  `{"status":"deleted","id":…}`.

### `mail drafts list`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 20 | Maximum items. |
| `--all` | off | Fetch every page, cap 500. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/mailFolders/drafts/messages?$select=…&$orderby=lastModifiedDateTime desc`.
- **Scopes:** `Mail.Read`
- **Tier:** P1

### `mail drafts create`

The `mail send` options, minus `--save-to-sent`.

| Option | Default | Meaning |
|---|---|---|
| `--to` / `--cc` / `--bcc ADDR` | — | Recipients. Repeatable. |
| `--subject TEXT` | — | Subject line. |
| `--body TEXT` / `--body-file FILE\|-` | — | Body, or a file (`-` for stdin). |
| `--html` | off | The body is HTML. |
| `--attach FILE` | — | File to attach. Repeatable. |
| `--importance LEVEL` | `normal` | `low`, `normal` or `high`. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/messages {subject, body, toRecipients, …}` plus the same attachment steps as
  `mail send`.
- **Scopes:** `Mail.ReadWrite`
- **Tier:** P2
- **Notes:** write. Returns the draft, including the id `mail drafts send` needs.

### `mail drafts send ID`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/messages/{id}/send`.
- **Scopes:** `Mail.ReadWrite`, `Mail.Send`
- **Tier:** P2
- **Notes:** write.

### `mail rules list`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/mailFolders/inbox/messageRules`.
- **Scopes:** `MailboxSettings.Read`
- **Tier:** P2
- **Notes:** read-only. Columns: id, sequence, enabled, name, actions summary.

### `mail categories`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/outlook/masterCategories`.
- **Scopes:** `MailboxSettings.Read`
- **Tier:** P2

## `mailbox`

### `mailbox settings`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/mailboxSettings`.
- **Scopes:** `MailboxSettings.Read`
- **Tier:** P2
- **Notes:** shows the mailbox time zone, language, working hours and automatic-replies status.

### `mailbox oof get`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/mailboxSettings/automaticRepliesSetting`.
- **Scopes:** `MailboxSettings.Read`
- **Tier:** P2

### `mailbox oof set`

| Option | Default | Meaning |
|---|---|---|
| `--message TEXT` | — | Internal reply text. Required unless `--clear`. |
| `--external-message TEXT` | `--message` | External reply text. |
| `--start DT` | — | Start of the period. |
| `--end DT` | — | End of the period. |
| `--external AUDIENCE` | `all` | Who outside sees a reply: `all`, `contacts`, `none`. |
| `--internal-only` | off | Same as `--external none`. |
| `--clear` | off | Turn automatic replies off. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `PATCH /me/mailboxSettings {automaticRepliesSetting:{status, externalAudience,
  scheduledStartDateTime, scheduledEndDateTime, internalReplyMessage, externalReplyMessage}}`.
- **Scopes:** `MailboxSettings.ReadWrite`
- **Tier:** P2
- **Notes:** write. `--start` with `--end` sets status `scheduled`; otherwise `alwaysEnabled`;
  `--clear` sets `disabled`. `--external contacts` maps to `contactsOnly`. Messages go out as HTML.

### `mailbox focused`

| Option | Default | Meaning |
|---|---|---|
| `--other` | off | Show the Other inbox instead of Focused. |
| `--after DT` | `-30d` | Only messages received after this. |
| `--limit N` | 25 | Maximum items. |
| `--all` | off | Fetch every page, cap 500. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/mailFolders/inbox/messages` with
  `$filter=receivedDateTime ge {after} and inferenceClassification eq 'focused'` (or `'other'`),
  `$orderby=receivedDateTime desc`, the `mail list` `$select`, and `Prefer: outlook.timezone`.
- **Scopes:** `Mail.Read`
- **Tier:** P1
- **Notes:** `receivedDateTime` leads the filter so the `$orderby` stays efficient.

## `calendar`

### `calendar list`

| Option | Default | Meaning |
|---|---|---|
| `--start DT` (alias `--after`) | now | Window start. |
| `--end DT` (alias `--before`) | `--days` out | Window end. |
| `--days N` | 7 | Days from `--start`, when `--end` is not given. |
| `--calendar NAME\|ID` | the default calendar | Which calendar to read. |
| `--search KW` | — | Client-side match on subject, organizer and attendees. |
| `--limit N` | 50 | Maximum items. |
| `--all` | off | Fetch every page, cap 200. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/calendarView` (or `/me/calendars/{id}/calendarView`) with
  `startDateTime`, `endDateTime`,
  `$select=id,subject,start,end,location,organizer,attendees,isOnlineMeeting,onlineMeeting,isCancelled,isAllDay,showAs,responseStatus,seriesMasterId,bodyPreview,webLink`,
  `$orderby=start/dateTime`, `$top=50`, and `Prefer: outlook.timezone`.
- **Scopes:** `Calendars.Read`
- **Tier:** P0
- **Notes:** `calendarView` expands recurring series into occurrences. Columns: start, end, markers
  (`T` Teams meeting, `X` cancelled), subject, organizer, location, id.

### `calendar calendars`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/calendars?$select=id,name,isDefaultCalendar,canEdit,owner,color`.
- **Scopes:** `Calendars.Read`
- **Tier:** P1

### `calendar get ID`

| Option | Default | Meaning |
|---|---|---|
| `--html` | off | Show the HTML body verbatim. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/events/{id}` with `Prefer: outlook.timezone`, and
  `Prefer: outlook.body-content-type="text"` unless `--html`.
- **Scopes:** `Calendars.Read`
- **Tier:** P1
- **Notes:** shows every attendee with their response status, and the Teams join URL when there is
  one.

### `calendar create`

| Option | Default | Meaning |
|---|---|---|
| `--subject TEXT` | — | Event title. Required. |
| `--start DT` | — | Start. Required. |
| `--end DT` | `--start` + `--duration` | End. |
| `--duration D` | `30m` | Length, when `--end` is not given. |
| `--all-day` / `--no-all-day` | off | All-day event. |
| `--attendees ADDR` | — | Required attendee. Repeatable. |
| `--optional ADDR` | — | Optional attendee. Repeatable. |
| `--body TEXT` | — | Event body. |
| `--html` | off | The body is HTML. |
| `--location TEXT` | — | Location display name. |
| `--teams` / `--no-teams` | off | Add a Teams online meeting. |
| `--reminder MIN` | — | Minutes before start. |
| `--show-as STATE` | — | `free`, `tentative`, `busy`, `oof`, `workingElsewhere`. |
| `--category X` | — | Category. Repeatable. |
| `--calendar NAME\|ID` | the default calendar | Which calendar to create in. |
| `--transaction-id ID` | a generated uuid4 | Idempotency key. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/events` (or `/me/calendars/{id}/events`) with
  `{subject, start, end, isAllDay, attendees, body, location, isOnlineMeeting,
  onlineMeetingProvider:"teamsForBusiness", reminderMinutesBeforeStart, showAs, categories,
  transactionId}` and `Prefer: outlook.timezone`.
- **Scopes:** `Calendars.ReadWrite`
- **Tier:** P0
- **Notes:** write. Returns the event, including `onlineMeeting.joinUrl` with `--teams`. An all-day
  event with no `--end` ends at midnight the next day. Graph sends the invitations.

### `calendar update ID`

Every `calendar create` option except `--calendar` and `--transaction-id`; all optional.

| Option | Default | Meaning |
|---|---|---|
| `--subject` / `--start` / `--end` / `--duration` | — | Change these fields. |
| `--all-day` / `--no-all-day` | — | Change the all-day flag. |
| `--attendees` / `--optional ADDR` | — | Replace the attendee list. Repeatable. |
| `--body TEXT` / `--html` | — | Replace the body. |
| `--teams` / `--no-teams` | — | Add or remove the Teams online meeting. |
| `--location` / `--reminder` / `--show-as` / `--category` | — | Change these fields. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `PATCH /me/events/{id}` with only the fields given, and `Prefer: outlook.timezone`.
- **Scopes:** `Calendars.ReadWrite`
- **Tier:** P1
- **Notes:** write. Graph cannot move an event between calendars, so there is no `--calendar`.
  Updating a series master updates the whole series.

### `calendar delete ID`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `DELETE /me/events/{id}`.
- **Scopes:** `Calendars.ReadWrite`
- **Tier:** P1
- **Notes:** write. When the signed-in user is the organizer, Graph sends cancellations to every
  attendee.

### `calendar respond ID accept|decline|tentative`

| Option | Default | Meaning |
|---|---|---|
| `--comment TEXT` | — | Comment to send with the response. |
| `--send` / `--no-send` | on | Send the response to the organizer. |
| `--propose-start DT` | — | Propose a new start (decline or tentative only). |
| `--propose-end DT` | — | Propose a new end (decline or tentative only). |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/events/{id}/accept` | `/decline` | `/tentativelyAccept` with
  `{comment, sendResponse, proposedNewTime}`.
- **Scopes:** `Calendars.ReadWrite`
- **Tier:** P1
- **Notes:** write. JSON `{"status":"accepted"|"declined"|"tentativelyAccepted"}`.

### `calendar availability`

| Option | Default | Meaning |
|---|---|---|
| `--users ADDR` | the signed-in user | Mailbox to check. Repeatable. |
| `--start DT` | now, floored to the interval | Window start. |
| `--end DT` | end of today | Window end. |
| `--interval MIN` | 30 | Minutes per slot (5–1440). |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/calendar/getSchedule {schedules, startTime, endTime,
  availabilityViewInterval}` with `Prefer: outlook.timezone`; with no `--users`, one
  `GET /me?$select=mail,userPrincipalName` first.
- **Scopes:** `Calendars.Read`
- **Tier:** P0
- **Notes:** text lists each user's busy, tentative, out-of-office and working-elsewhere blocks,
  and the free windows computed from `availabilityView`.

### `calendar find-times`

| Option | Default | Meaning |
|---|---|---|
| `--attendees ADDR` | — | Attendee. Repeatable. At least one required. |
| `--duration D` | `30m` | Meeting length. |
| `--start DT` | now | Earliest start. |
| `--end DT` | +7d | Latest end. |
| `--max N` | 5 | Maximum candidates. |
| `--domain DOMAIN` | `work` | `work`, `personal` or `unrestricted`. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/findMeetingTimes {attendees, timeConstraint:{activityDomain, timeSlots},
  meetingDuration, maxCandidates, returnSuggestionReasons:true}` with `Prefer: outlook.timezone`.
- **Scopes:** `Calendars.Read.Shared`
- **Tier:** P2
- **Notes:** text shows each suggestion with its confidence and per-attendee availability. When
  Graph returns nothing it surfaces `emptySuggestionsReason`.

## `people`

### `people search Q`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 20 | Maximum items. |
| `--all` | off | Fetch every page, cap 250. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/people?$search="Q"&$top=50&$select=id,displayName,scoredEmailAddresses,jobTitle,department,companyName,personType,userPrincipalName`.
- **Scopes:** `People.Read`
- **Tier:** P0
- **Notes:** `/me/people` ranks by relevance to the signed-in user and is in maintenance mode; for a
  wider sweep use `search Q --type person` or `people users Q`.

### `people contacts`

| Option | Default | Meaning |
|---|---|---|
| `--search Q` | — | Filter by name or email. |
| `--limit N` | 20 | Maximum items. |
| `--all` | off | Fetch every page, cap 250. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/contacts?$top=50&$select=id,displayName,emailAddresses,mobilePhone,businessPhones,jobTitle,companyName[&$search="Q"]`.
- **Scopes:** `Contacts.Read`
- **Tier:** P0
- **Notes:** when Graph rejects `$search` with a 400, up to 250 contacts are fetched and matched
  client-side instead.

### `people contact ID`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/contacts/{id}`.
- **Scopes:** `Contacts.Read`
- **Tier:** P1

### `people users Q`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 20 | Maximum items. |
| `--all` | off | Fetch every page, cap 999. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /users?$search="displayName:Q" OR "mail:Q"&$count=true&$top=100&$select=id,displayName,userPrincipalName,mail,jobTitle,department,officeLocation`
  with `ConsistencyLevel: eventual`.
- **Scopes:** `User.ReadBasic.All`
- **Tier:** P2
- **Notes:** a directory search. `$search` matches whole tokens, not substrings — "ann" will not
  find "Anna".

### `people user UPN|ID`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /users/{x}?$select=id,displayName,userPrincipalName,mail,jobTitle,department,officeLocation,businessPhones,mobilePhone`
  (or `GET /me` for `me`).
- **Scopes:** `User.Read`; resolving a bare display name additionally checks `User.ReadBasic.All`.
- **Tier:** P0
- **Notes:** accepts a UPN, an object id, `me`, or a display name.

### `people photo [UPN]`

| Option | Default | Meaning |
|---|---|---|
| `--output FILE` | `<upn>.jpg` | Destination file. |
| `--size WxH` | `96x96` | Photo size. Applies to other users only. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/photo/$value`, or `GET /users/{upn}/photos/{size}/$value` (streamed).
- **Scopes:** `User.Read` for yourself; `User.ReadBasic.All` is checked before reading anyone else.
- **Tier:** P1 (P2 for another user)
- **Notes:** a mailbox with no photo returns 404 → exit 4.

## `org`

### `org manager [UPN]`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/manager` or `GET /users/{upn}/manager` with
  `$select=id,displayName,userPrincipalName,mail,jobTitle,department`.
- **Scopes:** `User.Read`; another user additionally checks `User.Read.All` (*on-demand*).
- **Tier:** P0 (P2 for another user)
- **Notes:** no manager on record → `No manager found`, exit 4.

### `org reports [UPN]`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 20 | Maximum items. |
| `--all` | off | Fetch every page, cap 500. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/directReports` or `GET /users/{upn}/directReports` with the same `$select`.
- **Scopes:** `User.Read`; another user additionally checks `User.Read.All` (*on-demand*).
- **Tier:** P0 (P2 for another user)

### `org chain [UPN]`

| Option | Default | Meaning |
|---|---|---|
| `--max N` | 10 | Maximum levels to climb. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me?$expand=manager($levels=max;$select=id,displayName,userPrincipalName,jobTitle)&$count=true`
  with `ConsistencyLevel: eventual`; on 400 or 403 it falls back to walking
  `GET /users/{id}/manager` one level at a time, up to `--max`.
- **Scopes:** `User.Read`; the iterative fallback additionally checks `User.Read.All` (*on-demand*).
- **Tier:** P1
- **Notes:** text prints one line per level, from the user upward; `--json` prints the same order
  in the list envelope `{"items": [...], "count": N, "truncated": false}`.

## `groups`

### `groups list`

| Option | Default | Meaning |
|---|---|---|
| `--unified` | off | Only Microsoft 365 (unified) groups. |
| `--limit N` | 20 | Maximum items. |
| `--all` | off | Fetch every page, cap 999. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/memberOf/microsoft.graph.group?$select=id,displayName,mail,groupTypes,description&$top=100`;
  `--unified` adds `$filter=groupTypes/any(c:c eq 'Unified')&$count=true` and
  `ConsistencyLevel: eventual`.
- **Scopes:** `User.Read`; `Group.Read.All` widens what Graph returns.
- **Tier:** P1

### `groups members GROUP`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 20 | Maximum items. |
| `--all` | off | Fetch every page, cap 999. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /groups/{id}/members?$select=id,displayName,userPrincipalName,mail,jobTitle&$top=100`.
- **Scopes:** `Group.Read.All`
- **Tier:** P1
- **Notes:** `GROUP` may be a group id or a display name from the groups you belong to.

## `teams`

### `teams list`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/joinedTeams` (Graph accepts no OData parameters on this path).
- **Scopes:** `Team.ReadBasic.All` or `Group.Read.All`
- **Tier:** P0
- **Notes:** returns every team, unpaged; there is no `--limit`.

### `teams get TEAM`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /teams/{t}`.
- **Scopes:** `Team.ReadBasic.All` or `Group.Read.All`
- **Tier:** P1
- **Notes:** `TEAM` may be a team id (GUID) or a display name from `teams list`.

### `teams members TEAM`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 100 | Maximum items. |
| `--all` | off | Fetch every page, cap 999. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /teams/{t}/members`.
- **Scopes:** `TeamMember.Read.All`
- **Tier:** P2

### `teams channels TEAM`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /teams/{t}/channels?$select=id,displayName,description,membershipType`.
- **Scopes:** `Channel.ReadBasic.All` or `Group.Read.All`
- **Tier:** P0

### `teams channel get TEAM CHANNEL`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /teams/{t}/channels/{c}`.
- **Scopes:** `Channel.ReadBasic.All` or `Group.Read.All`
- **Tier:** P1
- **Notes:** `CHANNEL` may be a channel id (starts with `19:`) or a display name.

### `teams channel messages TEAM CHANNEL`

| Option | Default | Meaning |
|---|---|---|
| `--full` | off | Print whole bodies, not the first 300 characters. |
| `--with-replies` | off | Expand each message's replies. |
| `--replies MSGID` | — | List the replies to one message instead. |
| `--after DT` | — | Only messages whose reply chain was touched after this. |
| `--before DT` | — | Only messages whose reply chain was touched before this. |
| `--limit N` | 20 | Maximum items. |
| `--all` | off | Fetch every page, cap 200. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /teams/{t}/channels/{c}/messages?$top=50[&$expand=replies]`;
  `--replies`: `GET …/messages/{m}/replies?$top=50`, paged and bounded by `--limit`.
- **Scopes:** `ChannelMessage.Read.All`
- **Tier:** P0
- **Notes:** deleted messages and system placeholders are dropped. Text mode prints oldest first
  with HTML bodies converted to Markdown; JSON keeps Graph's order, newest first.
  `--after`/`--before` add no query parameter: Graph documents `$top` and `$expand` as the only
  ones this endpoint supports, in v1.0 and beta alike, so a `$filter` there would be rejected or —
  worse — ignored, and an ignored one would return an unfiltered page dressed up as a window. The
  window is applied client-side instead, on the last-modified time of the whole reply chain, which
  is the order Graph returns messages in. Because that order is newest first, paging stops at the
  first message older than `--after` rather than walking to the cap. `truncated` then counts
  only the messages inside the window: reaching the far edge is not a truncation, but a cap
  that cut in-window messages short still is. The cap stays 200 for both chat and channel messages — a window that needs more than
  200 messages should be narrowed. `--after`/`--before` do not apply to `--replies` (exit 2), and
  `--after` later than `--before` is a usage error.
  Without `--after`/`--before` the request is byte-for-byte what it was.
  Each message and reply carries `teamId` and `channelId`, which Graph omits on this collection,
  so a message can be routed back to its channel.

### `teams channel send TEAM CHANNEL`

| Option | Default | Meaning |
|---|---|---|
| `--body TEXT` | — | Message text. |
| `--body-file FILE\|-` | — | File holding the text, or `-` for stdin. |
| `--html` | off | Send the body as HTML. |
| `--subject TEXT` | — | Message subject. |
| `--reply-to MSGID` | — | Reply inside that message's thread. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /teams/{t}/channels/{c}/messages`, or `…/messages/{m}/replies` with
  `--reply-to`, body `{subject?, body:{contentType:"text"|"html", content}}`.
- **Scopes:** `ChannelMessage.Send`
- **Tier:** P0
- **Notes:** write. Plain text is sent as `contentType:"text"`, so nothing needs escaping.

## `chats`

### `chats list`

| Option | Default | Meaning |
|---|---|---|
| `--unread` | off | Only chats with unread messages. |
| `--type TYPE` | — | `oneOnOne`, `group` or `meeting`. |
| `--since DT` | — | Only chats whose last message is newer than this. |
| `--limit N` | 20 | Maximum items. |
| `--all` | off | Fetch every page, cap 200. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/chats?$top=50&$expand=members,lastMessagePreview&$orderby=lastMessagePreview/createdDateTime desc&$select=id,topic,chatType,lastUpdatedDateTime,viewpoint,webUrl`.
- **Scopes:** `Chat.Read`
- **Tier:** P0
- **Notes:** unread is computed client-side from `viewpoint.lastMessageReadDateTime` against
  `lastMessagePreview.createdDateTime`, and shows only in text mode. A 1:1 chat is named after the
  other member; a group chat shows its topic or its first three members.
  `--since` adds no query parameter — the listing is already ordered by
  `lastMessagePreview/createdDateTime desc`, so paging simply stops at the first chat whose last
  message predates it, and the chats past that boundary are dropped. Reaching the boundary is not
  a truncation; the 200 cap still is. A chat with no readable preview timestamp says nothing
  about where the boundary is, so it neither stops the fetch nor is dropped from it.
  With `--since`, text mode gains a `lastMessage` column
  showing the timestamp the bound is measured against; the JSON is unchanged either way, since
  `lastMessagePreview` is always expanded.

### `chats get CHAT`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /chats/{id}?$expand=members`.
- **Scopes:** `Chat.Read`
- **Tier:** P1

### `chats members CHAT`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /chats/{id}/members`.
- **Scopes:** `Chat.Read`
- **Tier:** P1

### `chats messages CHAT`

| Option | Default | Meaning |
|---|---|---|
| `--after DT` | — | Only messages last touched after this. |
| `--before DT` | — | Only messages last touched before this. |
| `--full` | off | Print whole bodies, not the first 300 characters. |
| `--limit N` | 20 | Maximum items. |
| `--all` | off | Fetch every page, cap 200. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /chats/{id}/messages?$top=50&$orderby=createdDateTime desc`; with a window,
  `$orderby=lastModifiedDateTime desc&$filter=lastModifiedDateTime gt {after} and lastModifiedDateTime lt {before}`.
- **Scopes:** `Chat.Read`
- **Tier:** P0
- **Notes:** text prints oldest first with Markdown bodies and `[image: hostedContents/<id>]`
  markers; JSON keeps Graph's order, newest first.
  A window filters and orders on `lastModifiedDateTime`, not `createdDateTime`: Graph supports
  `gt`/`lt` only on that property (`createdDateTime` takes `lt` alone), and ignores a `$filter`
  whose property `$orderby` does not also name. So the bounds are the *last touched* time — an
  edited message sorts and filters by its edit, and the oldest-first text order follows that
  same property rather than creation time. Without a window the order stays
  `createdDateTime desc`. `--after` later than `--before` is a usage error.

### `chats send CHAT`

| Option | Default | Meaning |
|---|---|---|
| `--body TEXT` | — | Message text. |
| `--body-file FILE\|-` | — | File holding the text, or `-` for stdin. |
| `--html` | off | Send the body as HTML. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /chats/{id}/messages {body:{contentType:"text"|"html", content}}`.
- **Scopes:** `ChatMessage.Send` (implied by `Chat.ReadWrite`)
- **Tier:** P0
- **Notes:** write.

### `chats dm USER`

| Option | Default | Meaning |
|---|---|---|
| `--body TEXT` | — | Message text. |
| `--body-file FILE\|-` | — | File holding the text, or `-` for stdin. |
| `--html` | off | Send the body as HTML. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /users/{upn}?$select=id,displayName`; then page
  `GET /me/chats?$filter=chatType eq 'oneOnOne'&$expand=members&$top=50` (cap 500) looking for a
  chat with that user; if there is none, `POST /chats {chatType:"oneOnOne", members:[…]}`; then
  `POST /chats/{id}/messages`.
- **Scopes:** `Chat.Read`, `ChatMessage.Send`; creating the chat additionally checks `Chat.Create`
  before the `POST`.
- **Tier:** P0 (creating the chat is P2)
- **Notes:** write. The dry run lists both possible paths, with `{chatId}` standing for the id the
  create step would produce.

### `chats create`

| Option | Default | Meaning |
|---|---|---|
| `--members UPN` | — | Member to add. Repeatable. At least one required. |
| `--topic TEXT` | — | Group chat topic. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /chats {chatType: "oneOnOne" (one member, no topic) | "group", topic, members}`.
- **Scopes:** `Chat.Create`
- **Tier:** P2
- **Notes:** write.

### `chats search Q`

| Option | Default | Meaning |
|---|---|---|
| `--after DT` | — | Only hits after this time. |
| `--before DT` | — | Only hits before this time. |
| `--limit N` | 25 | Maximum items. |
| `--all` | off | Fetch every page, cap 200. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /search/query {requests:[{entityTypes:["chatMessage"], query:{queryString}, from,
  size:25}]}`, paging on `moreResultsAvailable`.
- **Scopes:** `Chat.Read`; channel hits also need `ChannelMessage.Read.All` to read further.
- **Tier:** P0
- **Notes:** the date window is applied client-side on `createdDateTime`. Its body is the Search
  API's `summary` snippet, not the whole message — read the thread with `chats messages` or
  `teams channel messages`.
  Each hit carries its routing twice: `where` is the text column, `chat:<id>` or
  `channel:<teamId>/<channelId>`, and `kind` (`chat`, `channel` or `unknown`) with `chatId`,
  `teamId` and `channelId` give a JSON consumer the same thing as ids, so a hit can be followed
  into a windowed fetch without parsing that string apart. A hit Graph supplied no routing for —
  or only half a `channelIdentity` — is `unknown` with an empty `where`, never
  `channel:None/None`.

### `chats hosted-content CHAT MSGID HCID` | `chats hosted-content URL`

| Option | Default | Meaning |
|---|---|---|
| `--output FILE` | `teams_hosted_<hcid>.<ext>` | Where to write it. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /chats/{c}/messages/{m}/hostedContents/{h}/$value` (streamed). A
  `graph.microsoft.com` URL containing `/hostedContents/` — chat or channel — is used verbatim.
- **Scopes:** `Chat.Read`; a channel URL additionally checks `ChannelMessage.Read.All`.
- **Tier:** P0
- **Notes:** the extension is sniffed from the magic bytes (png, jpg, gif, webp, pdf, svg, bin).

## `presence`

### `presence get [USER...]`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/presence`; with users, `POST /communications/getPresencesByUserId {ids}` after
  resolving each UPN.
- **Scopes:** `Presence.Read`; reading anyone else additionally checks `Presence.Read.All`
  (*on-demand*).
- **Tier:** P2

### `presence set available|busy|dnd|brb|away|offline`

| Option | Default | Meaning |
|---|---|---|
| `--expiration D` | `1h` | How long it lasts (`30m`, `2h`, `PT1H`). |
| `--message TEXT` | — | Status message to show alongside it. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /users/{my-oid}/presence/setUserPreferredPresence {availability, activity,
  expirationDuration}`; `--message` adds `POST …/presence/setStatusMessage`.
- **Scopes:** `Presence.ReadWrite`
- **Tier:** P2
- **Notes:** write. The object id comes from the token's `oid` claim, so there is no `/me` call.

### `presence clear`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /users/{my-oid}/presence/clearUserPreferredPresence`.
- **Scopes:** `Presence.ReadWrite`
- **Tier:** P2
- **Notes:** write. Hands presence back to Teams.

## `meetings`

All `meetings` verbs except `list` select the meeting three ways: a positional online-meeting id,
`--join-url URL`, or `--event EVENT_ID`. Give exactly one.

### `meetings list`

| Option | Default | Meaning |
|---|---|---|
| `--start DT` | today − 7 days | Start of the window. |
| `--end DT` | end of today | End of the window. |
| `--subject KW` | — | Case-insensitive subject substring. |
| `--resolve` | off | Resolve each event to its online-meeting id. |
| `--with-transcripts` | off | Also list transcript ids (implies `--resolve`). |
| `--limit N` | 50 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/calendarView?…&$select=id,subject,start,end,organizer,isOnlineMeeting,onlineMeeting&$top=50`
  with `Prefer: outlook.timezone`, keeping events that have a join URL; `--resolve` adds a
  `POST /$batch` of `GET /me/onlineMeetings?$filter=JoinWebUrl eq '{url}'`;
  `--with-transcripts` adds `GET /me/onlineMeetings/{id}/transcripts` per resolved meeting.
- **Scopes:** `Calendars.Read`; `--resolve` additionally checks `OnlineMeetings.Read`, and
  `--with-transcripts` `OnlineMeetingTranscript.Read.All`.
- **Tier:** P0
- **Notes:** columns: start, subject, event id, meeting id (when resolved), transcript ids.

### `meetings get [MEETING]`

| Option | Default | Meaning |
|---|---|---|
| `--join-url URL` | — | Select the meeting by its join URL. |
| `--event ID` | — | Select the meeting from a calendar event id. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onlineMeetings/{id}`, or
  `GET /me/onlineMeetings?$filter=JoinWebUrl eq '{url}'`.
- **Scopes:** `OnlineMeetings.Read`
- **Tier:** P1

### `meetings transcripts [MEETING]`

| Option | Default | Meaning |
|---|---|---|
| `--join-url URL` | — | Select the meeting by its join URL. |
| `--event ID` | — | Select the meeting from a calendar event id. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onlineMeetings/{id}/transcripts`.
- **Scopes:** `OnlineMeetingTranscript.Read.All`
- **Tier:** P0

### `meetings transcript [MEETING] TRANSCRIPT_ID`

| Option | Default | Meaning |
|---|---|---|
| `--join-url URL` | — | Select the meeting by its join URL. |
| `--event ID` | — | Select the meeting from a calendar event id. |
| `--format FMT` | `text` | `text` or `vtt`. |
| `--speakers` | off | Merge each speaker's consecutive cues into one turn. |
| `--output FILE` | — | Write to this file instead of stdout. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onlineMeetings/{m}/transcripts/{t}/content?$format=text/vtt` (streamed). A 403
  `SpeakerAttributionNotAllowed` is retried with
  `Accept: application/vnd.microsoft.graph.transcript+text`. With `--json`, one extra
  `GET /me/onlineMeetings/{m}/transcripts` supplies `createdDateTime`.
- **Scopes:** `OnlineMeetingTranscript.Read.All`
- **Tier:** P0
- **Notes:** with `--join-url` or `--event` the single positional argument is the transcript id;
  otherwise give the meeting id and then the transcript id. `text` converts the VTT locally into
  `[HH:MM:SS] Speaker: line`, one line per cue.
  JSON is `{"meetingId","transcriptId","createdDateTime","format","content"}`.
  `format` is **sniffed from the body**, not taken from `--format`: the speaker-attribution
  fallback answers in plain text even to a vtt request, and some meeting types answer in vtt to a
  text one, so the field says what the content actually is. `--output` reports the same sniffed
  value. `createdDateTime` costs one extra listing request, so only `--json` pays it, and a failed
  lookup leaves the field `null` rather than failing the command — the content is already in hand.
  `--speakers` renders `**Speaker:** text` turns, merging a speaker's consecutive cues into one
  and separating turns with a blank line, which is what makes a transcript readable; a cue with no
  `<v>` tag continues the turn it falls inside. It respects `--output`, and combined with
  `--format vtt` is a usage error rather than a silent override.

### `meetings insights [MEETING]`

| Option | Default | Meaning |
|---|---|---|
| `--join-url URL` | — | Select the meeting by its join URL. |
| `--event ID` | — | Select the meeting from a calendar event id. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /copilot/users/{oid}/onlineMeetings/{m}/aiInsights` on `/v1.0`, falling back to
  the same path on `/beta` on a 404; then `GET …/aiInsights/{id}` per item.
- **Scopes:** `OnlineMeetingAiInsight.Read.All`
- **Tier:** P0
- **Notes:** needs a Microsoft 365 Copilot licence. A 403 prints
  `AI insights require a Microsoft 365 Copilot license…` and **exits 0**; an empty or missing recap
  is likewise a soft message with exit 0 and a `note` in the JSON. Insights can take up to a few
  hours after a meeting ends to appear.

### `meetings recordings [MEETING]`

| Option | Default | Meaning |
|---|---|---|
| `--join-url URL` | — | Select the meeting by its join URL. |
| `--event ID` | — | Select the meeting from a calendar event id. |
| `--download RID` | — | Recording id to download. |
| `--output FILE` | — | File to write the recording to. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onlineMeetings/{id}/recordings`; `--download`:
  `GET …/recordings/{rid}/content` (streamed).
- **Scopes:** `OnlineMeetingRecording.Read.All` (*on-demand*)
- **Tier:** P2
- **Notes:** the missing-scope hint names `login --scope OnlineMeetingRecording.Read.All`.

## `onedrive`

`ls`, `search`, `get`, `download`, `upload`, `mkdir`, `move`, `rename`, `delete` and `share` accept
`--drive DRIVE_ID` to work against another drive; the base is `/me/drive`, or `/drives/{id}` with
`--drive`. `recent`, `shared-with-me` and `link` are always about the signed-in user's own drive.

A file or folder is named either by id (`id:ID`, or a bare id-shaped string) or by path
(`/Reports/2026/plan.xlsx`).

### `onedrive ls [PATH]`

| Option | Default | Meaning |
|---|---|---|
| `--drive ID` | your drive | Target another drive. |
| `--limit N` | 50 | Maximum items. |
| `--all` | off | Fetch every page, cap 1000. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET {base}/root/children`, or `GET {base}/root:/{path}:/children`, with
  `$top=200&$select=id,name,size,lastModifiedDateTime,file,folder,webUrl,parentReference&$orderby=name`.
- **Scopes:** `Files.Read`
- **Tier:** P0
- **Notes:** columns: type (`d`/`f`), id, size, modified, name.

### `onedrive search Q`

| Option | Default | Meaning |
|---|---|---|
| `--drive ID` | your drive | Target another drive. |
| `--shared` | off | Search everything shared with you as well. |
| `--limit N` | 50 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET {base}/root/search(q='{q}')`, or `GET {base}/search(q='{q}')` with `--shared`,
  which also returns remote items.
- **Scopes:** `Files.Read`
- **Tier:** P1

### `onedrive get ID|PATH`

| Option | Default | Meaning |
|---|---|---|
| `--drive ID` | your drive | Target another drive. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET {base}/items/{id}`, or `GET {base}/root:/{path}`.
- **Scopes:** `Files.Read`
- **Tier:** P0

### `onedrive download ID|PATH`

| Option | Default | Meaning |
|---|---|---|
| `--drive ID` | your drive | Target another drive. |
| `--output FILE` | the item name | Destination file. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET {base}/items/{id}/content` or `GET {base}/root:/{path}:/content`; the 302 is
  followed without the bearer token.
- **Scopes:** `Files.Read`
- **Tier:** P0
- **Notes:** writes `<dest>.part` and renames it, creating parent directories and overwriting an
  existing file. Prints `Downloaded <name> (<size>) to <path>`.

### `onedrive upload FILE`

| Option | Default | Meaning |
|---|---|---|
| `--drive ID` | your drive | Target another drive. |
| `--dest PATH` | `/<basename>` | Destination path; a trailing `/` means a folder. |
| `--conflict MODE` | `replace` | `rename`, `replace` or `fail`. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** under 4 MiB, `PUT {base}/root:/{path}:/content?@microsoft.graph.conflictBehavior=…`;
  above it, `POST {base}/root:/{path}:/createUploadSession` followed by 10 MiB chunks.
- **Scopes:** `Files.ReadWrite`
- **Tier:** P0
- **Notes:** write. The dry run shows the file as `{"$file": …, "bytes": N, "contentType": …}`.

### `onedrive mkdir PATH`

| Option | Default | Meaning |
|---|---|---|
| `--drive ID` | your drive | Target another drive. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST {base}/root:/{parent}:/children {name, folder:{},
  "@microsoft.graph.conflictBehavior":"fail"}`.
- **Scopes:** `Files.ReadWrite`
- **Tier:** P1
- **Notes:** write. Fails rather than silently reusing an existing folder.

### `onedrive move ID|PATH`

| Option | Default | Meaning |
|---|---|---|
| `--to FOLDER\|id:ID` | — | Destination folder. Required. |
| `--drive ID` | your drive | Target another drive. |
| `--name NAME` | — | Rename while moving. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `PATCH {base}/items/{id} {parentReference:{id}, name?}`, after a `GET` to resolve the
  destination folder.
- **Scopes:** `Files.ReadWrite`
- **Tier:** P1
- **Notes:** write.

### `onedrive rename ID|PATH NAME`

| Option | Default | Meaning |
|---|---|---|
| `--drive ID` | your drive | Target another drive. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `PATCH {base}/items/{id} {name}`.
- **Scopes:** `Files.ReadWrite`
- **Tier:** P1
- **Notes:** write.

### `onedrive delete ID|PATH`

| Option | Default | Meaning |
|---|---|---|
| `--drive ID` | your drive | Target another drive. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `DELETE {base}/items/{id}`.
- **Scopes:** `Files.ReadWrite`
- **Tier:** P1
- **Notes:** write. Moves the item to the recycle bin.

### `onedrive share ID|PATH`

| Option | Default | Meaning |
|---|---|---|
| `--drive ID` | your drive | Target another drive. |
| `--type KIND` | `view` | `view` or `edit`. |
| `--scope WHO` | `organization` | `organization` or `anonymous`. |
| `--expires DT` | — | When the link stops working. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST {base}/items/{id}/createLink {type, scope, expirationDateTime}`.
- **Scopes:** `Files.ReadWrite`
- **Tier:** P1
- **Notes:** write. Prints `link.webUrl`. Anonymous links are blocked by policy in many tenants —
  a 403 there is a tenant setting, not a missing scope.

### `onedrive shared-with-me`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 50 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/drive/sharedWithMe`.
- **Scopes:** `Files.Read.All` or `Sites.Read.All`
- **Tier:** P1
- **Notes:** Microsoft is retiring this endpoint; a stderr note says so. Each item carries a
  `remoteItem` whose `driveId` and `id` are shown, and which `onedrive get --drive` can open.

### `onedrive recent`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 20 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/drive/recent`.
- **Scopes:** `Files.Read`
- **Tier:** P1

### `onedrive link URL`

| Option | Default | Meaning |
|---|---|---|
| `--download` | off | Download the item's content. |
| `--output FILE` | the item name | Destination file for `--download`. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /shares/{share_id(url)}/driveItem`; `--download` adds `…/driveItem/content`.
- **Scopes:** `Files.Read` (plus whatever access the link itself grants)
- **Tier:** P1
- **Notes:** works for OneDrive and SharePoint sharing links alike.

## `sharepoint`

`SITE` accepts a site URL, a `host:/sites/name` reference, a composite site id, or a site name to
search for.

### `sharepoint sites`

| Option | Default | Meaning |
|---|---|---|
| `--search Q` | — | Search text; `*` matches everything. |
| `--limit N` | 20 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/followedSites?$select=id,displayName,webUrl`; with `--search`, or when the
  followed list is empty, `GET /sites?search={Q or *}&$top={limit}`.
- **Scopes:** `Sites.Read.All`
- **Tier:** P0

### `sharepoint site REF`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /sites/{ref}?$select=id,displayName,name,webUrl,description`.
- **Scopes:** `Sites.Read.All`
- **Tier:** P0
- **Notes:** use this to turn a URL a colleague sent into the site id the other verbs take.

### `sharepoint drives SITE`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /sites/{id}/drives?$select=id,name,webUrl,driveType`.
- **Scopes:** `Sites.Read.All`
- **Tier:** P1

### `sharepoint ls SITE [PATH]`

| Option | Default | Meaning |
|---|---|---|
| `--drive NAME\|ID` | the site's default drive | Which document library. |
| `--limit N` | 50 | Maximum items. |
| `--all` | off | Fetch every page, cap 1000. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** as `onedrive ls`, with the base `/sites/{id}/drive` or `/drives/{d}`.
- **Scopes:** `Sites.Read.All`
- **Tier:** P0
- **Notes:** item ids are printed in full, so they can be fed straight to `sharepoint download`.

### `sharepoint search Q`

| Option | Default | Meaning |
|---|---|---|
| `--site SITE` | — | Search within one site's drive instead of everywhere. |
| `--limit N` | 25 | Maximum items. |
| `--all` | off | Fetch every page, cap 200. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** with `--site`, `GET /sites/{id}/drive/root/search(q='{q}')`; without it,
  `POST /search/query` with `entityTypes:["driveItem"]` and size 25.
- **Scopes:** `Sites.Read.All`
- **Tier:** P1

### `sharepoint download SITE ITEM|PATH`

| Option | Default | Meaning |
|---|---|---|
| `--output FILE` | the item name | Destination file. |
| `--drive NAME\|ID` | the site's default drive | Which document library. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /sites/{id}/drive/items/{item}/content`, or
  `GET /drives/{d}/root:/{path}:/content`.
- **Scopes:** `Sites.Read.All`
- **Tier:** P0
- **Notes:** reads the **site** drive, not the signed-in user's OneDrive.

### `sharepoint upload SITE FILE`

| Option | Default | Meaning |
|---|---|---|
| `--dest PATH` | `/<basename>` | Destination path in the library. |
| `--drive NAME\|ID` | the site's default drive | Which document library. |
| `--conflict MODE` | `replace` | `rename`, `replace` or `fail`. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** as `onedrive upload`, with the site drive as the base.
- **Scopes:** `Sites.ReadWrite.All`
- **Tier:** P1
- **Notes:** write.

### `sharepoint url URL`

| Option | Default | Meaning |
|---|---|---|
| `--output FILE` | the file's own name | Destination file. |
| `--info` | off | Resolve and print, without downloading. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** first `GET /shares/{share_id(url)}/driveItem`; on a 4xx it parses the URL's host and
  `sites`/`teams`/`personal` segment, resolves the site and its drives, picks the drive whose
  `webUrl` is the deepest prefix of the file path, and reads
  `GET /drives/{d}/root:/{rel}:/content`, with `GET /sites/{id}/drive/root:/{rel}:/content` as a
  last resort.
- **Scopes:** `Sites.Read.All`
- **Tier:** P0
- **Notes:** the fastest way to open a link someone pasted into chat or mail. `--info` prints the
  resolution — site id, drive id, path, item — and downloads nothing; JSON includes `resolution`.
  A `/personal/` (OneDrive) URL needs the owner to have shared the file with you.

### `sharepoint lists SITE`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /sites/{id}/lists?$select=id,displayName,webUrl,list`.
- **Scopes:** `Sites.Read.All`
- **Tier:** P1
- **Notes:** system lists are hidden.

### `sharepoint items SITE LIST`

| Option | Default | Meaning |
|---|---|---|
| `--fields a,b` | every field | Which columns to fetch. |
| `--filter ODATA` | — | OData filter over `fields/*`. |
| `--limit N` | 50 | Maximum items. |
| `--all` | off | Fetch every page, cap 500. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /sites/{id}/lists/{l}/items?$expand=fields($select=…)&$top=200[&$filter=…]`, with
  `Prefer: HonorNonIndexedQueriesWarningMayFailRandomly` when `--filter` is given.
- **Scopes:** `Sites.Read.All`
- **Tier:** P1
- **Notes:** text shows the first eight fields as columns; use `--json` to see them all. A filter on
  an unindexed column may fail intermittently — that is the SharePoint list threshold, not a bug.

## `onenote`

### `onenote notebooks`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 50 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onenote/notebooks?$top=100&$select=id,displayName,lastModifiedDateTime,links`.
- **Scopes:** `Notes.Read`
- **Tier:** P0

### `onenote sections [NOTEBOOK]`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 50 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onenote/notebooks/{id}/sections`, or `GET /me/onenote/sections` across every
  notebook, with `$top=100&$select=id,displayName,lastModifiedDateTime,parentNotebook`.
- **Scopes:** `Notes.Read`
- **Tier:** P0

### `onenote pages SECTION`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 50 | Maximum items. |
| `--all` | off | Fetch every page, cap 500. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onenote/sections/{id}/pages?$top=100&$select=id,title,lastModifiedDateTime,links&$orderby=lastModifiedDateTime desc`.
- **Scopes:** `Notes.Read`
- **Tier:** P0

### `onenote read PAGE`

| Option | Default | Meaning |
|---|---|---|
| `--html` | off | Print the page's raw HTML instead of Markdown. |
| `--output FILE` | — | Write to this file instead of stdout. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onenote/pages/{id}?$select=id,title,lastModifiedDateTime,links` plus
  `GET /me/onenote/pages/{id}/content?includeIDs=true`.
- **Scopes:** `Notes.Read`
- **Tier:** P0
- **Notes:** JSON carries `{"id","title","html","markdown"}`.

### `onenote create`

| Option | Default | Meaning |
|---|---|---|
| `--section SECTION` | — | Section name or id. Required. |
| `--title TEXT` | — | Page title. Required. |
| `--body TEXT` | — | Page body text. |
| `--body-file FILE\|-` | — | File holding the body, or `-` for stdin. |
| `--html` | off | Treat the body as raw HTML, unescaped. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/onenote/sections/{id}/pages` with `Content-Type: text/html` and a minimal
  HTML document carrying the title and body.
- **Scopes:** `Notes.ReadWrite`
- **Tier:** P0
- **Notes:** write. The title and body are HTML-escaped unless `--html` is given.

### `onenote search Q`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 50 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onenote/pages?$search={Q}&$top=100&$select=id,title,createdDateTime,parentSection`.
- **Scopes:** `Notes.Read`
- **Tier:** P0
- **Notes:** Graph documents `$search` here for consumer notebooks only. On a work account it may
  return 400 or 501; that error is passed through with the hint to use
  `search Q --type driveItem` instead.

## `planner`

Planner endpoints accept no OData parameters, so `--limit` slices client-side after the whole
collection has been fetched.

### `planner plans`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 50 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/planner/plans`, unioned with the plans of every Microsoft 365 group you belong
  to — `GET /me/memberOf/microsoft.graph.group?$filter=groupTypes/any(c:c eq 'Unified')&$count=true`
  with `ConsistencyLevel: eventual`, then a `POST /$batch` of `GET /groups/{id}/planner/plans` —
  deduplicated by id.
- **Scopes:** `Tasks.ReadWrite`, `Group.Read.All`
- **Tier:** P0
- **Notes:** text shows the owning group's name next to each plan.

### `planner plan PLAN`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /planner/plans/{id}` plus `GET /planner/plans/{id}/details`.
- **Scopes:** `Tasks.ReadWrite`
- **Tier:** P1
- **Notes:** JSON is the plan with a `details` member.

### `planner buckets PLAN`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /planner/plans/{id}/buckets`.
- **Scopes:** `Tasks.ReadWrite`
- **Tier:** P0

### `planner tasks [PLAN]`

| Option | Default | Meaning |
|---|---|---|
| `--my` | off | Your tasks across every plan, instead of one plan's tasks. |
| `--bucket NAME\|ID` | — | Only tasks in this bucket. |
| `--include-completed` | off | Also show tasks at 100 %. |
| `--limit N` | 50 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /planner/plans/{id}/tasks`, or `GET /me/planner/tasks` with `--my`; `--my` adds a
  `POST /$batch` of `GET /planner/plans/{planId}` (up to 20 distinct plans) for plan titles, and
  bucket names are fetched for the plans involved.
- **Scopes:** `Tasks.ReadWrite`
- **Tier:** P0
- **Notes:** completed tasks are hidden unless `--include-completed`. Columns: id, percent,
  priority, due, bucket, plan (with `--my`), title.

### `planner task ID`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /planner/tasks/{id}` plus `GET /planner/tasks/{id}/details`.
- **Scopes:** `Tasks.ReadWrite`
- **Tier:** P0
- **Notes:** an error fetching the details is swallowed; the task still prints.

### `planner create`

| Option | Default | Meaning |
|---|---|---|
| `--plan PLAN` | — | Plan name or id. Required. |
| `--title TEXT` | — | Task title. Required. |
| `--bucket NAME\|ID` | — | Bucket to file it under. |
| `--due DATE` | — | Due date. |
| `--assign UPN` | — | Assignee. Repeatable. |
| `--priority 0-10` | — | Planner priority. |
| `--description TEXT` | — | Task description. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /users/{upn}?$select=id` per assignee, then
  `POST /planner/tasks {planId, bucketId, title, dueDateTime, priority, assignments}`;
  `--description` adds `GET …/details` for the etag and `PATCH …/details` with `If-Match`.
- **Scopes:** `Tasks.ReadWrite`
- **Tier:** P0
- **Notes:** write. Assignees are given as UPNs, not object ids.

### `planner update ID`

| Option | Default | Meaning |
|---|---|---|
| `--title TEXT` | — | New title. |
| `--due DATE` | — | New due date. |
| `--percent N` | — | Completion: 0, 50 or 100. |
| `--bucket NAME\|ID` | — | Move to another bucket. |
| `--priority 0-10` | — | New priority. |
| `--assign UPN` | — | Add an assignee. Repeatable. |
| `--unassign UPN` | — | Remove an assignee. Repeatable. |
| `--description TEXT` | — | New description. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /planner/tasks/{id}` for the etag, then `PATCH /planner/tasks/{id}` with
  `If-Match` and `Prefer: return=representation`; a 412 re-reads the etag once and retries.
- **Scopes:** `Tasks.ReadWrite`
- **Tier:** P1
- **Notes:** write. Planner tracks completion as a percentage; Planner's own UI only ever sets
  0, 50 or 100.

### `planner complete ID`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** the `planner update` request with `percentComplete: 100`.
- **Scopes:** `Tasks.ReadWrite`
- **Tier:** P0
- **Notes:** write.

### `planner delete ID`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /planner/tasks/{id}` for the etag, then `DELETE /planner/tasks/{id}` with
  `If-Match`.
- **Scopes:** `Tasks.ReadWrite`
- **Tier:** P1
- **Notes:** write. Planner has no recycle bin — a deleted task is gone.

## `todo`

`LIST` accepts a list id, the well-known names `defaultList` and `flaggedEmails`, or a list's
display name.

### `todo lists`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/todo/lists?$top=100`.
- **Scopes:** `Tasks.ReadWrite`
- **Tier:** P0
- **Notes:** shows each list's `wellknownListName` where it has one.

### `todo tasks LIST`

| Option | Default | Meaning |
|---|---|---|
| `--include-completed` | off | Also show completed tasks. |
| `--limit N` | 50 | Maximum items. |
| `--all` | off | Fetch every page, cap 500. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/todo/lists/{l}/tasks?$top=100[&$filter=status ne 'completed']` with
  `Prefer: outlook.timezone`.
- **Scopes:** `Tasks.ReadWrite`
- **Tier:** P0
- **Notes:** columns: id, status, importance, due, title.

### `todo task LIST ID`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/todo/lists/{l}/tasks/{t}?$expand=checklistItems,linkedResources` with
  `Prefer: outlook.timezone`.
- **Scopes:** `Tasks.ReadWrite`
- **Tier:** P1

### `todo create LIST`

| Option | Default | Meaning |
|---|---|---|
| `--title TEXT` | — | Task title. Required. |
| `--due DT` | — | Due date. |
| `--body TEXT` | — | Task notes. |
| `--importance LEVEL` | — | `low`, `normal` or `high`. |
| `--reminder DT` | — | Reminder time; also turns the reminder on. |
| `--start DT` | — | Start date. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/todo/lists/{l}/tasks {title, body, importance, dueDateTime, reminderDateTime,
  isReminderOn, startDateTime}`, dates sent in the active time zone.
- **Scopes:** `Tasks.ReadWrite`
- **Tier:** P0
- **Notes:** write.

### `todo update LIST ID`

| Option | Default | Meaning |
|---|---|---|
| `--title` / `--due` / `--body` / `--importance` / `--reminder` / `--start` | — | The `todo create` fields. |
| `--status STATE` | — | `notStarted`, `inProgress`, `completed`, `waitingOnOthers`, `deferred`. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `PATCH /me/todo/lists/{l}/tasks/{t}` with only the fields given.
- **Scopes:** `Tasks.ReadWrite`
- **Tier:** P1
- **Notes:** write.

### `todo complete LIST ID`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `PATCH /me/todo/lists/{l}/tasks/{t} {status:"completed"}`.
- **Scopes:** `Tasks.ReadWrite`
- **Tier:** P0
- **Notes:** write.

### `todo delete LIST ID`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `DELETE /me/todo/lists/{l}/tasks/{t}`.
- **Scopes:** `Tasks.ReadWrite`
- **Tier:** P1
- **Notes:** write.

### `todo from-mail LIST MSGID`

| Option | Default | Meaning |
|---|---|---|
| `--title TEXT` | the message subject | Task title. |
| `--due DT` | — | Due date. |
| `--importance LEVEL` | — | `low`, `normal` or `high`. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/messages/{id}?$select=subject,webLink,bodyPreview,from,receivedDateTime`, then
  `POST /me/todo/lists/{l}/tasks` with the sender and preview in the body and a `linkedResources`
  entry pointing back at the message in Outlook.
- **Scopes:** `Tasks.ReadWrite`, `Mail.Read`
- **Tier:** P1
- **Notes:** write. The task carries a working link back to the original mail.

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
| `MGRAPHCTL_CLIENT_ID` | the shared public client id | Entra application to authenticate as. |
| `MGRAPHCTL_TENANT_ID` | `common` | Authority `https://login.microsoftonline.com/<tenant>`. |
| `MGRAPHCTL_SCOPES` | `default` | `default`, `extended`, or an explicit scope list. `login --scopes` overrides it. |
| `MGRAPHCTL_TOKEN_CACHE` | `~/.mgraphctl/token_cache.json` | Where the msal cache lives (mode 0600). |
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
retries       = 2
timeout_ms    = 30000
```
