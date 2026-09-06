# `people`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

### `people search Q`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 20 | Maximum items. |
| `--all` | off | Fetch every page, cap 250. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/people?$search="Q"&$top=50&$select=id,displayName,scoredEmailAddresses,jobTitle,department,companyName,personType,userPrincipalName`.
- **Scopes:** `People.Read`
- **Notes:** `/me/people` ranks by relevance to the signed-in user and is in maintenance mode; for a
  wider sweep use `search Q --type person` or `people users Q`.

### `people contacts`

| Option | Default | Meaning |
|---|---|---|
| `--search Q` | — | Filter by name or email. |
| `--limit N` | 20 | Maximum items. |
| `--all` | off | Fetch every page, cap 250. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/contacts?$top=50&$select=id,displayName,emailAddresses,mobilePhone,businessPhones,jobTitle,companyName[&$search="Q"]`.
- **Scopes:** `Contacts.Read`
- **Notes:** when Graph rejects `$search` with a 400, up to 250 contacts are fetched and matched
  client-side instead.

### `people contact ID`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/contacts/{id}`.
- **Scopes:** `Contacts.Read`

### `people users Q`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 20 | Maximum items. |
| `--all` | off | Fetch every page, cap 999. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /users?$search="displayName:Q" OR "mail:Q"&$count=true&$top=100&$select=id,displayName,userPrincipalName,mail,jobTitle,department,officeLocation`
  with `ConsistencyLevel: eventual`.
- **Scopes:** `User.ReadBasic.All`
- **Beyond `default`:** always.
- **Notes:** a directory search. `$search` matches whole tokens, not substrings — "ann" will not
  find "Anna".

### `people user UPN|ID`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /users/{x}?$select=id,displayName,userPrincipalName,mail,jobTitle,department,officeLocation,businessPhones,mobilePhone`
  (or `GET /me` for `me`).
- **Scopes:** `User.Read`; resolving a bare display name additionally checks `User.ReadBasic.All`.
- **Notes:** accepts a UPN, an object id, `me`, or a display name.

### `people photo [UPN]`

| Option | Default | Meaning |
|---|---|---|
| `--output FILE` | `<upn>.jpg` | Destination file. |
| `--size WxH` | `96x96` | Photo size. Applies to other users only. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/photo/$value`, or `GET /users/{upn}/photos/{size}/$value` (streamed).
- **Scopes:** `User.Read` for yourself; `User.ReadBasic.All` is checked before reading anyone else.
- **Beyond `default`:** only for another user.
- **Notes:** a mailbox with no photo returns 404 → exit 4.
