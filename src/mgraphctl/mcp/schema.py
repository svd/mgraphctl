"""Click parameters become a tool's JSON Schema (MCP spec §4.2, §5).

The schema is closed: a client cannot smuggle a keyword the callback never declared.
"""

from __future__ import annotations

from typing import Any

# The CLI's `--json` is a switch on a stream the CLI owns; MCP has three channels for the same
# information, so it becomes `output_format` and `output_file` instead (MCP spec §5).
DROPPED = {"json_"}

OUTPUT_FORMAT = {
    "type": "string",
    "enum": ["text", "json"],
    "default": "text",
    "description": (
        "'text' returns the compact table the CLI prints — far cheaper to read. "
        "'json' returns the full Graph payload as structured content."
    ),
}
OUTPUT_FILE = {
    "type": "string",
    "description": (
        "Optional file name, relative to the server's output directory. Given one, the full "
        "result is written there and a link is returned instead of the payload — use it for "
        "large fetches you want to keep out of the conversation."
    ),
}

_SCALARS = {
    "text": "string",
    "str": "string",
    "integer": "integer",
    "int": "integer",
    "int range": "integer",
    "boolean": "boolean",
    "path": "string",
    "file": "string",
    "filename": "string",
    "choice": "string",
}


# Click types whose value is a filesystem path. The server resolves every one of them inside its
# own output directory, so a tool argument cannot reach the rest of the filesystem.
PATH_TYPES = {"path", "file", "filename"}


def path_params(command: Any) -> frozenset[str]:
    """The schema property names whose value is a path."""
    return frozenset(property_name(p) for p in command.params if p.type.name in PATH_TYPES)


def property_name(param: Any) -> str:
    """`from_` -> `from`: the callback's name freed of the underscore Python forced on it."""
    return param.name.rstrip("_") if param.name.endswith("_") else param.name


def _type_of(param: Any) -> dict[str, Any]:
    kind = _SCALARS.get(param.type.name, "string")
    node: dict[str, Any] = {"type": kind}
    choices = getattr(param.type, "choices", None)
    if choices:
        node["enum"] = list(choices)
    if param.multiple:
        return {"type": "array", "items": node}
    return node


def _describe(param: Any) -> str:
    help_text = (getattr(param, "help", None) or "").strip()
    if param.param_type_name == "argument":
        return help_text or f"{param.name} (positional argument)"
    flags = ", ".join(param.opts)
    return f"{help_text} ({flags})" if help_text else flags


def build(command: Any) -> tuple[dict[str, Any], dict[str, str]]:
    """The tool's `inputSchema`, and the schema-name -> Python-name map the dispatcher needs."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    params: dict[str, str] = {}
    for param in command.params:
        if param.name in DROPPED or param.name == "ctx":
            continue
        name = property_name(param)
        node = _type_of(param)
        node["description"] = _describe(param)
        if param.default is not None and not param.required and not param.multiple:
            node["default"] = param.default
        properties[name] = node
        params[name] = param.name
        if param.required:
            required.append(name)
    properties["output_format"] = dict(OUTPUT_FORMAT)
    properties["output_file"] = dict(OUTPUT_FILE)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema, params
