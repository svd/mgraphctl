# `presence`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

### `presence get [USER...]`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/presence`; with users, `POST /communications/getPresencesByUserId {ids}` after
  resolving each UPN.
- **Scopes:** `Presence.Read`; reading anyone else additionally checks `Presence.Read.All`
  (*on-demand*).
- **Beyond `default`:** always.

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
- **Beyond `default`:** always.
- **Notes:** write. The object id comes from the token's `oid` claim, so there is no `/me` call.

### `presence clear`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /users/{my-oid}/presence/clearUserPreferredPresence`.
- **Scopes:** `Presence.ReadWrite`
- **Beyond `default`:** always.
- **Notes:** write. Hands presence back to Teams.
