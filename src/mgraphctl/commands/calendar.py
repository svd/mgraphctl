"""Outlook calendar commands (spec §8.4)."""

from datetime import timedelta
from typing import Annotated

import typer

from mgraphctl import html as html_mod
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
from mgraphctl.graph import calendar as calendar_mod
from mgraphctl.graph import users as users_mod
from mgraphctl.http import GraphClient
from mgraphctl.render import (
    Column,
    DryRunResult,
    ListResult,
    ObjectResult,
    TextResult,
    Window,
    WriteResult,
    fmt_dtz,
    fmt_event_time,
    fmt_person,
    parse_dt,
    parse_duration,
    truncate,
)

app = make_noun_app("Calendar events, availability, meeting times.")

SHOW_AS_VALUES = frozenset({"free", "tentative", "busy", "oof", "workingElsewhere"})
DOMAIN_VALUES = frozenset({"work", "personal", "unrestricted"})


def _end_short(full: str) -> str:
    """The `HH:MM` portion of an `fmt_dtz` string, for a same-line "start – end" pair."""
    return full[11:16] if len(full) > 16 else full


def _validate_show_as(show_as: str | None) -> None:
    if show_as is not None and show_as not in SHOW_AS_VALUES:
        raise UsageError("USAGE", f"--show-as must be one of {', '.join(sorted(SHOW_AS_VALUES))}")


def _fmt_owner(owner: dict | None) -> str:
    """A calendar's `owner` is a plain `{name, address}` EmailAddress, not a Recipient."""
    if not owner:
        return ""
    name, address = owner.get("name"), owner.get("address")
    if name and address:
        return f"{name} <{address}>"
    return address or name or ""


# ------------------------------------------------------------ list / calendars / get


