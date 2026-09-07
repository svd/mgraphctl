"""The MCP server itself: tool listing, dispatch, and the files it hands back (MCP spec §4, §5).

Dispatch is in-process. `@graph_command` wraps the verb's real function with `functools.wraps`, so
`__wrapped__` is `fn(client, **kwargs)` returning a `render.Result` — the same object the CLI
renders. Nothing here writes to stdout, which is load-bearing: on stdio transport stdout carries
JSON-RPC.

The tool list is built from an explicit JSON Schema per verb, so this uses the low-level `Server`
rather than `MCPServer`, whose only registration path infers a schema from a Python signature.
Two consequences of that, both handled below: the SDK does not validate arguments against the
advertised schema, and an exception raised out of a handler becomes an opaque protocol error
instead of the `isError` result a model can recover from.
"""

from __future__ import annotations

import contextlib
import functools
import inspect
import io
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
import jsonschema
import mcp.types as types
import typer
import typer.main
from mcp.server.lowlevel import Server

from mgraphctl import __version__, auth, config, render
from mgraphctl.cli import Globals, open_client
from mgraphctl.errors import MsgraphError, UsageError, format_error
from mgraphctl.mcp import discover, output

log = logging.getLogger("mgraphctl.mcp")

# `status` and `claims` read `ctx.find_root().obj`; they are invoked through a Click context
# holding the same `Globals` the CLI would have built.
LOCAL_VERBS = ("status", "claims", "version")


@dataclass
class Settings:
    """Everything `mcp serve` decided, as the server needs it."""

    capabilities: list[str] = field(default_factory=lambda: list(discover.DEFAULT))
    allow_write: bool = False
    output_dir: Path | None = None
    max_inline_bytes: int = output.DEFAULT_MAX_INLINE_BYTES

    def store(self) -> output.OutputStore:
        root = self.output_dir if self.output_dir is not None else output.default_root()
        return output.OutputStore(root, max_inline_bytes=self.max_inline_bytes)


def _tool(spec: discover.ToolSpec) -> types.Tool:
    return types.Tool(
        name=spec.name,
        title=spec.title,
        description=spec.description,
        input_schema=spec.input_schema,
        annotations=types.ToolAnnotations(
            read_only_hint=spec.annotations.get("readOnlyHint"),
            destructive_hint=spec.annotations.get("destructiveHint"),
            idempotent_hint=spec.annotations.get("idempotentHint"),
            open_world_hint=spec.annotations.get("openWorldHint"),
        ),
    )


def _globals() -> Globals:
    settings = config.settings()
    zone = settings.tz or render.local_tz()
    return Globals(debug=settings.debug, tz=zone, beta=False)


def _kwargs(spec: discover.ToolSpec, arguments: dict[str, Any], store: output.OutputStore) -> dict:
    """Schema names to callback names, with every path argument confined to the output dir."""
    out: dict[str, Any] = {}
    for name, value in arguments.items():
        if value is None:
            continue
        if name in spec.path_params:
            value = (
                [store.resolve(v) for v in value]
                if isinstance(value, list)
                else store.resolve(value)
            )
        out[spec.params[name]] = value
    return out


def _run_local(spec: discover.ToolSpec, kwargs: dict[str, Any], *, as_json: bool) -> render.Result:
    """A verb that answers from the local cache, run through its Click callback."""
    callback = spec.command.callback
    # `status` and `claims` read the root context for the timezone and debug level; `version`
    # takes no context at all.
    if "ctx" in inspect.signature(callback).parameters:
        group = typer.main.get_group(_app())
        root_ctx = typer.Context(group, obj=_globals())
        kwargs["ctx"] = typer.Context(spec.command, parent=root_ctx, info_name=spec.path)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        callback(json_=as_json, **kwargs)
    text = buffer.getvalue()
    return render.TextResult(text=text, json_obj=json.loads(text) if as_json else None)


@functools.lru_cache(maxsize=1)
def _app() -> typer.Typer:
    from mgraphctl.cli import build_app

    return build_app()


