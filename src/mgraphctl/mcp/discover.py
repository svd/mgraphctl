"""The Click tree becomes tool specs (MCP spec §4).

`walk` is the single definition of "every registered verb": `tests/test_surface.py` imports it, so
the CLI's coverage invariants and the MCP tool set cannot describe different command trees.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import typer
import typer.main

from mgraphctl.errors import UsageError
from mgraphctl.mcp import schema

# `login` and `logout` drive a browser and a credential store; `config` edits the operator's file;
# `mcp` runs this server. All three belong to the person running the server, not to the model
# talking to it — a tool that could restart the server with `--allow-write` would defeat the gate.
EXCLUDED = {
    "login",
    "logout",
    "config path",
    "config show",
    "config init",
    "config set",
    "config unset",
    "mcp serve",
    "mcp tools",
}

# Verbs that change something. Kept explicit because a scope is not a reliable signal in either
# direction: Graph has no read-only Tasks scope, so `planner tasks` must ask for `Tasks.ReadWrite`
# to read, while `chats create` writes holding nothing that matches "ReadWrite".
# `test_mcp_discover.py` fails if a verb is unclassified, if a mutating verb lacks a scope that
# could write, or if a verb that could write is neither listed here nor in READ_WITH_WRITE_SCOPE.
MUTATING = frozenset(
    {
        "api",  # takes --method; a POST or DELETE is one argument away
        "calendar create",
        "calendar delete",
        "calendar respond",
        "calendar update",
        "chats create",
        "chats dm",
        "chats send",
        "mail delete",
        "mail drafts create",
        "mail drafts send",
        "mail forward",
        "mail mark",
        "mail move",
        "mail reply",
        "mail send",
        "mailbox oof set",
        "onedrive delete",
        "onedrive mkdir",
        "onedrive move",
        "onedrive rename",
        "onedrive share",
        "onedrive upload",
        "onenote create",
        "planner complete",
        "planner create",
        "planner delete",
        "planner update",
        "presence clear",
        "presence set",
        "sharepoint upload",
        "teams channel send",
        "todo complete",
        "todo create",
        "todo delete",
        "todo from-mail",
        "todo update",
    }
)

# Reads that have to declare a write-capable scope because Graph offers no narrower one.
READ_WITH_WRITE_SCOPE = frozenset(
    {
        "planner buckets",
        "planner plan",
        "planner plans",
        "planner task",
        "planner tasks",
        "todo lists",
        "todo task",
        "todo tasks",
    }
)

WRITE_SCOPE_MARKERS = ("ReadWrite", ".Send", ".Create", ".Write")

# Command groups the operator can switch on, plus the two synthetic ones. `core` is the top-level
# verbs; `api` is the raw Graph escape hatch and is never part of `all`.
CORE = "core"
API = "api"
DEFAULT = ("core", "mail", "calendar", "people", "chats")


@dataclass(frozen=True)
class ToolSpec:
    """One CLI verb, as much as the server needs to expose and to call it."""

    name: str
    path: str
    description: str
    capability: str
    mutating: bool
    scopes: list[str]
    command: Any
    input_schema: dict[str, Any]
    annotations: dict[str, bool]
    # Schema property name -> the callback's Python parameter name (`from` -> `from_`).
    params: dict[str, str]
    # Property names holding a filesystem path; the server confines each to its output directory.
    path_params: frozenset[str]
    # Property names holding a path only behind a leading `@` (`api --body @FILE`).
    at_file_params: frozenset[str]
    # The undecorated `fn(client, **kwargs)` of a `@graph_command`; None for a verb that answers
    # locally (`status`, `claims`, `version`) and is invoked through its Click callback instead.
    fn: Callable[..., Any] | None

    @property
    def title(self) -> str:
        return self.path


def walk(app: Any) -> dict[str, Any]:
    """Every leaf verb in the tree, keyed by the path a user would type."""
    group = app if hasattr(app, "commands") else typer.main.get_group(app)
    out: dict[str, Any] = {}

    def rec(cmd: Any, prefix: str) -> None:
        for name, sub in cmd.commands.items():
            full = f"{prefix} {name}".strip()
            if hasattr(sub, "commands"):
                rec(sub, full)
            else:
                out[full] = sub

    rec(group, "")
    return out


# Every capability name. `test_mcp_discover.py` checks this against the groups the CLI registers,
# so a new noun cannot be silently unreachable.
ALL = frozenset(
    {
        CORE,
        API,
        "calendar",
        "chats",
        "groups",
        "mail",
        "mailbox",
        "meetings",
        "onedrive",
        "onenote",
        "org",
        "people",
        "planner",
        "presence",
        "sharepoint",
        "teams",
        "todo",
    }
)


def capabilities_of(app: Any) -> set[str]:
    """The capability names the registered command tree actually offers."""
    groups = {path.split(" ")[0] for path in walk(app) if " " in path}
    return groups - {"config", "mcp"} | {CORE, API}


def resolve(value: str | None) -> list[str]:
    """`--capabilities` to a list of names. Omitted is the default set; `all` excludes `api`."""
    if value is None:
        return list(DEFAULT)
    names = [n.strip() for n in value.split(",") if n.strip()]
    if names == ["all"]:
        return sorted(ALL - {API})
    unknown = [n for n in names if n not in ALL]
    if unknown:
        raise UsageError(
            "USAGE",
            f"unknown capability {', '.join(sorted(unknown))}; "
            f"choose from {', '.join(sorted(ALL))}, or 'all'",
        )
    return list(dict.fromkeys(names))


def can_write(scopes: list[str]) -> bool:
    """Whether the declared scopes permit anything but a read."""
    return any(marker in scope for scope in scopes for marker in WRITE_SCOPE_MARKERS)


def _annotations(path: str, mutating: bool) -> dict[str, bool]:
    """Hints for the host's confirmation UI. The server's own gate is `--allow-write`."""
    if not mutating:
        return {"readOnlyHint": True, "openWorldHint": True}
    verb = path.rsplit(" ", 1)[-1]
    return {
        "readOnlyHint": False,
        "destructiveHint": verb == "delete",
        "idempotentHint": verb in ("update", "set", "mark", "complete", "rename", "clear"),
        "openWorldHint": True,
    }


def spec_for(path: str, command: Any) -> ToolSpec:
    callback = command.callback
    scopes = list(getattr(callback, "__graph_scopes__", []) or [])
    properties, params = schema.build(command)
    mutating = path in MUTATING
    return ToolSpec(
        name=path.replace(" ", "_"),
        path=path,
        description=(command.help or command.short_help or path).strip(),
        capability=path.split(" ")[0] if " " in path else (API if path == API else CORE),
        mutating=mutating,
        scopes=scopes,
        command=command,
        input_schema=properties,
        annotations=_annotations(path, mutating),
        params=params,
        path_params=schema.path_params(command),
        at_file_params=frozenset(schema.AT_FILE_PARAMS.get(path, ())),
        # `@graph_command` stashes the undecorated `fn(client, **kwargs)`; a verb that answers
        # locally has none and is invoked through its Click callback instead.
        fn=getattr(callback, "__graph_fn__", None),
    )


def discover(
    app: Any,
    *,
    capabilities: list[str] | frozenset[str],
    allow_write: bool = False,
) -> list[ToolSpec]:
    """The tools this server exposes, in a deterministic order (the spec asks for one)."""
    wanted = set(capabilities)
    out = []
    for path, command in sorted(walk(app).items()):
        if path in EXCLUDED:
            continue
        spec = spec_for(path, command)
        if spec.capability not in wanted or (spec.mutating and not allow_write):
            continue
        out.append(spec)
    return out
