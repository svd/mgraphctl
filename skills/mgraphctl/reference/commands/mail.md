# `mail`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

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
- **Notes:** in search mode `--unread` is applied client-side, because KQL has no `isRead` term.
  So are `--after`/`--before` when they carry a time of day: KQL's `received` compares on the
  calendar date only, so `--after 2026-09-02T14:00` reaches Graph as `received>=2026-09-02` and the
  earlier part of that day is dropped here. A date-only bound needs no such pass and gets none.
  Both passes run after paging, so a filtered page can be shorter than `--limit` while
  `truncated` is still true.
  Columns: id, received, flags (`*` unread, `A` attachment, `!` high importance), from, subject.
  The default folder is the Inbox; pass `--folder all` to list the whole mailbox.

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
- **Beyond `default`:** only on the draft path.
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
- **Beyond `default`:** always.
- **Notes:** write. Takes any number of ids. JSON is the list envelope even for a single id.

### `mail move ID`

| Option | Default | Meaning |
|---|---|---|
| `--folder NAME\|ID` | — | Destination folder. Required. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/messages/{id}/move {destinationId}`.
- **Scopes:** `Mail.ReadWrite`
- **Beyond `default`:** always.
- **Notes:** write. Returns the **new** message: the id changes, so any id captured before the move
  is dead. Re-list after moving.

### `mail delete ID`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `DELETE /me/messages/{id}`.
- **Scopes:** `Mail.ReadWrite`
- **Beyond `default`:** always.
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
- **Beyond `default`:** always.
- **Notes:** write. Returns the draft, including the id `mail drafts send` needs.

### `mail drafts send ID`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/messages/{id}/send`.
- **Scopes:** `Mail.ReadWrite`, `Mail.Send`
- **Beyond `default`:** always.
- **Notes:** write.

### `mail rules list`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/mailFolders/inbox/messageRules`.
- **Scopes:** `MailboxSettings.Read`
- **Beyond `default`:** always.
- **Notes:** read-only. Columns: id, sequence, enabled, name, actions summary.

### `mail categories`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/outlook/masterCategories`.
- **Scopes:** `MailboxSettings.Read`
- **Beyond `default`:** always.
