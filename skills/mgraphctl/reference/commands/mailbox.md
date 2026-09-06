# `mailbox`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

### `mailbox settings`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/mailboxSettings`.
- **Scopes:** `MailboxSettings.Read`
- **Beyond `default`:** always.
- **Notes:** shows the mailbox time zone, language, working hours and automatic-replies status.

### `mailbox oof get`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/mailboxSettings/automaticRepliesSetting`.
- **Scopes:** `MailboxSettings.Read`
- **Beyond `default`:** always.

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
- **Beyond `default`:** always.
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
- **Notes:** `receivedDateTime` leads the filter so the `$orderby` stays efficient.
