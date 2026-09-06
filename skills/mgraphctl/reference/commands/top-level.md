# Top-level

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

### `login`

The only command that may open a browser. Run it yourself in your own terminal.

| Option | Default | Meaning |
|---|---|---|
| `--scopes SET` | `MGRAPHCTL_SCOPES`, else `default` | `default`, `extended`, or a space/comma-separated scope list. |
| `--scope X` | — | One extra on-demand scope. Repeatable. |
| `--force` | off | Sign in again even when a token is cached. |
| `--device-code` | off | Device-code flow, for a host with no browser. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** the msal token endpoint, then `GET /me?$select=id,displayName,userPrincipalName`.
- **Scopes:** none checked (this is what obtains them).
- **Notes:** already signed in and no new scopes asked for → prints `Already logged in as: <upn>`,
  exit 0. Interactive login times out after 300 s (`error[LOGIN_TIMEOUT]`, exit 3). Re-running with
  `--scopes extended` on a consented account adds scopes with one consent prompt, no re-login.
  The `Cache:` line (JSON `cache`, with `store` = `keyring` or `file`) names the OS keychain or
  the cache file, whichever `token_store` resolved to.

### `logout`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** none.
- **Scopes:** none.
- **Notes:** removes the keychain item and `~/.mgraphctl/token_cache.json`, whichever exist.
  Exit 0 whether or not a cache existed; JSON `{"loggedOut", "cache", "store"}`.

### `status`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** none — a silent token acquisition, which may refresh.
- **Scopes:** none.
- **Notes:** run this first. Logged in → `Logged in as`, `Token expires`, `Scopes`, `Cache`, exit 0.
  Not logged in → `error[NOT_LOGGED_IN]` on stderr, exit 3. With `--json` stdout carries
  `{"loggedIn": …}` in both states, so it can be parsed without checking the exit code first.
  `cache` and `store` say where the sign-in lives: the OS keychain or the file.

### `claims`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print the raw token payload. |

- **Graph:** none — a local JWT decode, no network call.
- **Scopes:** none.
- **Notes:** sections IDENTITY, DEVICE, AUTH METHODS, SCOPES. It cannot refresh an expired token;
  no cached token → exit 3.

### `me`

| Option | Default | Meaning |
|---|---|---|
| `--photo PATH` | — | Save the profile photo to this file instead of printing the profile. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me?$select=id,displayName,userPrincipalName,mail,jobTitle,department,officeLocation,businessPhones,mobilePhone,preferredLanguage`;
  `--photo`: `GET /me/photo/$value` (streamed).
- **Scopes:** `User.Read`
- **Notes:** a mailbox with no photo returns 404 → exit 4.

### `version`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** none.
- **Scopes:** none.
- **Notes:** prints `mgraphctl <version>` with the Python, msal and httpx versions it runs on.

### `api METHOD PATH`

The escape hatch: one raw Graph request. `PATH` may be relative (`/me/messages`) or absolute.

| Option | Default | Meaning |
|---|---|---|
| `--query k=v` | — | Query parameter. Repeatable. |
| `--body JSON\|@FILE` | — | JSON request body, or `@FILE` holding it. |
| `--header k:v` | — | Extra request header. Repeatable. |
| `--beta` | off | Send this call to `/beta`. |
| `--all` | off | Follow `@odata.nextLink` and merge every page's `value`. |
| `--raw` | off | Treat the response as bytes, not JSON. |
| `--output FILE` | — | Write the `--raw` bytes to this file. |
| `--outlook-tz` | off | Send `Prefer: outlook.timezone` for mail/calendar paths. Hidden from `--help`. |
| `--dry-run` | off | Show the request; send nothing. |
| `--json` | off | Accepted, no-op — the body is printed as returned. |

- **Graph:** exactly the request given.
- **Scopes:** none declared; the local gate is skipped and Graph decides.
- **Notes:** the response body is printed as-is; a non-JSON body prints as text unless `--raw`.
  Any non-GET `api` call is a write — dry-run it and confirm first.

### `search Q`

| Option | Default | Meaning |
|---|---|---|
| `--type TYPE` | `message` | `message`, `event`, `driveItem`, `site`, `list`, `chatMessage`, or `person`. |
| `--after DT` | — | Only hits after this time. |
| `--before DT` | — | Only hits before this time. |
| `--limit N` | 25 | Maximum items. |
| `--all` | off | Fetch every page, cap 200. |
| `--fields a,b` | — | Comma-separated Graph fields to fetch. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /search/query {requests:[{entityTypes:[type], query:{queryString}, from, size:25, fields?}]}`,
  paging on `moreResultsAvailable`.
- **Scopes:** checked per `--type` after parsing: `message` → `Mail.Read`; `event` → `Calendars.Read`;
  `driveItem`/`site`/`list` → `Sites.Read.All`; `chatMessage` → `Chat.Read`; `person` → `People.Read`.
- **Notes:** for `message` the date window is appended to the KQL as `received>=`/`received<=`; for
  every other type it is applied client-side. Hits carry a `summary` snippet, not the whole item.
  `chatMessage` hits are labelled `chat:<id>` or `channel:<teamId>/<channelId>`, exactly as
  `chats search` labels them.
