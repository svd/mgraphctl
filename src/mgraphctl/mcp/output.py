"""A `Result` becomes what a tool call returns (MCP spec §5).

The CLI's `--json` is a switch on a stream the CLI owns. MCP has three channels for the same
information — a text block, `structuredContent`, and a link to a file the client can read later —
so the flag becomes a choice among them. This module makes that choice and owns every path the
server touches; it holds no MCP types, so `server.py` decides how to put it on the wire.
"""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mgraphctl import render
from mgraphctl.errors import UsageError

# Past this, a result is written to a file whatever the caller asked for, so that one runaway
# `--all` cannot fill the client's context.
DEFAULT_MAX_INLINE_BYTES = 25_000

# How much of a spilled result is quoted back, so the model can see what it got.
EXCERPT_LINES = 12

MIME_TEXT = "text/plain"
MIME_JSON = "application/json"


def default_root() -> Path:
    cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache) if cache else Path.home() / ".cache"
    return base / "mgraphctl" / "mcp"


@dataclass(frozen=True)
class FileLink:
    """A file this server produced, as a tool result points at it."""

    path: Path
    uri: str
    name: str
    mime: str
    bytes: int


@dataclass(frozen=True)
class ToolOutput:
    """What one tool call produced, before `server.py` turns it into MCP content."""

    text: str
    payload: Any | None = None
    link: FileLink | None = None


class OutputStore:
    """The one directory the server reads and writes.

    Every path a tool argument names is resolved inside it, and so is every file the server
    spills. A caller cannot reach the rest of the filesystem through a tool argument, in either
    direction: the server writes where the operator configured, not where the caller asks.
    """

    def __init__(self, root: Path, *, max_inline_bytes: int = DEFAULT_MAX_INLINE_BYTES) -> None:
        self.root = Path(root).expanduser()
        self.max_inline_bytes = max_inline_bytes

    def ensure(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self.root

    def resolve(self, name: str | Path) -> Path:
        """A caller-supplied name as a path inside the store, or a usage error."""
        candidate = Path(name)
        if candidate.is_absolute():
            raise UsageError(
                "USAGE",
                f"{name!r} is an absolute path; name a file relative to the server's "
                "output directory instead",
            )
        self.ensure()
        # resolve() follows symlinks, so a link planted inside the store cannot lead out of it.
        target = (self.root / candidate).resolve()
        root = self.root.resolve()
        if target != root and root not in target.parents:
            raise UsageError("USAGE", f"{name!r} leaves the server's output directory")
        return target

    def contains(self, path: Path) -> bool:
        resolved = Path(path).resolve()
        root = self.root.resolve()
        return resolved == root or root in resolved.parents

    def write(self, name: str | Path, text: str) -> Path:
        path = self.resolve(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def files(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(p for p in self.root.rglob("*") if p.is_file())

    def read(self, uri: str) -> tuple[str, str]:
        """The text of a `file://` URI this store produced, with its media type."""
        prefix = "file://"
        if not uri.startswith(prefix):
            raise UsageError("USAGE", f"{uri!r} is not a file:// URI")
        from urllib.parse import unquote, urlparse

        path = Path(unquote(urlparse(uri).path))
        if not self.contains(path):
            raise UsageError("USAGE", f"{uri!r} is outside the server's output directory")
        if not path.is_file():
            raise UsageError("USAGE", f"{uri!r} does not exist")
        return path.read_text(), mime_for(path)


def mime_for(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or MIME_TEXT


def link_to(store: OutputStore, path: Path) -> FileLink:
    return FileLink(
        path=path,
        uri=path.as_uri(),
        name=str(path.relative_to(store.root.resolve())) if store.contains(path) else path.name,
        mime=mime_for(path),
        bytes=path.stat().st_size,
    )


def _summary(result: render.Result, payload: Any) -> str:
    """One line saying what a file holds, so the link does not have to be opened to know."""
    if isinstance(result, render.ListResult):
        count = len(result.items)
        noun = "item" if count == 1 else "items"
        more = ", truncated" if result.truncated else ""
        return f"{count} {noun}{more}"
    if isinstance(payload, list):
        return f"{len(payload)} items"
    return "1 item"


def _excerpt(text: str) -> str:
    lines = text.splitlines()
    head = "\n".join(lines[:EXCERPT_LINES])
    return head if len(lines) <= EXCERPT_LINES else head + "\n…"


def build(
    result: render.Result,
    *,
    store: OutputStore,
    tool_name: str,
    output_format: str = "text",
    output_file: str | None = None,
) -> ToolOutput:
    """Turn a verb's result into a text block, structured content, or a link to a file."""
    as_json = output_format == "json"
    payload = render.to_json(result)
    body = "".join([render.to_text(result), *(f"{line}\n" for line in render.notes(result))])
    document = json.dumps(payload, indent=2, ensure_ascii=False) + "\n" if as_json else body
    summary = _summary(result, payload)

    # A verb that wrote a file of its own (a download, a photo) is already a link.
    if isinstance(result, render.FileResult) and output_file is None:
        return ToolOutput(text=body, link=link_to(store, Path(result.path)))

    if output_file is not None:
        path = store.write(output_file, document)
        link = link_to(store, path)
        return ToolOutput(text=f"{summary} written to {link.name} ({link.uri})\n", link=link)

    if len(document.encode()) > store.max_inline_bytes:
        suffix = ".json" if as_json else ".txt"
        name = f"{tool_name}-{secrets.token_hex(4)}{suffix}"
        path = store.write(name, document)
        link = link_to(store, path)
        return ToolOutput(
            text=(
                f"{summary}, too large to inline — written to {link.name} ({link.uri}).\n"
                f"First {EXCERPT_LINES} lines:\n{_excerpt(document)}\n"
            ),
            link=link,
        )

    return ToolOutput(text=document, payload=payload if as_json else None)
