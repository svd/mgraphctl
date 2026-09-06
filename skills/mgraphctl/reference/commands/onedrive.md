# `onedrive`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

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

### `onedrive get ID|PATH`

| Option | Default | Meaning |
|---|---|---|
| `--drive ID` | your drive | Target another drive. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET {base}/items/{id}`, or `GET {base}/root:/{path}`.
- **Scopes:** `Files.Read`

### `onedrive download ID|PATH`

| Option | Default | Meaning |
|---|---|---|
| `--drive ID` | your drive | Target another drive. |
| `--output FILE` | the item name | Destination file. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET {base}/items/{id}/content` or `GET {base}/root:/{path}:/content`; the 302 is
  followed without the bearer token.
- **Scopes:** `Files.Read`
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
- **Notes:** write.

### `onedrive rename ID|PATH NAME`

| Option | Default | Meaning |
|---|---|---|
| `--drive ID` | your drive | Target another drive. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `PATCH {base}/items/{id} {name}`.
- **Scopes:** `Files.ReadWrite`
- **Notes:** write.

### `onedrive delete ID|PATH`

| Option | Default | Meaning |
|---|---|---|
| `--drive ID` | your drive | Target another drive. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `DELETE {base}/items/{id}`.
- **Scopes:** `Files.ReadWrite`
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
- **Notes:** write. Prints `link.webUrl`. Anonymous links are blocked by policy in many tenants —
  a 403 there is a tenant setting, not a missing scope.

### `onedrive shared-with-me`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 50 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/drive/sharedWithMe`.
- **Scopes:** `Files.Read.All` or `Sites.Read.All`
- **Notes:** Microsoft is retiring this endpoint; a stderr note says so. Each item carries a
  `remoteItem` whose `driveId` and `id` are shown, and which `onedrive get --drive` can open.

### `onedrive recent`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 20 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/drive/recent`.
- **Scopes:** `Files.Read`

### `onedrive link URL`

| Option | Default | Meaning |
|---|---|---|
| `--download` | off | Download the item's content. |
| `--output FILE` | the item name | Destination file for `--download`. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /shares/{share_id(url)}/driveItem`; `--download` adds `…/driveItem/content`.
- **Scopes:** `Files.Read` (plus whatever access the link itself grants)
- **Notes:** works for OneDrive and SharePoint sharing links alike.
