"""Root typer app, global options and the `@graph_command` decorator (spec §6.1, §6.5, §7.1).

`from __future__ import annotations` must NOT be added here or to any `commands/*` module:
typer reads the real `Annotated` objects off each command signature.
"""

import functools
import inspect
import logging
import os
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, TypeVar

import typer
import typer.core

from mgraphctl import __version__, auth, config, fixtures, render
from mgraphctl.errors import MsgraphError, UsageError, format_error
from mgraphctl.http import GraphClient

log = logging.getLogger("mgraphctl")
F = TypeVar("F", bound=Callable[..., Any])

# Exceptions typer and Click use for control flow; they must reach Click's own handler.
CONTROL_FLOW = (typer.Exit, typer.Abort, typer.TyperException)


@dataclass
class Globals:
    """The root callback's decisions, handed to every command through `ctx.obj`."""

    debug: int
    tz: str
    beta: bool
    # Config keys a root flag overrode (`tz`, `debug`), so `config show` can say so.
    flag_keys: frozenset[str] = frozenset()


JsonFlag = Annotated[bool, typer.Option("--json", help="Print JSON instead of text.")]
DryRunFlag = Annotated[bool, typer.Option("--dry-run", help="Show the request(s); send nothing.")]
LimitOpt = Annotated[int | None, typer.Option("--limit", min=1, help="Maximum items.")]
AllFlag = Annotated[bool, typer.Option("--all", help="Fetch every page up to the cap.")]


class MsgraphGroup(typer.core.TyperGroup):
    """Maps every failure to the §6.5 stderr block plus an exit code, and flushes the cache."""

    def invoke(self, ctx: typer.Context) -> Any:
        try:
            return super().invoke(ctx)
        except MsgraphError as exc:
            self._fail(ctx, format_error(exc), exc.exit_code)
        except CONTROL_FLOW:
            raise  # --help, --version, Click parse errors: Click renders and exits on its own.
        except OSError as exc:
            self._fail(ctx, format_error(MsgraphError("IO", _io_detail(exc))), 1)
        except Exception as exc:
            block = format_error(MsgraphError("INTERNAL", f"{type(exc).__name__}: {exc}"))
            if _debug_level(ctx) >= 1:
                block += "".join(traceback.format_exception(exc))
            self._fail(ctx, block, 1)
        finally:
            auth.save_cache()

    @staticmethod
    def _fail(ctx: typer.Context, block: str, exit_code: int) -> None:
        sys.stdout.flush()
        sys.stderr.write(block)
        ctx.exit(exit_code)


def _io_detail(exc: OSError) -> str:
    detail = exc.strerror or str(exc)
    return f"{detail}: {exc.filename}" if exc.filename else detail


def _debug_level(ctx: typer.Context) -> int:
    """The `--debug` count, or 0 when the root callback has not run yet."""
    g = ctx.find_root().obj
    return g.debug if isinstance(g, Globals) else 0


