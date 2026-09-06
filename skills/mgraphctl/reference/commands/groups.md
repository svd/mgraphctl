# `groups`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

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

### `groups members GROUP`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 20 | Maximum items. |
| `--all` | off | Fetch every page, cap 999. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /groups/{id}/members?$select=id,displayName,userPrincipalName,mail,jobTitle&$top=100`.
- **Scopes:** `Group.Read.All`
- **Notes:** `GROUP` may be a group id or a display name from the groups you belong to.
