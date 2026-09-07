# mgraphctl MCP server — design specification

Status: approved 2026-09-07. Implemented on `feat/mcp-server`.

This document specifies `mgraphctl mcp serve`: a Model Context Protocol server that exposes the
mgraphctl CLI verbs as MCP tools. It extends the base design
(`docs/specs/2026-09-02-mgraphctl-design.md`), whose section numbers are cited as "base §N".

## 1. Goals and non-goals

Goals:

- Every CLI verb reachable as an MCP tool, generated from the command tree rather than restated,
  so a new verb becomes a new tool with no second surface to maintain.
- The MCP revision in force is **2026-07-28**. No deprecated feature is implemented.
- Bounded context cost: the operator chooses which command groups are exposed, and no single tool
  result can flood the client.
- Bounded blast radius: read-only by default, one identity, loopback only.

Non-goals:

- OAuth 2.1 authorization (§7.3 says why it cannot be done honestly here).
- The deprecated HTTP+SSE transport (2024-11-05), protocol sessions, resumable streams, or
  Dynamic Client Registration.
- Interactive sign-in as a tool. `login` opens a browser; it stays a CLI verb.

## 2. Protocol revision

The server targets MCP **2026-07-28** and speaks the earlier revisions the SDK negotiates, so
hosts that have not moved yet still work. Consequences of that revision, all of which the
implementation follows rather than works around:

- No `initialize` handshake; per-request metadata in `_meta.io.modelcontextprotocol/*`.
- No protocol-level session, so no `Mcp-Session-Id` is minted or echoed.
- No standalone GET stream and no `Last-Event-ID` resumption. GET and DELETE on the MCP endpoint
  answer `405 Method Not Allowed`.
- Server-to-client interaction, if it is ever needed, is `InputRequiredResult` under MRTR, never a
  server-initiated JSON-RPC request. The current tool set needs none.

## 3. Packaging

`mcp>=2.1,<3` is an **optional extra**, `mgraphctl[mcp]`, never a base dependency: the SDK pulls in
pydantic, starlette, uvicorn, jsonschema, pyjwt, opentelemetry and `httpx2`, none of which the CLI
itself should carry. `mgraphctl mcp serve` without the extra installed fails with a usage error
naming the install command.

New modules under `src/mgraphctl/mcp/`:

| Module | Holds |
|---|---|
| `discover.py` | Walks the Click tree; yields one `ToolSpec` per verb, with its capability and mutation class. |
| `schema.py` | Click params → JSON Schema; argument-name normalisation. |
| `output.py` | `Result` → MCP content: text, structured, spill-to-file, resource links. |
| `server.py` | Builds the `MCPServer`, registers tools and resources, dispatches calls. |
| `http_app.py` | Streamable HTTP: loopback guard, bearer check, Origin validation. |

`commands/mcp_cmd.py` registers the `mcp` noun (`serve`, `tools`). It is attached in `build_app`
alongside `config_cmd`, not through the `NOUNS` table, because it makes no Graph call.

## 4. Tool generation

### 4.1 Discovery

`discover.py` walks the Click group tree exactly as `tests/test_surface.py` does — that walk moves
into `discover.py` and the test imports it, so the two cannot drift. Each leaf command yields a
`ToolSpec`:

| Field | From |
|---|---|
| `name` | Path joined with `_`: `mail list` → `mail_list`, `mail drafts create` → `mail_drafts_create`. |
| `title` | The path as typed: `mail drafts create`. |
| `description` | The command's help text (its docstring). |
| `capability` | The first path segment, or `core` for a top-level verb. |
| `input_schema` | `schema.py`, from the Click params. |
| `annotations` | §4.4. |
| `scopes` | `__graph_scopes__`, already stashed by `graph_command`. |
| `fn` | `__graph_fn__`, added to `graph_command` by this change. |

Tool names satisfy the spec's character rules and are unique by construction (the CLI path is).

### 4.2 Input schema

Every Click param becomes one property. `--body-file` → `body_file`; `--all` → `all`; a positional
`ID` argument → a required property named after the parameter. Types map `STRING`→`string`,
`INT`→`integer`, `BOOL` flag→`boolean`, `Path`→`string`, `multiple=True`→`array` of the item type.
`description` is the Click help; `default` is carried when it is not `None`. Required properties are
the Click arguments plus any option with `required=True`. The schema is closed
(`additionalProperties: false`) so a client cannot smuggle unknown kwargs into the callback.

