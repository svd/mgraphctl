"""Mailbox settings, automatic replies and the focused inbox (spec §8.3)."""

from typing import Annotated

import typer

from mgraphctl.cli import (
    AllFlag,
    DryRunFlag,
    JsonFlag,
    LimitOpt,
    graph_command,
    make_noun_app,
    page_bounds,
)
from mgraphctl.errors import UsageError
from mgraphctl.graph import mail, mailbox
from mgraphctl.html import to_markdown
from mgraphctl.http import GraphClient
from mgraphctl.render import (
    DryRunResult,
    ListResult,
    ObjectResult,
    Window,
    WriteResult,
    fmt_dtz,
    parse_dt,
)

app = make_noun_app("Mailbox settings, automatic replies, focused inbox.")
oof = make_noun_app("Automatic replies (out of office).")
app.add_typer(oof, name="oof")


def _working_hours(settings: dict) -> str:
    """`Mon,Tue,Wed,Thu,Fri 08:00-17:00 (Europe/Warsaw)`, or "" when Graph sent nothing."""
    hours = settings.get("workingHours") or {}
    days = hours.get("daysOfWeek") or []
    if not days:
        return ""
    zone = (hours.get("timeZone") or {}).get("name") or ""
    labels = ",".join(str(day)[:3].capitalize() for day in days)
    start = str(hours.get("startTime") or "")[:5]
    end = str(hours.get("endTime") or "")[:5]
    return f"{labels} {start}-{end} ({zone})"


OOF_MESSAGES = (
    ("Internal reply", "internalReplyMessage"),
    ("External reply", "externalReplyMessage"),
)


def _oof_body(setting: dict) -> str | None:
    """The reply messages as text, one labelled block each."""
    blocks = [
        f"{label}\n{to_markdown(setting[key], 'mail')}"
        for label, key in OOF_MESSAGES
        if setting.get(key)
    ]
    return "\n\n".join(blocks) if blocks else None


@app.command("settings")
@graph_command(scopes=["MailboxSettings.Read"])
def settings(client: GraphClient, json_: JsonFlag = False):
    """Show the mailbox's time zone, language, working hours and reply status."""
    obj = mailbox.get_settings(client)
    return ObjectResult(
        obj=obj,
        fields=[
            ("Time zone", "timeZone"),
            ("Language", "language.displayName"),
            ("Working hours", _working_hours),
            ("Automatic replies", "automaticRepliesSetting.status"),
            ("Date format", "dateFormat"),
            ("Time format", "timeFormat"),
        ],
    )


@oof.command("get")
@graph_command(scopes=["MailboxSettings.Read"])
def oof_get(client: GraphClient, json_: JsonFlag = False):
    """Show the automatic replies setting."""
    setting = mailbox.get_oof(client)
    tz = client.tz
    return ObjectResult(
        obj=setting,
        fields=[
            ("Status", "status"),
            ("External audience", "externalAudience"),
            ("Start", lambda s: fmt_dtz(s.get("scheduledStartDateTime"), tz)),
            ("End", lambda s: fmt_dtz(s.get("scheduledEndDateTime"), tz)),
        ],
        body=_oof_body(setting),
    )


@oof.command("set")
@graph_command(scopes=["MailboxSettings.ReadWrite"])
def oof_set(
    client: GraphClient,
    message: Annotated[str | None, typer.Option("--message", help="Internal reply text.")] = None,
    external_message: Annotated[
        str | None, typer.Option("--external-message", help="External reply (default: --message).")
    ] = None,
    start: Annotated[str | None, typer.Option("--start", help="Start of the period.")] = None,
    end: Annotated[str | None, typer.Option("--end", help="End of the period.")] = None,
    external: Annotated[
        str | None,
        typer.Option("--external", help="Who outside sees a reply: all, contacts, none."),
    ] = None,
    internal_only: Annotated[
        bool, typer.Option("--internal-only", help="Same as --external none.")
    ] = False,
    clear: Annotated[bool, typer.Option("--clear", help="Turn automatic replies off.")] = False,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Turn automatic replies on (always or for a period) or off."""
    tz = client.tz
    if not clear and not message:
        raise UsageError("USAGE", "--message is required unless --clear is given")
    if (start is None) != (end is None):
        raise UsageError("USAGE", "--start and --end go together; give both or neither")
    if external is not None and external not in mailbox.AUDIENCE:
        raise UsageError(
            "USAGE",
            f"--external must be one of {', '.join(mailbox.AUDIENCE)} (got {external!r})",
        )
    if internal_only and external not in (None, "none"):
        raise UsageError("USAGE", "--internal-only and --external are mutually exclusive")
    audience = "none" if internal_only else mailbox.AUDIENCE[external or "all"]
    plan = mailbox.plan_set_oof(
        client,
        message=message,
        external_message=external_message,
        start=parse_dt(start, tz) if start else None,
        end=parse_dt(end, tz, end_of_day=True) if end else None,
        audience=audience,
        clear=clear,
        tz=tz,
    )
    if dry_run:
        return DryRunResult(plan)
    updated = mail.run_plan(client, plan)[0]
    return WriteResult(obj=updated, message="Automatic replies updated.")


@app.command("focused")
@graph_command(scopes=["Mail.Read"])
def focused(
    client: GraphClient,
    other: Annotated[
        bool, typer.Option("--other", help="Show the Other inbox instead of Focused.")
    ] = False,
    after: Annotated[
        str, typer.Option("--after", help="Only messages received after this.")
    ] = "-30d",
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List Focused (or Other) inbox messages, newest first."""
    limit, all_ = page_bounds(limit, all_, default=25)
    tz = client.tz
    after_dt = parse_dt(after, tz)
    page = mailbox.list_focused(client, other=other, after=after_dt, limit=limit, all_=all_)
    return ListResult(
        items=page.items,
        page=page,
        window=Window(after=after_dt),
        hit_cap=mail.CAP_LIST if all_ else None,
        columns=mail.message_columns(tz),
    )
