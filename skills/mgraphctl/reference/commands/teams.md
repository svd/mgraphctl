# `teams`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

### `teams list`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/joinedTeams` (Graph accepts no OData parameters on this path).
- **Scopes:** `Team.ReadBasic.All` or `Group.Read.All`
- **Notes:** returns every team, unpaged; there is no `--limit`.

### `teams get TEAM`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /teams/{t}`.
- **Scopes:** `Team.ReadBasic.All` or `Group.Read.All`
- **Notes:** `TEAM` may be a team id (GUID) or a display name from `teams list`.

### `teams members TEAM`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 100 | Maximum items. |
| `--all` | off | Fetch every page, cap 999. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /teams/{t}/members`.
- **Scopes:** `TeamMember.Read.All`
- **Beyond `default`:** always.

### `teams channels TEAM`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /teams/{t}/channels?$select=id,displayName,description,membershipType`.
- **Scopes:** `Channel.ReadBasic.All` or `Group.Read.All`

### `teams channel get TEAM CHANNEL`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /teams/{t}/channels/{c}`.
- **Scopes:** `Channel.ReadBasic.All` or `Group.Read.All`
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
- **Notes:** write. Plain text is sent as `contentType:"text"`, so nothing needs escaping.
