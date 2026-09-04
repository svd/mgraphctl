"""`config path|show|init`: the config file, its resolved values and where each came from."""

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from mgraphctl import config, render
from mgraphctl.cli import Globals, JsonFlag, make_noun_app
from mgraphctl.errors import UsageError
from mgraphctl.render import TextResult, WriteResult

app = make_noun_app("The config file: where it is, what it resolves to, and a starter template.")


@app.command("path")
def path_(json_: JsonFlag = False) -> None:
    """Print the config file path in use."""
    p = config.config_path()
    render.emit(
        TextResult(text=str(p), json_obj=dict(path=str(p), exists=p.exists())), json_mode=json_
    )


@app.command("show")
def show(ctx: typer.Context, json_: JsonFlag = False) -> None:
    """Every setting with its effective value and source (flag, env, file or default)."""
    g: Globals = ctx.find_root().obj
    rows = []
    for key, value, source in config.effective_settings():
        # The root callback already resolved these two (flag, detection): report what it uses.
        if key == "tz":
            value = g.tz
        elif key == "debug":
            value = g.debug
        if key in g.flag_keys:
            source = "flag"
        rows.append((key, value, source))
    unknown = config.unknown_config_keys()
    p = config.config_path()
    width = max(len(k) for k, _, _ in rows)
    vwidth = max(len(str(v)) for _, v, _ in rows)
    lines = [f"Config file: {p}"]
    lines += [f"  {k:<{width}}  {str(v):<{vwidth}}  {src}" for k, v, src in rows]
    if unknown:
        lines.append(f"Unknown keys ignored: {', '.join(unknown)}")
    payload = dict(
        path=str(p),
        settings={k: v for k, v, _ in rows},
        sources={k: src for k, _, src in rows},
        unknownKeys=unknown,
    )
    render.emit(TextResult(text="\n".join(lines), json_obj=payload), json_mode=json_)


@app.command("init")
def init(
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
    json_: JsonFlag = False,
) -> None:
    """Write a commented template with every key at its default."""
    p = config.config_path()
    existed = p.exists()
    if existed and not force:
        raise UsageError("USAGE", f"{p} already exists", hint="pass --force to overwrite it")
    _write(p, config.CONFIG_TEMPLATE)
    render.emit(
        WriteResult(obj=dict(path=str(p), overwritten=existed), message=f"Wrote {p}"),
        json_mode=json_,
    )


@app.command("set")
def set_(
    key: Annotated[str, typer.Argument(help="One of the config keys (see `config show`).")],
    value: Annotated[str, typer.Argument(help="The value; integers for the numeric keys.")],
    json_: JsonFlag = False,
) -> None:
    """Set one key in the config file, creating the file when it does not exist."""
    parsed = config.parse_config_value(key, value)
    if key == "tz" and not render.is_iana(value):
        raise UsageError("USAGE", f"unknown time zone {value!r}; use an IANA name")
    p = config.config_path()
    config.load_config_file(p)  # a file that is not valid TOML must be fixed by hand first
    _write(p, config.upsert_config_line(_read(p), key, parsed))
    message = f"Set {key} = {config.format_toml_value(parsed)} in {p}"
    render.emit(
        WriteResult(obj=dict(path=str(p), key=key, value=parsed), message=message),
        json_mode=json_,
    )


@app.command("unset")
def unset(
    key: Annotated[str, typer.Argument(help="One of the config keys (see `config show`).")],
    json_: JsonFlag = False,
) -> None:
    """Comment a key out of the config file, so the environment or the default applies."""
    if key not in config.CONFIG_KEYS:
        raise UsageError(
            "USAGE",
            f"unknown config key {key!r}",
            hint=f"one of: {', '.join(config.CONFIG_KEYS)}",
        )
    p = config.config_path()
    removed = key in config.load_config_file(p)
    if removed:
        _write(p, config.upsert_config_line(_read(p), key, None))
    render.emit(
        WriteResult(obj=dict(path=str(p), key=key, removed=removed), message=f"Unset {key} in {p}"),
        json_mode=json_,
    )


def _read(p: Path) -> str:
    try:
        return p.read_text()
    except FileNotFoundError:
        return ""


def _write(p: Path, text: str) -> None:
    """Atomic 0600 write into a 0700 directory, the same way the token cache is saved."""
    p.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        p.parent.chmod(0o700)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f"{p.name}.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, text.encode())
    finally:
        os.close(fd)
    os.replace(tmp, p)


def register(root: typer.Typer) -> None:
    root.add_typer(app, name="config")
