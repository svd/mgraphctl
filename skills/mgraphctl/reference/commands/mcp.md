# `mcp`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

These two verbs are for the person configuring an MCP host, not for a task. They serve the other
verbs in this reference to an MCP client; they read no Microsoft 365 data themselves. The server
needs the optional dependency: install `mgraphctl[mcp]`.

### `mcp tools`

| Option | Default | Meaning |
|---|---|---|
| `--capabilities NAMES` | `core,mail,calendar,people,chats` | Comma-separated command groups to expose, or `all`. |
| `--allow-write` | off | Also count the verbs that change something. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** none; it reads the command tree.
- **Scopes:** none.
- **Notes:** prints the tools `mcp serve` would expose, so the client's context cost can be seen
  before the server is wired into a host.

### `mcp serve`

| Option | Default | Meaning |
|---|---|---|
| `--capabilities NAMES` | `core,mail,calendar,people,chats` | Command groups to expose, or `all`. Each costs the client context. |
| `--allow-write` | off | Also expose the verbs that change something. |
| `--transport stdio\|http` | `stdio` | `stdio` is the recommended transport. |
| `--host HOST` | `127.0.0.1` | Loopback only; anything else is a usage error. |
| `--port PORT` | `8765` | Port for `--transport http`. |
| `--allow-origin ORIGIN` | none | Browser origin allowed to call the HTTP endpoint (repeatable); it also gets the CORS headers a browser needs. |
| `--output-dir DIR` | `~/.cache/mgraphctl/mcp` | Where results are written, and the only place tool paths may point. |
| `--max-inline-bytes N` | `25000` | Larger results are written to a file and linked instead of inlined. |

- **Graph:** none directly; each tool call runs the verb it names.
- **Scopes:** whatever the called verb declares, checked per call as on the command line.
- **Notes:** the only verb with no `--json` — it hands stdout to the MCP protocol and blocks.
  Capabilities are command groups plus `core` (`me`, `status`, `claims`, `version`) and `api`, the
  raw Graph escape hatch, which `all` deliberately omits. `login` and this noun are never exposed
  as tools.

**Tool arguments.** Every tool takes the verb's own options plus `output_format`
(`text`, the default, or `json`) and `output_file`. `--json` is not a tool argument: `text`
returns the compact table, `json` returns the full payload as structured content, and
`output_file` writes the result under `--output-dir` and returns a link to it instead of the
payload. A result past `--max-inline-bytes` is written and linked whatever the caller asked, so a
single wide fetch cannot flood the client.

Every path a tool argument names — a destination like `--output`, and equally a file the verb
*reads*, such as `--attach` or `--body-file` — resolves inside `--output-dir`; one that escapes it
is a tool error - including `api --body @FILE`, whose leading `@` is what makes the rest of the
value a path. The server also runs from inside that directory, so a verb whose destination is
optional (`onedrive download`, `mail attachments`) writes its default there rather than wherever
the server was launched.

**Protocol.** MCP revision `2026-07-28`, plus the earlier revisions the SDK negotiates. The
deprecated HTTP+SSE transport, protocol sessions, the standalone GET stream and resumable streams
are not implemented; `GET` and `DELETE` on the endpoint answer `405`.

**HTTP and its limits.** The server acts as exactly one user — whoever's sign-in is cached — and
cannot tell callers apart, so any reachable port is that person's mailbox. Hence: loopback only; a
bearer token is required (`MGRAPHCTL_MCP_TOKEN`, else one is generated and printed to stderr at
startup); a request carrying an unlisted `Origin` gets `403`, which is the DNS-rebinding defence
the transport spec requires of local servers.

That token is a local shared secret, **not** OAuth. Conforming to the MCP authorization spec would
mean validating tokens issued for this server as their audience; forwarding the caller's Entra
token instead is the token passthrough the spec prohibits, and doing it properly needs a second
Entra app registered as an API plus an on-behalf-of exchange, which requires a client secret a
locally installed CLI cannot hold. So no protected-resource metadata is advertised, and `stdio`
remains the recommended transport — where, as the spec prescribes, credentials come from the
environment.
