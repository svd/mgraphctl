"""`mgraphctl mcp`: run the MCP server, or list what it would expose.

The design is `docs/specs/2026-09-07-mcp-server-design.md`. `tools` needs nothing beyond the CLI
itself; `serve` needs the `mgraphctl[mcp]` extra, and says so when it is missing.
"""

import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from mgraphctl.cli import JsonFlag, make_noun_app
from mgraphctl.errors import MsgraphError, UsageError
from mgraphctl.mcp import discover, output
from mgraphctl.render import Column, ListResult, emit

app = make_noun_app("Serve these verbs to an MCP client, or list what would be served.")

INSTALL_HINT = (
    "the MCP server needs the optional dependency: install `mgraphctl[mcp]` "
    "(uv add 'mgraphctl[mcp]', or pip install 'mgraphctl[mcp]')"
)

TOKEN_ENV = "MGRAPHCTL_MCP_TOKEN"

CapabilitiesOpt = Annotated[
    str | None,
    typer.Option(
        "--capabilities",
        help="Comma-separated command groups to expose, or 'all'. Default: "
        + ",".join(discover.DEFAULT)
        + ". Each one costs the client context, so name only what is needed.",
    ),
]
AllowWriteFlag = Annotated[
    bool,
    typer.Option("--allow-write", help="Also expose the verbs that change something."),
]
OutputDirOpt = Annotated[
    Path | None,
    typer.Option(
        "--output-dir",
        help="Where results are written and the only place tool paths may point "
        "(default: ~/.cache/mgraphctl/mcp).",
    ),
]
MaxInlineOpt = Annotated[
    int,
    typer.Option(
        "--max-inline-bytes",
        min=1024,
        help="Results larger than this are written to a file and linked instead of inlined.",
    ),
]


def _settings(
    capabilities: str | None,
    allow_write: bool,
    output_dir: Path | None,
    max_inline_bytes: int,
):
    from mgraphctl.mcp.server import Settings

    return Settings(
        capabilities=discover.resolve(capabilities),
        allow_write=allow_write,
        output_dir=output_dir,
        max_inline_bytes=max_inline_bytes,
    )


def _require_sdk():
    try:
        from mgraphctl.mcp import server
    except ImportError as exc:  # pragma: no cover - exercised by test_cli_mcp with a hidden module
        raise UsageError("USAGE", INSTALL_HINT) from exc
    return server


@app.command("tools")
def tools(
    capabilities: CapabilitiesOpt = None,
    allow_write: AllowWriteFlag = False,
    json_: JsonFlag = False,
) -> None:
    """List the tools the server would expose, without starting it."""
    from mgraphctl.cli import build_app

    specs = discover.discover(
        build_app(), capabilities=discover.resolve(capabilities), allow_write=allow_write
    )
    emit(
        ListResult(
            items=[
                {
                    "name": spec.name,
                    "verb": spec.path,
                    "capability": spec.capability,
                    "write": "yes" if spec.mutating else "",
                    "description": spec.description.splitlines()[0],
                }
                for spec in specs
            ],
            columns=[
                Column("Tool", "name"),
                Column("Verb", "verb"),
                Column("Capability", "capability"),
                Column("Write", "write"),
            ],
            empty_text="No tools; check --capabilities.",
        ),
        json_mode=json_,
    )


@app.command("serve")
def serve(
    capabilities: CapabilitiesOpt = None,
    allow_write: AllowWriteFlag = False,
    transport: Annotated[
        str, typer.Option("--transport", help="stdio (default) or http.")
    ] = "stdio",
    host: Annotated[
        str, typer.Option("--host", help="Loopback address for --transport http.")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Port for --transport http.")] = 8765,
    allow_origin: Annotated[
        list[str] | None,
        typer.Option(
            "--allow-origin",
            help="Browser origin allowed to call the HTTP endpoint (repeatable). "
            "None by default: any request carrying an Origin header is refused.",
        ),
    ] = None,
    output_dir: OutputDirOpt = None,
    max_inline_bytes: MaxInlineOpt = output.DEFAULT_MAX_INLINE_BYTES,
) -> None:
    """Run the MCP server over stdio, or over Streamable HTTP on the loopback interface."""
    import anyio

    server = _require_sdk()
    if transport not in ("stdio", "http"):
        raise UsageError("USAGE", f"--transport must be stdio or http (got {transport!r})")
    settings = _settings(capabilities, allow_write, output_dir, max_inline_bytes)
    built = server.build(settings)
    _warn_if_signed_out()

    if transport == "stdio":
        # stdout carries JSON-RPC from here on; everything else the server says goes to stderr.
        anyio.run(_serve_stdio, built)
        return
    _serve_http(built, host=host, port=port, allow_origin=list(allow_origin or []))


async def _serve_stdio(built) -> None:
    import mcp.server.stdio

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await built.run(read_stream, write_stream, built.create_initialization_options())


def _serve_http(built, *, host: str, port: int, allow_origin: list[str]) -> None:
    import uvicorn

    from mgraphctl.mcp import http_app

    http_app.check_host(host)
    token = os.environ.get(TOKEN_ENV) or http_app.new_token()
    if not os.environ.get(TOKEN_ENV):
        sys.stderr.write(
            f"mgraphctl mcp: generated a bearer token for this run.\n"
            f"  url:   http://{host}:{port}{http_app.MCP_PATH}\n"
            f"  token: {token}\n"
            f"Set {TOKEN_ENV} to keep one across restarts. This is a local shared secret, "
            f"not OAuth: anyone holding it acts as the signed-in user.\n"
        )
    uvicorn.run(
        http_app.build(built, token=token, allow_origin=allow_origin),
        host=host,
        port=port,
        log_level="warning",
    )


def _warn_if_signed_out() -> None:
    """Not fatal: a token may appear later, and a supervised server should not crash-loop."""
    from mgraphctl import auth

    try:
        signed_in = auth.cached_access_token() is not None
    except MsgraphError:
        signed_in = False
    if not signed_in:
        sys.stderr.write(
            "mgraphctl mcp: no cached sign-in; every tool call will fail until "
            "`mgraphctl login` has been run.\n"
        )


def register(root: typer.Typer) -> None:
    root.add_typer(app, name="mcp", help="The MCP server.")