Two params are **not** derived from Click, because the CLI's `--json` does not translate directly
(§5): `output_format` and `output_file` are added to every tool. `--json` itself is excluded from
the generated schema.

### 4.3 Capabilities

A capability is a command group: `mail`, `calendar`, `teams`, … plus two synthetic ones — `core`
(`me`, `status`, `claims`, `version`) and `api` (the raw Graph escape hatch of base §8.1).

`--capabilities mail,calendar,teams` selects them. Omitted, the default is
`core,mail,calendar,people,chats` — a working assistant without loading all 123 verbs. `--capabilities all`
is accepted and means every capability except `api`; `api` is only ever exposed by naming it.
An unknown name is a usage error listing the valid ones.

`mgraphctl mcp tools [--capabilities ...] [--json]` prints the resolved tool list without starting a
server, so the context cost is inspectable before wiring the server into a host.

### 4.4 Read-only default and annotations

A verb is **mutating** if it issues any request whose method is not GET. That classification is
derived once and asserted by a test, so a new mutating verb cannot silently become an exposed
read tool.

Only non-mutating tools are exposed unless `--allow-write` is passed. Annotations follow:
`readOnlyHint` true for non-mutating verbs; `destructiveHint` true for verbs whose path ends in
`delete`; `idempotentHint` true for `update`/`set`-shaped verbs. Annotations are hints for the
host's confirmation UI — the server's own gate is `--allow-write`, since the spec tells clients to
treat annotations as untrusted.

Mutating tools additionally expose `dry_run`, mapping to the CLI's `--dry-run` (base §6.4).

## 5. Results: what happens to `--json`

`--json` is a rendering switch on a stream the CLI owns. MCP has three distinct channels for the
same information, so the flag becomes a choice among them rather than a boolean.

Dispatch is **in-process**. `graph_command` gains `__graph_fn__`, so the server opens a client with
the verb's declared scopes and calls the undecorated function, receiving the same `Result` dataclass
the CLI renders (base §7.3). Nothing touches stdout — which is load-bearing, because on stdio
transport stdout *is* the JSON-RPC channel. To make that possible `render.emit` splits into pure
functions:

```python
def to_text(result: Result) -> str          # the body the CLI prints to stdout
def notes(result: Result) -> list[str]      # the truncation lines the CLI prints to stderr
def to_json(result: Result) -> Any          # today's private _to_json, made public
```

`emit` keeps its exact current behaviour by composing them; the CLI is unchanged.

Every tool takes `output_format`:

- `text` (default) — one `TextContent` block: `to_text` plus any `notes`. This is the compact table
  a human sees, and it is far cheaper in context than the JSON.
- `json` — `structuredContent` set to `to_json(result)`, plus the serialized JSON as a
  `TextContent` block, as the spec asks for backwards compatibility.

and `output_file`: an optional **relative** name. Given one, the full result is written under the
server's output directory and the tool returns a `resource_link` plus a one-line summary (item
count, whether the fetch was truncated) instead of the payload. The path is relative and resolved
inside the output directory; an absolute path or one escaping the directory is a tool error. The
server never writes where the caller asks it to — only where the operator configured.

`--output-dir` defaults to `~/.cache/mgraphctl/mcp/` (`$XDG_CACHE_HOME` honoured), created
`0o700` on first use.

**Auto-spill.** Any result whose rendering exceeds `--max-inline-bytes` (default 25000) is written
to the output directory and returned as a `resource_link` with a head excerpt, whatever the
caller asked for. A runaway `mail list --all` therefore cannot flood the client.

**Files the verbs already produce.** `FileResult` verbs (`onedrive download`, `me --photo`, …) have
their destination forced inside the output directory and return the same `resource_link` shape.

**Resources.** Everything the server writes is registered as an MCP resource under a `file://` URI
and served by `resources/read`, so a host with no filesystem access can still fetch what a
`resource_link` points at. The resource list is exactly the files this server produced; it does not
expose the rest of the filesystem.

**Errors.** A `MsgraphError` becomes a tool result with `isError: true` carrying `format_error`'s
block (base §6.5) — it already states the code, the message and an actionable hint, which is what
the spec wants a model to be able to self-correct from. An unknown tool name is a JSON-RPC
protocol error, not a tool result.

## 6. Transports

### 6.1 stdio

The primary path, and the one the README documents first. Credentials come from the environment
(the MSAL cache, base §4.3), which is what the authorization spec prescribes for stdio: it says
implementations on stdio **SHOULD NOT** follow the OAuth flow and should take credentials from the
environment.

### 6.2 Streamable HTTP