def invoke(
    spec: discover.ToolSpec,
    arguments: dict[str, Any],
    *,
    store: output.OutputStore,
) -> output.ToolOutput:
    """One tool call, start to finish. Runs on a worker thread: every Graph call is synchronous."""
    try:
        jsonschema.validate(arguments, spec.input_schema)
    except jsonschema.ValidationError as exc:
        raise UsageError("USAGE", exc.message) from exc

    arguments = dict(arguments)
    output_format = arguments.pop("output_format", "text")
    output_file = arguments.pop("output_file", None)
    kwargs = _kwargs(spec, arguments, store)

    try:
        if spec.fn is None:
            result = _run_local(spec, kwargs, as_json=output_format == "json")
        else:
            with open_client(_globals(), spec.scopes) as client:
                result = spec.fn(client, **kwargs)
    finally:
        auth.save_cache()

    if result is None:  # a verb that only prints; nothing left to render
        result = render.TextResult(text="", json_obj=None)
    return output.build(
        result,
        store=store,
        tool_name=spec.name,
        output_format=output_format,
        output_file=output_file,
    )


def _error(text: str) -> types.CallToolResult:
    """A tool execution error: the spec wants these readable, so the model can correct itself."""
    return types.CallToolResult(content=[types.TextContent(text=text)], is_error=True)


def _resource_link(link: output.FileLink) -> types.ResourceLink:
    return types.ResourceLink(
        name=link.name,
        uri=link.uri,
        title=link.name,
        description=f"{link.bytes} bytes written by mgraphctl",
        mime_type=link.mime,
        size=link.bytes,
    )


def build(settings: Settings | None = None, app: typer.Typer | None = None) -> Server:
    """The server, with its tool set fixed at startup by the operator's `--capabilities`."""
    settings = settings or Settings()
    app = app or _app()
    store = settings.store()
    specs = {
        spec.name: spec
        for spec in discover.discover(
            app, capabilities=settings.capabilities, allow_write=settings.allow_write
        )
    }

    async def list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[_tool(spec) for spec in specs.values()])

    async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        spec = specs.get(params.name)
        if spec is None:
            # A name that was never listed is a protocol error, not something to self-correct.
            raise ValueError(f"unknown tool: {params.name}")
        call = functools.partial(invoke, spec, params.arguments or {}, store=store)
        try:
            result = await anyio.to_thread.run_sync(call)
        except MsgraphError as exc:
            # format_error already states the code, the message and an actionable hint.
            return _error(format_error(exc))
        except OSError as exc:
            return _error(format_error(MsgraphError("IO", str(exc))))
        except Exception as exc:  # noqa: BLE001 - the model gets to see what went wrong
            log.debug("tool %s failed", params.name, exc_info=True)
            return _error(format_error(MsgraphError("INTERNAL", f"{type(exc).__name__}: {exc}")))
        content: list[types.ContentBlock] = [types.TextContent(text=result.text)]
        if result.link is not None:
            content.append(_resource_link(result.link))
        return types.CallToolResult(content=content, structured_content=result.payload)

    async def list_resources(ctx: Any, params: Any) -> types.ListResourcesResult:
        return types.ListResourcesResult(
            resources=[
                types.Resource(
                    name=str(path.relative_to(store.root.resolve())),
                    uri=path.as_uri(),
                    mime_type=output.mime_for(path),
                    size=path.stat().st_size,
                )
                for path in store.files()
            ]
        )

    async def read_resource(ctx: Any, params: types.ReadResourceRequestParams) -> Any:
        text, mime = store.read(str(params.uri))
        return types.ReadResourceResult(
            contents=[types.TextResourceContents(uri=str(params.uri), mime_type=mime, text=text)]
        )

    return Server(
        "mgraphctl",
        version=__version__,
        title="mgraphctl",
        instructions=(
            "Microsoft Graph through the mgraphctl CLI. Tools return a compact text table by "
            "default; pass output_format='json' for the full payload, or output_file='name.json' "
            "to have a large result written to a file and linked instead of inlined."
        ),
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_read_resource=read_resource,
    )
