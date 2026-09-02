"""Command-line entry point (minimal stub; completed in Task 6)."""

from typing import Annotated

import typer

from mgraphctl import __version__

app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"mgraphctl {__version__}")
        raise typer.Exit(0)


@app.callback()
def root(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version, is_eager=True, help="Print the version and exit."
        ),
    ] = False,
) -> None:
    """Microsoft Graph from the command line."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


def main() -> None:
    app(prog_name="mgraphctl")
