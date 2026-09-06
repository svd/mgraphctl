# `sharepoint`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

`SITE` accepts a site URL, a `host:/sites/name` reference, a composite site id, or a site name to
search for.

### `sharepoint sites`

| Option | Default | Meaning |
|---|---|---|
| `--search Q` | — | Search text; `*` matches everything. |
| `--limit N` | 20 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/followedSites?$select=id,displayName,webUrl`; with `--search`, or when the
  followed list is empty, `GET /sites?search={Q or *}&$top={limit}`.
- **Scopes:** `Sites.Read.All`

### `sharepoint site REF`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /sites/{ref}?$select=id,displayName,name,webUrl,description`.
- **Scopes:** `Sites.Read.All`
- **Notes:** use this to turn a URL a colleague sent into the site id the other verbs take.

### `sharepoint drives SITE`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /sites/{id}/drives?$select=id,name,webUrl,driveType`.
- **Scopes:** `Sites.Read.All`

### `sharepoint ls SITE [PATH]`

| Option | Default | Meaning |
|---|---|---|
| `--drive NAME\|ID` | the site's default drive | Which document library. |
| `--limit N` | 50 | Maximum items. |
| `--all` | off | Fetch every page, cap 1000. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** as `onedrive ls`, with the base `/sites/{id}/drive` or `/drives/{d}`.
- **Scopes:** `Sites.Read.All`
- **Notes:** item ids are printed in full, so they can be fed straight to `sharepoint download`.

### `sharepoint search Q`

| Option | Default | Meaning |
|---|---|---|
| `--site SITE` | — | Search within one site's drive instead of everywhere. |
| `--limit N` | 25 | Maximum items. |
| `--all` | off | Fetch every page, cap 200. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** with `--site`, `GET /sites/{id}/drive/root/search(q='{q}')`; without it,
  `POST /search/query` with `entityTypes:["driveItem"]` and size 25.
- **Scopes:** `Sites.Read.All`

### `sharepoint download SITE ITEM|PATH`

| Option | Default | Meaning |
|---|---|---|
| `--output FILE` | the item name | Destination file. |
| `--drive NAME\|ID` | the site's default drive | Which document library. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /sites/{id}/drive/items/{item}/content`, or
  `GET /drives/{d}/root:/{path}:/content`.
- **Scopes:** `Sites.Read.All`
- **Notes:** reads the **site** drive, not the signed-in user's OneDrive.

### `sharepoint upload SITE FILE`

| Option | Default | Meaning |
|---|---|---|
| `--dest PATH` | `/<basename>` | Destination path in the library. |
| `--drive NAME\|ID` | the site's default drive | Which document library. |
| `--conflict MODE` | `replace` | `rename`, `replace` or `fail`. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** as `onedrive upload`, with the site drive as the base.
- **Scopes:** `Sites.ReadWrite.All`
- **Notes:** write.

### `sharepoint url URL`

| Option | Default | Meaning |
|---|---|---|
| `--output FILE` | the file's own name | Destination file. |
| `--info` | off | Resolve and print, without downloading. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** first `GET /shares/{share_id(url)}/driveItem`; on a 4xx it parses the URL's host and
  `sites`/`teams`/`personal` segment, resolves the site and its drives, picks the drive whose
  `webUrl` is the deepest prefix of the file path, and reads
  `GET /drives/{d}/root:/{rel}:/content`, with `GET /sites/{id}/drive/root:/{rel}:/content` as a
  last resort.
- **Scopes:** `Sites.Read.All`
- **Notes:** the fastest way to open a link someone pasted into chat or mail. `--info` prints the
  resolution — site id, drive id, path, item — and downloads nothing; JSON includes `resolution`.
  A `/personal/` (OneDrive) URL needs the owner to have shared the file with you.

### `sharepoint lists SITE`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /sites/{id}/lists?$select=id,displayName,webUrl,list`.
- **Scopes:** `Sites.Read.All`
- **Notes:** system lists are hidden.

### `sharepoint items SITE LIST`

| Option | Default | Meaning |
|---|---|---|
| `--fields a,b` | every field | Which columns to fetch. |
| `--filter ODATA` | — | OData filter over `fields/*`. |
| `--limit N` | 50 | Maximum items. |
| `--all` | off | Fetch every page, cap 500. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /sites/{id}/lists/{l}/items?$expand=fields($select=…)&$top=200[&$filter=…]`, with
  `Prefer: HonorNonIndexedQueriesWarningMayFailRandomly` when `--filter` is given.
- **Scopes:** `Sites.Read.All`
- **Notes:** text shows the first eight fields as columns; use `--json` to see them all. A filter on
  an unindexed column may fail intermittently — that is the SharePoint list threshold, not a bug.
