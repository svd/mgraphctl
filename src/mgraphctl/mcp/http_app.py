"""Streamable HTTP, on the 2026-07-28 shape (MCP spec §6.2, §7).

That revision dropped protocol sessions, the standalone GET stream and resumable streams, so none
of them appear here. The deprecated HTTP+SSE transport of 2024-11-05 is not implemented at all.

The three guards below are what stands between a local MCP server and the network. They matter
more here than in most servers because this one has exactly one identity — whoever's token is in
the local MSAL cache — so any reachable listener is that person's mailbox. See spec §7.3 for why
the MCP authorization spec is deliberately not implemented.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

from mgraphctl.errors import UsageError

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
MCP_PATH = "/mcp"


def check_host(host: str) -> str:
    """Refuse to start off the loopback interface. The transport spec says SHOULD; this is MUST.

    A non-loopback bind hands every caller on the network the signed-in user's Microsoft 365
    account, with no way for the server to tell callers apart.
    """
    if host not in LOOPBACK:
        raise UsageError(
            "USAGE",
            f"--host {host} is not a loopback address. This server acts as one signed-in user "
            "and cannot authenticate callers; bind 127.0.0.1 and reach it through a tunnel if "
            "you need it from elsewhere",
        )
    return host


def new_token() -> str:
    return secrets.token_urlsafe(32)


class RequireBearer:
    """A static bearer token, checked on every request.

    Not OAuth: the token is a local shared secret, and the server advertises no protected-resource
    metadata because it is not an OAuth resource server (spec §7.3).
    """

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":  # lifespan must pass through, or the server never starts
            await self.app(scope, receive, send)
            return
        header = _header(scope, b"authorization") or ""
        scheme, _, value = header.partition(" ")
        # Compared as bytes: a header carrying any byte above 0x7f makes the str form of
        # compare_digest raise, which would surface as a 500 rather than a clean 401.
        if scheme.lower() != "bearer" or not secrets.compare_digest(
            value.encode("latin-1"), self.token.encode()
        ):
            await _reject(
                send,
                401,
                "unauthorized",
                headers=[(b"www-authenticate", b'Bearer realm="mgraphctl"')],
            )
            return
        await self.app(scope, receive, send)


class RequireOrigin:
    """The DNS-rebinding defence the transport spec mandates for local servers.

    Without it, any page the user visits can drive this server through localhost.

    An allowed origin also needs CORS, or the guard would let the request through only for the
    browser to discard the answer: the preflight is unauthenticated, so it has to be answered
    ahead of the bearer check, and the real response needs `Access-Control-Allow-Origin` back.
    With no `--allow-origin` there is no preflight to answer and every browser is refused.
    """

    def __init__(self, app: Any, allowed: list[str]) -> None:
        self.app = app
        self.allowed = set(allowed)

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        origin = _header(scope, b"origin")
        # A browser always sends Origin; a CLI client never does. An unlisted one is refused.
        if origin is not None and origin not in self.allowed:
            await _reject(send, 403, f"origin {origin} is not allowed")
            return
        if origin is None:
            await self.app(scope, receive, send)
            return
        if scope["method"] == "OPTIONS":
            await self._preflight(scope, send, origin)
            return
        await self.app(scope, receive, _with_cors(send, origin))

    async def _preflight(self, scope: dict, send: Any, origin: str) -> None:
        # The requested headers are echoed rather than listed: a client may mirror tool arguments
        # into `Mcp-Param-*` headers, whose names are not known ahead of the request.
        requested = _header(scope, b"access-control-request-headers") or "authorization"
        await send(
            {
                "type": "http.response.start",
                "status": 204,
                "headers": [
                    (b"access-control-allow-origin", origin.encode("latin-1")),
                    (b"access-control-allow-methods", b"POST, OPTIONS"),
                    (b"access-control-allow-headers", requested.encode("latin-1")),
                    (b"access-control-max-age", b"600"),
                    (b"vary", b"origin"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})


def _with_cors(send: Any, origin: str) -> Any:
    """Add the allow-origin header to whatever the inner app answers."""

    async def wrapped(message: dict) -> None:
        if message["type"] == "http.response.start":
            message = dict(message)
            message["headers"] = [
                *message.get("headers", []),
                (b"access-control-allow-origin", origin.encode("latin-1")),
                (b"vary", b"origin"),
            ]
        await send(message)

    return wrapped


def _header(scope: dict, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


async def _reject(send: Any, status: int, message: str, headers: list | None = None) -> None:
    # json.dumps, not string formatting: `message` can quote a caller-supplied Origin, and a
    # crafted one would otherwise inject structure into the response body.
    body = json.dumps({"error": message}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                *(headers or []),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def build(server: Any, *, token: str, allow_origin: list[str] | None = None) -> Any:
    """The ASGI app: the SDK's Streamable HTTP endpoint behind the origin and bearer guards."""
    from mcp.server.transport_security import TransportSecuritySettings

    app = server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        host="127.0.0.1",
        # A request carrying `MCP-Protocol-Version: 2026-07-28` is routed to the revision's own
        # sessionless path whatever this says; the flag settles the handshake revisions the SDK
        # still negotiates for older clients, and they get the same treatment: a fresh transport
        # per request, no `Mcp-Session-Id`, no session to expire. The server holds nothing between
        # calls that a session could carry — one sign-in, one output directory, a tool set fixed
        # at startup.
        stateless_http=True,
        # `RequireOrigin` is this server's DNS-rebinding defence, and it is the one under test.
        # The SDK's own check also validates Host against a port-bearing allowlist, which rejects
        # legitimate loopback requests; running both would mean two allowlists to keep in step.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return RequireOrigin(RequireBearer(app, token), allow_origin or [])
