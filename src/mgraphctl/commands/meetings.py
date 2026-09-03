"""Online meetings, transcripts and AI insights (spec §8.10)."""

from datetime import timedelta
from typing import Annotated

import typer

from mgraphctl import odata, render
from mgraphctl.cli import JsonFlag, LimitOpt, gate, graph_command, make_noun_app
from mgraphctl.graph import meetings
from mgraphctl.http import GraphClient
from mgraphctl.render import Column, ListResult, ObjectResult, fmt_dtz, truncate

app = make_noun_app("Online meetings, transcripts and AI insights.")

DEFAULT_LIMIT = 50

MeetingArg = Annotated[str | None, typer.Argument(metavar="MEETING", help="An online meeting id.")]
JoinUrlOpt = Annotated[
    str | None, typer.Option("--join-url", help="Select the meeting by its join URL.")
]
EventOpt = Annotated[
    str | None, typer.Option("--event", help="Select the meeting from a calendar event id.")
]

GET_FIELDS = [
    ("Meeting id", "id"),
    ("Subject", "subject"),
    ("Join URL", "joinWebUrl"),
]


def _window(start: str | None, end: str | None, tz: str) -> tuple:
    """The `[start, end]` window: explicit `--start`/`--end`, else the last 7 days (spec §8.10)."""
    start_dt = (
        render.parse_dt(start, tz) if start else render.parse_dt("today", tz) - timedelta(days=7)
    )
    end_dt = (
        render.parse_dt(end, tz, end_of_day=True)
        if end
        else render.parse_dt("today", tz, end_of_day=True)
    )
    return start_dt, end_dt


@app.command("list")
@graph_command(scopes=["Calendars.Read"])
def list_(
    client: GraphClient,
    start: Annotated[str | None, typer.Option("--start", help="Start of the window.")] = None,
    end: Annotated[str | None, typer.Option("--end", help="End of the window.")] = None,
    subject: Annotated[
        str | None, typer.Option("--subject", help="Case-insensitive subject substring.")
    ] = None,
    resolve: Annotated[
        bool, typer.Option("--resolve", help="Resolve each event to its online meeting id.")
    ] = False,
    with_transcripts: Annotated[
        bool,
        typer.Option("--with-transcripts", help="Also list transcript ids (implies --resolve)."),
    ] = False,
    limit: LimitOpt = None,
    json_: JsonFlag = False,
):
    """List calendar events that are online meetings (default window: the last 7 days)."""
    tz = client.tz
    start_dt, end_dt = _window(start, end, tz)
    bound = limit if limit is not None else DEFAULT_LIMIT
    events = meetings.list_online_events(
        client, start=start_dt, end=end_dt, subject=subject, limit=bound, tz=tz
    )
    do_resolve = resolve or with_transcripts
    resolved: dict[str, dict] = {}
    if do_resolve:
        gate(["OnlineMeetings.Read"])
        resolved = meetings.resolve_meetings(client, events)
    transcripts: dict[str, list] = {}
    if with_transcripts:
        gate(["OnlineMeetingTranscript.Read.All"])
        meeting_ids = [m["id"] for m in resolved.values() if m.get("id")]
        transcripts = meetings.transcripts_for(client, meeting_ids)
    items = []
    for event in events:
        meeting = resolved.get(event["id"])
        meeting_id = meeting.get("id") if meeting else None
        items.append(
            {
                "eventId": event.get("id"),
                "subject": event.get("subject"),
                "start": event.get("start"),
                "end": event.get("end"),
                "organizer": event.get("organizer"),
                "meetingId": meeting_id if do_resolve else None,
                "transcriptIds": (
                    [t.get("id") for t in transcripts.get(meeting_id, [])]
                    if with_transcripts and meeting_id
                    else []
                ),
            }
        )
    return ListResult(
        items=items,
        columns=[
            Column("start", lambda it: fmt_dtz(it.get("start"), tz)),
            Column("subject", lambda it: truncate(it.get("subject"))),
            Column("event_id", "eventId"),
            Column("meeting_id", "meetingId"),
            Column("transcripts", "transcriptIds"),
        ],
    )


@app.command("get")
@graph_command(scopes=["OnlineMeetings.Read"])
def get(
    client: GraphClient,
    meeting: MeetingArg = None,
    join_url: JoinUrlOpt = None,
    event: EventOpt = None,
    json_: JsonFlag = False,
):
    """Show one online meeting."""
    selected = meetings.select_meeting(client, meeting, join_url, event)
    # A bare positional id costs no request in select_meeting; fetch the full record here.
    # --join-url and --event already resolve through a $filter lookup that returns it.
    obj = (
        client.get(odata.p("me", "onlineMeetings", selected["id"]))
        if meeting is not None
        else selected
    )
    return ObjectResult(obj=obj, fields=list(GET_FIELDS))
