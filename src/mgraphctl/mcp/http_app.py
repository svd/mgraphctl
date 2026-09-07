"""Streamable HTTP, on the 2026-07-28 shape (MCP spec §6.2, §7).

That revision dropped protocol sessions, the standalone GET stream and resumable streams, so none
of them appear here. The deprecated HTTP+SSE transport of 2024-11-05 is not implemented at all.

The three guards below are what stands between a local MCP server and the network. They matter
more here than in most servers because this one has exactly one identity — whoever's token is in
the local MSAL cache — so any reachable listener is that person's mailbox. See spec §7.3 for why
the MCP authorization spec is deliberately not implemented.
"""

from __future__ import annotations

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
        if scheme.lower() != "bearer" or not secrets.compare_digest(value, self.token):
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
            await _reject(send, 403, f"origin {origin!r} is not allowed")
            return
        await self.app(scope, receive, send)


def _header(scope: dict, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


async def _reject(send: Any, status: int, message: str, headers: list | None = None) -> None:
    body = f'{{"error":{message!r}}}'.replace("'", '"').encode()
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
        # `RequireOrigin` is this server's DNS-rebinding defence, and it is the one under test.
        # The SDK's own check also validates Host against a port-bearing allowlist, which rejects
        # legitimate loopback requests; running both would mean two allowlists to keep in step.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return RequireOrigin(RequireBearer(app, token), allow_origin or [])
