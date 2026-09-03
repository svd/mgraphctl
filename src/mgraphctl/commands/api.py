"""The raw `api` escape hatch (spec §8.17). No scopes are declared; Graph decides."""

import json as jsonlib
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from mgraphctl import odata
from mgraphctl.cli import AllFlag, DryRunFlag, JsonFlag, graph_command
from mgraphctl.errors import UsageError
from mgraphctl.http import GraphClient, PlannedRequest
from mgraphctl.render import DryRunResult, FileResult, TextResult, WriteResult, fmt_size

JSON_CONTENT = "application/json"
PAGE_CAP = sys.maxsize


def _params(query: list[str]) -> dict[str, str]:
    """`--query k=v` pairs, split on the first `=`."""
    out: dict[str, str] = dict()
    for item in query:
        key, sep, value = item.partition("=")
        if not sep:
            raise UsageError("USAGE", f"--query needs k=v, got {item!r}")
        out[key] = value
    return out


def _headers(header: list[str]) -> dict[str, str]:
    """`--header k:v` pairs, split on the first `:`."""
    out: dict[str, str] = dict()
    for item in header:
        key, sep, value = item.partition(":")
        if not sep:
            raise UsageError("USAGE", f"--header needs k:v, got {item!r}")
        out[key.strip()] = value.strip()
    return out


def _body(body: str | None) -> Any:
    """JSON text, or `@FILE` naming a file that holds it."""
    if body is None:
        return None
    text = Path(body[1:]).read_text() if body.startswith("@") else body
    try:
        return jsonlib.loads(text)
    except jsonlib.JSONDecodeError as exc:
        raise UsageError("USAGE", f"--body is not valid JSON: {exc}") from exc


def _write_bytes(data: bytes, output: Path | None) -> FileResult | None:
    if output is None:
        sys.stdout.flush()
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        return None
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    return FileResult(
        path=output,
        bytes=len(data),
        meta=dict(),
        message=f"Wrote {fmt_size(len(data))} to {output}",
    )


def _document(obj: Any) -> TextResult:
    """A JSON body, pretty-printed in text mode and passed through unchanged in JSON mode."""
    return TextResult(text=jsonlib.dumps(obj, indent=2, ensure_ascii=False), json_obj=obj)


@graph_command(scopes=[])
def api(
    client: GraphClient,
    method: Annotated[str, typer.Argument(metavar="METHOD", help="GET, POST, PATCH, PUT, DELETE.")],
    path: Annotated[
        str, typer.Argument(metavar="PATH", help="Graph path such as /me, or an absolute URL.")
    ],
    query: Annotated[
        list[str] | None, typer.Option("--query", help="k=v query parameter (repeatable).")
    ] = None,
    body: Annotated[
        str | None, typer.Option("--body", help="JSON request body, or @FILE holding it.")
    ] = None,
    header: Annotated[
        list[str] | None, typer.Option("--header", help="k:v request header (repeatable).")
    ] = None,
    beta: Annotated[
        bool, typer.Option("--beta", help="Send this call to the /beta endpoint.")
    ] = False,
    all_: AllFlag = False,
    raw: Annotated[
        bool, typer.Option("--raw", help="Treat the response as bytes, not JSON.")
    ] = False,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write the --raw bytes to this file.")
    ] = None,
    outlook_tz: Annotated[bool, typer.Option("--outlook-tz", hidden=True)] = False,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Send one request to Microsoft Graph and print what comes back."""
    params = _params(query or [])
    headers = _headers(header or [])
    payload = _body(body)
    verb = method.upper()
    use_beta = True if beta else None
    if dry_run:
        planned = dict(headers)
        if payload is not None:
            planned.setdefault("Content-Type", JSON_CONTENT)
        url = client.url(odata.with_query(path, params), beta=use_beta)
        return DryRunResult([PlannedRequest(verb, url, planned, payload)])
    if all_:
        page = client.paginate(
            path,
            params=params,
            headers=headers or None,
            beta=use_beta,
            outlook_tz=outlook_tz,
            limit=None,
            all_=True,
            cap=PAGE_CAP,
            page_size=None,
        )
        return _document(dict(value=page.items))
    call = dict(
        params=params,
        json=payload,
        headers=headers or None,
        beta=use_beta,
        outlook_tz=outlook_tz,
    )
    if raw:
        return _write_bytes(client.request(verb, path, expect="bytes", **call), output)
    response = client.request(verb, path, expect="response", **call)
    content_type = response.headers.get("content-type", "")
    data = response.read()
    response.close()
    if not data:
        return WriteResult(obj=None, message="OK")
    if "json" in content_type:
        return _document(jsonlib.loads(data))
    return TextResult(text=data.decode("utf-8", errors="replace"), json_obj=None)


def register(root: typer.Typer) -> None:
    """Attach `api` to the root app."""
    root.command("api")(api)
