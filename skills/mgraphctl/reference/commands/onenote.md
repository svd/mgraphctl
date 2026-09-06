# `onenote`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

### `onenote notebooks`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 50 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onenote/notebooks?$top=100&$select=id,displayName,lastModifiedDateTime,links`.
- **Scopes:** `Notes.Read`

### `onenote sections [NOTEBOOK]`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 50 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onenote/notebooks/{id}/sections`, or `GET /me/onenote/sections` across every
  notebook, with `$top=100&$select=id,displayName,lastModifiedDateTime,parentNotebook`.
- **Scopes:** `Notes.Read`

### `onenote pages SECTION`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 50 | Maximum items. |
| `--all` | off | Fetch every page, cap 500. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onenote/sections/{id}/pages?$top=100&$select=id,title,lastModifiedDateTime,links&$orderby=lastModifiedDateTime desc`.
- **Scopes:** `Notes.Read`

### `onenote read PAGE`

| Option | Default | Meaning |
|---|---|---|
| `--html` | off | Print the page's raw HTML instead of Markdown. |
| `--output FILE` | — | Write to this file instead of stdout. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onenote/pages/{id}?$select=id,title,lastModifiedDateTime,links` plus
  `GET /me/onenote/pages/{id}/content?includeIDs=true`.
- **Scopes:** `Notes.Read`
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
- **Notes:** write. The title and body are HTML-escaped unless `--html` is given.

### `onenote search Q`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 50 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onenote/pages?$search={Q}&$top=100&$select=id,title,createdDateTime,parentSection`.
- **Scopes:** `Notes.Read`
- **Notes:** Graph documents `$search` here for consumer notebooks only. On a work account it may
  return 400 or 501; that error is passed through with the hint to use
  `search Q --type driveItem` instead.
