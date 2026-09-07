"""The HTTP transport's guards (MCP spec §6.2, §7)."""

import httpx
import pytest

from mgraphctl.errors import UsageError
from mgraphctl.mcp import http_app, server

pytestmark = pytest.mark.anyio

TOKEN = "test-token"
POST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    },
}
HEADERS = {
    "content-type": "application/json",
    "accept": "application/json, text/event-stream",
    "mcp-protocol-version": "2026-07-28",
    "mcp-method": "tools/list",
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def asgi(app, tmp_path):
    settings = server.Settings(capabilities=["core"], output_dir=tmp_path / "out")
    return http_app.build(server.build(settings, app), token=TOKEN, allow_origin=["http://ok"])


@pytest.fixture
async def http(asgi):
    """The app with its lifespan run, so the SDK's session manager is started."""
    inner = asgi.app.app  # RequireOrigin -> RequireBearer -> Starlette
    async with inner.router.lifespan_context(inner):
        transport = httpx.ASGITransport(app=asgi)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            yield client


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com"])
def test_a_non_loopback_bind_is_refused(host):
    """One identity, no way to tell callers apart: a reachable port is the user's mailbox."""
    with pytest.raises(UsageError) as excinfo:
        http_app.check_host(host)
    assert "loopback" in str(excinfo.value)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_is_allowed(host):
    assert http_app.check_host(host) == host


def test_a_generated_token_is_long_enough_to_be_a_secret():
    assert len(http_app.new_token()) >= 32
    assert http_app.new_token() != http_app.new_token()


async def test_a_request_without_a_token_is_401(http):
    response = await http.post(http_app.MCP_PATH, json=POST, headers=HEADERS)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


async def test_a_request_with_the_wrong_token_is_401(http):
    response = await http.post(
        http_app.MCP_PATH, json=POST, headers={**HEADERS, "authorization": "Bearer nope"}
    )
    assert response.status_code == 401


async def test_a_request_with_the_token_gets_through(http):
    response = await http.post(
        http_app.MCP_PATH, json=POST, headers={**HEADERS, "authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 200
    assert "me" in response.text


async def test_an_unlisted_origin_is_403_before_the_token_is_even_checked(http):
    """The DNS-rebinding defence: a page the user visits must not reach this server."""
    response = await http.post(
        http_app.MCP_PATH,
        json=POST,
        headers={**HEADERS, "origin": "http://evil.example", "authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 403


async def test_an_allowed_origin_passes(http):
    response = await http.post(
        http_app.MCP_PATH,
        json=POST,
        headers={**HEADERS, "origin": "http://ok", "authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200


@pytest.mark.parametrize("method", ["get", "delete"])
async def test_the_removed_session_endpoints_are_405(http, method):
    """2026-07-28 dropped the GET stream and the DELETE session teardown."""
    response = await getattr(http, method)(
        http_app.MCP_PATH, headers={**HEADERS, "authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 405


async def test_a_malformed_authorization_header_is_401_not_a_crash(http):
    """A byte above 0x7f makes the str form of compare_digest raise."""
    response = await http.post(
        http_app.MCP_PATH,
        json=POST,
        headers={**HEADERS, "authorization": "Bearer tok\xe9n".encode("latin-1")},
    )
    assert response.status_code == 401


async def test_a_crafted_origin_cannot_inject_into_the_error_body(http):
    response = await http.post(
        http_app.MCP_PATH,
        json=POST,
        headers={**HEADERS, "origin": '"},"injected":"'},
    )
    assert response.status_code == 403
    assert set(response.json()) == {"error"}


async def test_an_allowed_origin_can_preflight_without_a_token(http):
    """The browser sends OPTIONS with no Authorization; refusing it kills the real request."""
    response = await http.request(
        "OPTIONS",
        http_app.MCP_PATH,
        headers={
            "origin": "http://ok",
            "access-control-request-method": "POST",
            "access-control-request-headers": "authorization, content-type, mcp-method",
        },
    )
    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "http://ok"
    assert "authorization" in response.headers["access-control-allow-headers"]
    assert "mcp-method" in response.headers["access-control-allow-headers"]


async def test_an_unlisted_origin_cannot_preflight(http):
    response = await http.request(
        "OPTIONS",
        http_app.MCP_PATH,
        headers={"origin": "http://evil.example", "access-control-request-method": "POST"},
    )
    assert response.status_code == 403


async def test_the_real_response_carries_the_allow_origin_header(http):
    """Without it the browser discards an answer the guard already allowed."""
    response = await http.post(
        http_app.MCP_PATH,
        json=POST,
        headers={**HEADERS, "origin": "http://ok", "authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://ok"


async def test_a_client_without_an_origin_gets_no_cors_headers(http):
    response = await http.post(
        http_app.MCP_PATH, json=POST, headers={**HEADERS, "authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