def _noargs_help(ctx: typer.Context) -> None:
    """No verb at this level prints its help and exits 0 (§6.1; `no_args_is_help` exits 2)."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


def make_noun_app(help: str) -> typer.Typer:  # noqa: A002 - name fixed by the Phase 0 contract
    """A noun sub-app whose bare invocation prints help instead of failing."""
    return typer.Typer(
        help=help,
        invoke_without_command=True,
        callback=_noargs_help,
        add_completion=False,
        rich_markup_mode=None,
        pretty_exceptions_enable=False,
    )


def open_client(g: Globals, scopes: list[str]) -> GraphClient:
    """Run the local scope gate, then build the client every command shares."""
    token = auth.get_access_token(False)
    auth.require_scopes(token, scopes)
    cfg = config.settings()
    return GraphClient(
        auth.get_access_token,
        tz=g.tz,
        beta=g.beta,
        debug=g.debug,
        transport=fixtures.transport_from_env(cfg),
        retries=cfg.retries,
        timeout_ms=cfg.timeout_ms,
        retry_base_ms=cfg.retry_base_ms,
    )


def gate(scopes: list[str]) -> None:
    """Re-check scopes at a branch that needs more than the command declared (§4.4)."""
    auth.require_scopes(auth.get_access_token(False), scopes)


def page_bounds(limit: int | None, all_: bool, *, default: int) -> tuple[int, bool]:
    """Normalise the `--limit` / `--all` pair for a list verb."""
    if all_ and limit is not None:
        raise UsageError("USAGE", "--all and --limit are mutually exclusive")
    return (limit if limit is not None else default), all_


def read_body(body: str | None, body_file: str | None) -> str:
    """The message body from `--body`, `--body-file FILE`, or `--body-file -` (stdin)."""
    if (body is None) == (body_file is None):
        raise UsageError("USAGE", "give exactly one of --body or --body-file")
    if body is not None:
        return body
    return sys.stdin.read() if body_file == "-" else Path(body_file).read_text()


def graph_command(*, scopes: list[str]) -> Callable[[F], F]:
    """Gate the scopes, open a client, inject it as `client`, and render what the verb returns."""
    auth.DECLARED_SCOPES.update(s for entry in scopes for s in entry.split("|"))

    def decorate(fn: F) -> F:
        sig = inspect.signature(fn)
        params = [p for p in sig.parameters.values() if p.name != "client"]
        ctx_param = inspect.Parameter(
            "ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=typer.Context
        )

        @functools.wraps(fn)
        def wrapper(ctx: typer.Context, **kwargs: Any) -> None:
            g: Globals = ctx.find_root().obj
            with open_client(g, scopes) as client:
                result = fn(client, **kwargs)
            if result is not None:
                render.emit(result, json_mode=bool(kwargs.get("json_", False)))

        # typer reads the signature and the annotations; `client` is ours, not the CLI's.
        wrapper.__signature__ = sig.replace(parameters=[ctx_param, *params])
        annotations = dict(fn.__annotations__)
        annotations.pop("client", None)
        annotations["ctx"] = typer.Context
        wrapper.__annotations__ = annotations
        wrapper.__graph_scopes__ = list(scopes)
        # The MCP server calls the verb directly to get its `Result` back instead of printed.
        # `__wrapped__` cannot serve: typer wraps this wrapper again, so the chain's first link
        # is the wrapper itself. `functools.wraps` copies `__dict__`, so this attribute survives.
        wrapper.__graph_fn__ = fn
        return wrapper  # type: ignore[return-value]

    return decorate


def _version_cb(value: bool) -> None:
    if value:
        typer.echo(f"mgraphctl {__version__}")
        raise typer.Exit(0)


def _configure_logging(level: int) -> None:
    """Bind logging to the current stderr and prefix every line with its level (§5.7)."""
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if level else logging.WARNING,
        format="%(levelname)s %(message)s",
        force=True,
    )
    logging.getLogger("msal").setLevel(logging.INFO if level else logging.WARNING)


def build_app() -> typer.Typer:
    """The whole CLI: global options, the top-level verbs, `api`, and every noun that exists."""
    root = typer.Typer(
        cls=MsgraphGroup,
        invoke_without_command=True,
        add_completion=False,
        rich_markup_mode=None,
        pretty_exceptions_enable=False,
        help="Microsoft Graph from the command line.",
    )

    @root.callback()
    def _root(
        ctx: typer.Context,
        debug: Annotated[
            int,
            typer.Option(
                "--debug", "-d", count=True, help="Log requests to stderr (-dd adds bodies)."
            ),
        ] = 0,
        tz: Annotated[
            str | None,
            typer.Option("--tz", help="IANA time zone (else MGRAPHCTL_TZ, the config file)."),
        ] = None,
        beta: Annotated[bool, typer.Option("--beta", help="Use the /beta endpoint.")] = False,
        config_file: Annotated[
            Path | None,
            typer.Option(
                "--config",
                help="Config file (else MGRAPHCTL_CONFIG, ~/.mgraphctl/config.toml).",
            ),
        ] = None,
        version: Annotated[
            bool,
            typer.Option(
                "--version",
                callback=_version_cb,
                is_eager=True,
                help="Print the version and exit.",
            ),
        ] = False,
    ) -> None:
        if config_file is not None:
            # `settings()` reads the environment, so the flag becomes the env var for this run.
            os.environ["MGRAPHCTL_CONFIG"] = str(config_file)
        s = config.settings()
        zone = tz or s.tz or render.local_tz()
        if not render.is_iana(zone):
            raise UsageError(
                "USAGE", f"unknown time zone {zone!r}; use an IANA name such as Europe/Warsaw"
            )
        level = max(debug, s.debug)
        _configure_logging(level)
        flag_keys = {k for k, hit in (("tz", tz), ("debug", debug and debug >= s.debug)) if hit}
        ctx.obj = Globals(debug=level, tz=zone, beta=beta, flag_keys=frozenset(flag_keys))
        _noargs_help(ctx)

    from mgraphctl.commands import api, config_cmd, mcp_cmd, register_all, top

    top.register(root)
    api.register(root)
    config_cmd.register(root)
    mcp_cmd.register(root)
    register_all(root)
    return root


def main() -> None:
    build_app()(prog_name="mgraphctl")
