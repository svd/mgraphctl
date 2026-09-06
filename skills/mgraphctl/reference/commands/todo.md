# `todo`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

`LIST` accepts a list id, the well-known names `defaultList` and `flaggedEmails`, or a list's
display name.

### `todo lists`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/todo/lists?$top=100`.
- **Scopes:** `Tasks.ReadWrite`
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
- **Notes:** columns: id, status, importance, due, title.

### `todo task LIST ID`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/todo/lists/{l}/tasks/{t}?$expand=checklistItems,linkedResources` with
  `Prefer: outlook.timezone`.
- **Scopes:** `Tasks.ReadWrite`

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
- **Notes:** write.

### `todo complete LIST ID`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `PATCH /me/todo/lists/{l}/tasks/{t} {status:"completed"}`.
- **Scopes:** `Tasks.ReadWrite`
- **Notes:** write.

### `todo delete LIST ID`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `DELETE /me/todo/lists/{l}/tasks/{t}`.
- **Scopes:** `Tasks.ReadWrite`
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
- **Notes:** write. The task carries a working link back to the original mail.