@app.command("list")
@graph_command(scopes=["Calendars.Read"])
def list_(
    client: GraphClient,
    start: Annotated[
        str | None, typer.Option("--start", "--after", help="Window start (default: now).")
    ] = None,
    end: Annotated[
        str | None, typer.Option("--end", "--before", help="Window end (default: --days out).")
    ] = None,
    days: Annotated[
        int | None, typer.Option("--days", help="Days from --start (default 7).")
    ] = None,
    calendar: Annotated[str | None, typer.Option("--calendar", help="Calendar name or id.")] = None,
    search: Annotated[
        str | None, typer.Option("--search", help="Client-side match on subject/attendees.")
    ] = None,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List events in a time window (default: the next 7 days)."""
    limit, all_ = page_bounds(limit, all_, default=50)
    if days is not None and (start is not None or end is not None):
        raise UsageError("USAGE", "--days cannot be combined with --start or --end")
    tz = client.tz
    start_dt = parse_dt(start, tz) if start is not None else parse_dt("now", tz)
    if end is not None:
        end_dt = parse_dt(end, tz, end_of_day=True)
    else:
        end_dt = start_dt + timedelta(days=days if days is not None else 7)
    calendar_id = calendar_mod.resolve_calendar(client, calendar)
    page = calendar_mod.calendar_view(
        client,
        start=start_dt,
        end=end_dt,
        calendar_id=calendar_id,
        select=None,
        limit=limit,
        all_=all_,
        tz=tz,
    )
    items = calendar_mod.filter_search(page.items, search) if search else page.items
    return ListResult(
        items=items,
        page=page,
        window=Window(after=start_dt, before=end_dt),
        hit_cap=calendar_mod.CAP_LIST if all_ else None,
        columns=[
            Column("start", lambda e: fmt_event_time(e, "start", tz)),
            Column("end", lambda e: fmt_event_time(e, "end", tz)),
            Column("flags", calendar_mod.flags),
            Column("subject", lambda e: truncate(e.get("subject"))),
            Column("organizer", lambda e: fmt_person(e.get("organizer"))),
            Column("location", lambda e: truncate((e.get("location") or {}).get("displayName"))),
            Column("id", "id"),
        ],
    )


@app.command("calendars")
@graph_command(scopes=["Calendars.Read"])
def calendars(client: GraphClient, json_: JsonFlag = False):
    """List the signed-in user's calendars."""
    items = calendar_mod.list_calendars(client)
    return ListResult(
        items=items,
        columns=[
            Column("id", "id"),
            Column("name", "name"),
            Column("default", lambda c: "yes" if c.get("isDefaultCalendar") else ""),
            Column("editable", lambda c: "yes" if c.get("canEdit") else ""),
            Column("owner", lambda c: _fmt_owner(c.get("owner"))),
            Column("color", "color"),
        ],
    )


@app.command("get")
@graph_command(scopes=["Calendars.Read"])
def get(
    client: GraphClient,
    event_id: Annotated[str, typer.Argument(metavar="ID")],
    html: Annotated[bool, typer.Option("--html")] = False,
    json_: JsonFlag = False,
):
    """Show one event, with attendee response status and any Teams join URL."""
    tz = client.tz
    event = calendar_mod.get_event(client, event_id, html=html, tz=tz)
    fields = [
        ("Subject", lambda e: e.get("subject") or ""),
        ("Start", lambda e: fmt_event_time(e, "start", tz)),
        ("End", lambda e: fmt_event_time(e, "end", tz)),
        ("Location", lambda e: (e.get("location") or {}).get("displayName") or ""),
        ("Organizer", lambda e: fmt_person(e.get("organizer"))),
        ("Show as", lambda e: e.get("showAs") or ""),
        ("Id", "id"),
    ]
    sections = [calendar_mod.attendees_block(event)]
    join_url = (event.get("onlineMeeting") or {}).get("joinUrl")
    if join_url:
        sections.append(f"Join URL: {join_url}")
    body_obj = event.get("body") or {}
    content = body_obj.get("content")
    if content:
        is_html = (body_obj.get("contentType") or "").lower() == "html"
        sections.append(html_mod.to_markdown(content, "mail") if is_html and not html else content)
    return ObjectResult(obj=event, fields=fields, body="\n\n".join(sections))


# ------------------------------------------------------------ create / update / delete / respond


def _resolve_window(start: str | None, end: str | None, duration: str | None, tz: str) -> tuple:
    if end is not None and duration is not None:
        raise UsageError("USAGE", "--end and --duration are mutually exclusive")
    start_dt = parse_dt(start, tz) if start is not None else None
    end_dt = parse_dt(end, tz) if end is not None else None
    dur_td = parse_duration(duration) if duration is not None else None
    return start_dt, end_dt, dur_td


@app.command("create")
@graph_command(scopes=["Calendars.ReadWrite"])
def create(
    client: GraphClient,
    subject: Annotated[str, typer.Option("--subject", help="Event title.")],
    start: Annotated[str, typer.Option("--start", help="Start date/time.")],
    end: Annotated[str | None, typer.Option("--end", help="End date/time.")] = None,
    duration: Annotated[str | None, typer.Option("--duration", help="30m, 2h, 1d.")] = None,
    all_day: Annotated[bool | None, typer.Option("--all-day/--no-all-day")] = None,
    attendees: Annotated[
        list[str] | None, typer.Option("--attendees", help="Required attendee (repeatable).")
    ] = None,
    optional: Annotated[
        list[str] | None, typer.Option("--optional", help="Optional attendee (repeatable).")
    ] = None,
    body: Annotated[str | None, typer.Option("--body")] = None,
    html: Annotated[bool, typer.Option("--html")] = False,
    location: Annotated[str | None, typer.Option("--location")] = None,
    teams: Annotated[bool | None, typer.Option("--teams/--no-teams")] = None,
    reminder: Annotated[
        int | None, typer.Option("--reminder", help="Minutes before start.")
    ] = None,
    show_as: Annotated[str | None, typer.Option("--show-as")] = None,
    category: Annotated[
        list[str] | None, typer.Option("--category", help="Category (repeatable).")
    ] = None,
    calendar: Annotated[str | None, typer.Option("--calendar", help="Calendar name or id.")] = None,
    transaction_id: Annotated[str | None, typer.Option("--transaction-id", hidden=True)] = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Create a calendar event."""
    _validate_show_as(show_as)
    tz = client.tz
    start_dt, end_dt, dur_td = _resolve_window(start, end, duration, tz)
    if not all_day and end_dt is None and dur_td is None:
        dur_td = timedelta(minutes=30)
    calendar_id = calendar_mod.resolve_calendar(client, calendar)
    params = calendar_mod.EventParams(
        subject=subject,
        start=start_dt,
        end=end_dt,
        duration=dur_td,
        all_day=all_day,
        attendees=attendees or [],
        optional=optional or [],
        body=body,
        html=html,
        location=location,
        teams=teams,
        reminder=reminder,
        show_as=show_as,
        categories=category or [],
        calendar=calendar_id,
        transaction_id=transaction_id,
    )
    plan = calendar_mod.plan_create(client, params, tz)
    if dry_run:
        return DryRunResult(plan)
    event = calendar_mod.run_plan(client, plan)[0]
    message = (
        f"Created {event.get('subject')} {fmt_event_time(event, 'start', tz)} id: {event.get('id')}"
    )
    join_url = (event.get("onlineMeeting") or {}).get("joinUrl")
    if join_url:
        message += f"\nJoin URL: {join_url}"
    return WriteResult(obj=event, message=message)


@app.command("update")
@graph_command(scopes=["Calendars.ReadWrite"])
def update(
    client: GraphClient,
    event_id: Annotated[str, typer.Argument(metavar="ID")],
    subject: Annotated[str | None, typer.Option("--subject")] = None,
    start: Annotated[str | None, typer.Option("--start")] = None,
    end: Annotated[str | None, typer.Option("--end")] = None,
    duration: Annotated[str | None, typer.Option("--duration")] = None,
    all_day: Annotated[bool | None, typer.Option("--all-day/--no-all-day")] = None,
    attendees: Annotated[list[str] | None, typer.Option("--attendees")] = None,
    optional: Annotated[list[str] | None, typer.Option("--optional")] = None,
    body: Annotated[str | None, typer.Option("--body")] = None,
    html: Annotated[bool, typer.Option("--html")] = False,
    location: Annotated[str | None, typer.Option("--location")] = None,
    teams: Annotated[bool | None, typer.Option("--teams/--no-teams")] = None,
    reminder: Annotated[int | None, typer.Option("--reminder")] = None,
    show_as: Annotated[str | None, typer.Option("--show-as")] = None,
    category: Annotated[list[str] | None, typer.Option("--category")] = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Update a calendar event; only the given fields change.

    Any `create` option except --calendar (Graph cannot move an event between calendars).
    """
    _validate_show_as(show_as)
    tz = client.tz
    start_dt, end_dt, dur_td = _resolve_window(start, end, duration, tz)
    params = calendar_mod.EventParams(
        subject=subject,
        start=start_dt,
        end=end_dt,
        duration=dur_td,
        all_day=all_day,
        attendees=attendees or [],
        optional=optional or [],
        body=body,
        html=html,
        location=location,
        teams=teams,
        reminder=reminder,
        show_as=show_as,
        categories=category or [],
    )
    plan = calendar_mod.plan_update(client, event_id, params, tz)
    if dry_run:
        return DryRunResult(plan)
    event = calendar_mod.run_plan(client, plan)[0]
    return WriteResult(obj=event, message=f"Updated {event_id}.")


@app.command("delete")
@graph_command(scopes=["Calendars.ReadWrite"])
def delete(
    client: GraphClient,
    event_id: Annotated[str, typer.Argument(metavar="ID")],
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Delete (cancel) a calendar event."""
    plan = calendar_mod.plan_delete(client, event_id)
    if dry_run:
        return DryRunResult(plan)
    calendar_mod.run_plan(client, plan)
    return WriteResult(obj={"status": "deleted", "id": event_id}, message=f"Deleted {event_id}.")


@app.command("respond")
@graph_command(scopes=["Calendars.ReadWrite"])
def respond(
    client: GraphClient,
    event_id: Annotated[str, typer.Argument(metavar="ID")],
    action: Annotated[str, typer.Argument(metavar="accept|decline|tentative")],
    comment: Annotated[str | None, typer.Option("--comment")] = None,
    send: Annotated[bool, typer.Option("--send/--no-send")] = True,
    propose_start: Annotated[str | None, typer.Option("--propose-start")] = None,
    propose_end: Annotated[str | None, typer.Option("--propose-end")] = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Accept, decline or tentatively accept an event invitation."""
    action = action.lower()
    if action not in calendar_mod.RESPOND_ENDPOINTS:
        raise UsageError("USAGE", "ACTION must be accept, decline or tentative")
    if (propose_start is None) != (propose_end is None):
        raise UsageError("USAGE", "--propose-start and --propose-end must be given together")
    if propose_start is not None and action == "accept":
        raise UsageError(
            "USAGE", "--propose-start/--propose-end are only valid with decline or tentative"
        )
    tz = client.tz
    propose = None
    if propose_start is not None:
        propose = (parse_dt(propose_start, tz), parse_dt(propose_end, tz))
    plan = calendar_mod.plan_respond(
        client, event_id, action, comment=comment, send=send, propose=propose, tz=tz
    )
    if dry_run:
        return DryRunResult(plan)
    calendar_mod.run_plan(client, plan)
    status = calendar_mod.RESPOND_STATUS[action]
    return WriteResult(obj={"status": status}, message=f"{status.capitalize()}.")


# ------------------------------------------------------------ availability / find-times


def _floor(dt, interval: int):
    minutes = dt.hour * 60 + dt.minute
    floored = minutes - (minutes % interval)
    return dt.replace(hour=floored // 60, minute=floored % 60, second=0, microsecond=0)


def _availability_text(schedules: list[dict], start, interval: int, tz: str) -> str:
    lines: list[str] = []
    for item in schedules:
        lines.append(item.get("scheduleId") or "")
        for entry in item.get("scheduleItems") or []:
            status = entry.get("status") or ""
            start_full = fmt_dtz(entry.get("start"), tz)
            end_full = fmt_dtz(entry.get("end"), tz)
            subject = entry.get("subject")
            line = f"  {status} {start_full} – {_end_short(end_full)}"
            if subject:
                line += f" {subject}"
            lines.append(line)
        for window_start, window_end in calendar_mod.free_windows(item, start, interval):
            lines.append(
                f"  free {window_start.strftime('%H:%M')} – {window_end.strftime('%H:%M')}"
            )
    return "\n".join(lines)


@app.command("availability")
@graph_command(scopes=["Calendars.Read"])
def availability(
    client: GraphClient,
    users: Annotated[
        list[str] | None, typer.Option("--users", help="Mailbox (repeatable, default: me).")
    ] = None,
    start: Annotated[str | None, typer.Option("--start")] = None,
    end: Annotated[str | None, typer.Option("--end")] = None,
    interval: Annotated[
        int, typer.Option("--interval", min=5, max=1440, help="Minutes per slot.")
    ] = 30,
    json_: JsonFlag = False,
):
    """Free/busy for one or more mailboxes over a window."""
    tz = client.tz
    if users:
        emails = list(users)
    else:
        me = users_mod.get_me(client, select="mail,userPrincipalName")
        emails = [me.get("mail") or me.get("userPrincipalName")]
    start_dt = parse_dt(start, tz) if start is not None else _floor(parse_dt("now", tz), interval)
    end_dt = (
        parse_dt(end, tz, end_of_day=True)
        if end is not None
        else parse_dt("today", tz, end_of_day=True)
    )
    result = calendar_mod.get_schedule(
        client, users=emails, start=start_dt, end=end_dt, interval=interval, tz=tz
    )
    schedules = result.get("value") or []
    text = _availability_text(schedules, start_dt, interval, tz)
    envelope = {
        "items": schedules,
        "count": len(schedules),
        "fetched": len(schedules),
        # getSchedule returns one entry per mailbox asked for; nothing is capped or paged.
        "cap": None,
        "truncated": False,
        "window": Window(after=start_dt, before=end_dt).to_json(),
    }
    return TextResult(text=text, json_obj=envelope)


def _format_find_times(result: dict, tz: str) -> str:
    lines: list[str] = []
    reason = result.get("emptySuggestionsReason")
    if reason:
        lines.append(f"No suggestions: {reason}")
    for i, suggestion in enumerate(result.get("meetingTimeSuggestions") or [], 1):
        slot = suggestion.get("meetingTimeSlot") or {}
        start_full = fmt_dtz(slot.get("start"), tz)
        end_full = fmt_dtz(slot.get("end"), tz)
        confidence = suggestion.get("confidence")
        lines.append(f"{i}. {start_full} – {_end_short(end_full)}  confidence: {confidence}")
        for entry in suggestion.get("attendeeAvailability") or []:
            address = ((entry.get("attendee") or {}).get("emailAddress") or {}).get("address", "")
            lines.append(f"     {address}: {entry.get('availability')}")
    if not lines:
        lines.append("No suggestions.")
    return "\n".join(lines)


@app.command("find-times")
@graph_command(scopes=["Calendars.Read.Shared"])
def find_times(
    client: GraphClient,
    attendees: Annotated[
        list[str] | None, typer.Option("--attendees", help="Required attendee (repeatable).")
    ] = None,
    duration: Annotated[str, typer.Option("--duration")] = "30m",
    start: Annotated[str | None, typer.Option("--start")] = None,
    end: Annotated[str | None, typer.Option("--end")] = None,
    max_: Annotated[int, typer.Option("--max", help="Maximum candidates.")] = 5,
    domain: Annotated[str, typer.Option("--domain")] = "work",
    json_: JsonFlag = False,
):
    """Suggest meeting times for a set of attendees."""
    if not attendees:
        raise UsageError("USAGE", "--attendees needs at least one address")
    if domain not in DOMAIN_VALUES:
        raise UsageError("USAGE", f"--domain must be one of {', '.join(sorted(DOMAIN_VALUES))}")
    tz = client.tz
    start_dt = parse_dt(start, tz) if start is not None else parse_dt("now", tz)
    end_dt = parse_dt(end, tz, end_of_day=True) if end is not None else start_dt + timedelta(days=7)
    dur_td = parse_duration(duration)
    result = calendar_mod.find_times(
        client,
        attendees=attendees,
        duration=dur_td,
        start=start_dt,
        end=end_dt,
        max_candidates=max_,
        domain=domain,
        tz=tz,
    )
    # `findMeetingTimes` answers with its own object, not a listing; the window is added so a
    # consumer can still report what was asked for (spec §6.2).
    payload = {**result, "window": Window(after=start_dt, before=end_dt).to_json()}
    return TextResult(text=_format_find_times(result, tz), json_obj=payload)