`--transport http [--host 127.0.0.1] [--port N]`. One POST endpoint at `/mcp`. GET and DELETE
answer `405`. No session id is minted, no `Last-Event-ID` honoured. The SDK routes a request
carrying `MCP-Protocol-Version: 2026-07-28` to the revision's own sessionless path, and
`stateless_http=True` puts the handshake revisions it still negotiates on the same footing.

Three guards, in this order:

1. **Loopback.** A `--host` that is not a loopback literal is a usage error, not a warning. The
   server refuses to start.
2. **Bearer token.** Required. Taken from `MGRAPHCTL_MCP_TOKEN`, else generated with
   `secrets.token_urlsafe(32)` and printed to stderr at startup with the URL to paste into the host
   config. Compared with `secrets.compare_digest`. A missing or wrong token gets `401` with
   `WWW-Authenticate: Bearer`.
3. **Origin.** A request carrying an `Origin` header not in `--allow-origin` (empty by default) gets
   `403`. This is the DNS-rebinding defence the transport spec mandates for local servers: without
   it, any web page the user visits can drive their mailbox through localhost.

## 7. Authentication, and its limits over HTTP

### 7.1 One identity

The server acts as exactly one user: whoever's MSAL refresh token is in the local cache. It has no
way to tell callers apart. An HTTP listener therefore converts that cache into an ambient
credential for anything that can reach the port — which is the whole reason for the loopback and
bearer guards in §6.2, and the reason stdio is the recommended transport.

### 7.2 No cached sign-in

The server starts, warns on stderr, and every tool call returns an actionable error telling the
operator to run `mgraphctl login`. It is not a startup failure: a token may appear later, and a
host that supervises the process should not crash-loop.

### 7.3 Why the MCP authorization spec is not implemented

Conforming would mean acting as an OAuth 2.1 resource server: RFC 9728 protected resource metadata,
authorization-server discovery, and access tokens **validated for this server as their audience**.

The obvious shortcut — accepting the caller's Entra token and forwarding it to Graph — is precisely
the token passthrough the spec prohibits, and it fails audience validation by construction: a Graph
token's audience is Graph, not this server.

Doing it properly needs a *second* Entra app registered as an API with its own scope, plus an
on-behalf-of exchange to trade that token for a Graph token. On-behalf-of requires a **confidential**
client, i.e. a client secret. A locally installed CLI cannot hold a secret (base §4.2 is a public
client for exactly this reason), and the registration needs tenant admin work that the tool cannot
assume.

So the HTTP transport ships with a local shared secret and a loopback bind, and this is stated
plainly in the README rather than dressed up as OAuth. The server advertises no
`/.well-known/oauth-protected-resource` document, because it is not an OAuth resource server and
claiming otherwise would send clients into a flow that cannot complete.

## 8. Surface

```
mgraphctl mcp serve [--capabilities NAMES] [--allow-write] [--transport stdio|http]
                    [--host HOST] [--port PORT] [--allow-origin ORIGIN]...
                    [--output-dir DIR] [--max-inline-bytes N]
mgraphctl mcp tools [--capabilities NAMES] [--allow-write] [--json]
```

`mcp serve` is the one verb in the CLI that cannot satisfy the `--json` invariant of base §11: it
starts a server and prints nothing. `tests/test_surface.py` carries a single documented exemption
for it. `mcp tools` satisfies the invariant normally.

## 9. Tests

| Area | Assertion |
|---|---|
| `discover` | Every verb in the Click walk produces exactly one `ToolSpec`; names are unique and character-legal. |
| `schema` | Click params map to the documented JSON Schema; `--json` is absent; `output_format`/`output_file` present. |
| Capabilities | Filtering by name; `all`; `api` excluded from `all`; unknown name is a usage error. |
| Read-only | No mutating tool is exposed without `--allow-write`; the mutation classification matches the verbs' HTTP methods. |
| Output | `text` vs `json`; `output_file` writes inside the output dir and returns a `resource_link`; a path escaping the dir is refused; auto-spill fires past the threshold; the spilled file is readable through `resources/read`. |
| Errors | `MsgraphError` becomes `isError` with the `format_error` block; unknown tool is a protocol error. |
| HTTP | Non-loopback host refused; missing/wrong bearer is `401`; a foreign `Origin` is `403`; GET and DELETE are `405`. |
| Dispatch | A tool call reaches the verb's function with the right kwargs, against the recorded fixtures — no network. |

Tests use the SDK's in-memory client/server pair, so no socket is opened except in the HTTP guard
tests.
