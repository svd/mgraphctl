# `chats`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

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

### `chats members CHAT`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /chats/{id}/members`.
- **Scopes:** `Chat.Read`

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
- **Beyond `default`:** only when it has to create the chat.
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
- **Beyond `default`:** always.
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
- **Notes:** the extension is sniffed from the magic bytes (png, jpg, gif, webp, pdf, svg, bin).
