# `org`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

### `org manager [UPN]`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/manager` or `GET /users/{upn}/manager` with
  `$select=id,displayName,userPrincipalName,mail,jobTitle,department`.
- **Scopes:** `User.Read`; another user additionally checks `User.Read.All` (*on-demand*).
- **Beyond `default`:** only for another user.
- **Notes:** no manager on record → `No manager found`, exit 4.

### `org reports [UPN]`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 20 | Maximum items. |
| `--all` | off | Fetch every page, cap 500. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/directReports` or `GET /users/{upn}/directReports` with the same `$select`.
- **Scopes:** `User.Read`; another user additionally checks `User.Read.All` (*on-demand*).
- **Beyond `default`:** only for another user.

### `org chain [UPN]`

| Option | Default | Meaning |
|---|---|---|
| `--max N` | 10 | Maximum levels to climb. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me?$expand=manager($levels=max;$select=id,displayName,userPrincipalName,jobTitle)&$count=true`
  with `ConsistencyLevel: eventual`; on 400 or 403 it falls back to walking
  `GET /users/{id}/manager` one level at a time, up to `--max`.
- **Scopes:** `User.Read`; the iterative fallback additionally checks `User.Read.All` (*on-demand*).
- **Notes:** text prints one line per level, from the user upward; `--json` prints the same order
  in the list envelope `{"items": [...], "count": N, "truncated": false}`.
