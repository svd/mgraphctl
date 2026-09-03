"""Online meetings, transcripts and AI insights (spec §8.10)."""

from datetime import timedelta
from pathlib import Path
from typing import Annotated

import typer

from mgraphctl import auth, render
from mgraphctl.cli import JsonFlag, LimitOpt, gate, graph_command, make_noun_app
from mgraphctl.errors import UsageError
from mgraphctl.graph import meetings
from mgraphctl.http import GraphClient
from mgraphctl.render import (
    Column,
    FileResult,
    ListResult,
    ObjectResult,
    TextResult,
    fmt_dt,
    fmt_dtz,
    fmt_size,
    truncate,
)

app = make_noun_app("Online meetings, transcripts and AI insights.")

DEFAULT_LIMIT = 50
FORMATS = ("text", "vtt")

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
    page = meetings.list_online_events(
        client, start=start_dt, end=end_dt, subject=subject, limit=bound, tz=tz
    )
    events = page.items
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
        truncated=page.truncated,
        hit_cap=bound if page.truncated else None,
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
    obj = meetings.get_meeting(client, meeting, join_url=join_url, event=event)
    return ObjectResult(obj=obj, fields=list(GET_FIELDS))


@app.command("transcripts")
@graph_command(scopes=["OnlineMeetingTranscript.Read.All"])
def transcripts(
    client: GraphClient,
    meeting: MeetingArg = None,
    join_url: JoinUrlOpt = None,
    event: EventOpt = None,
    json_: JsonFlag = False,
):
    """List the transcripts recorded for one online meeting."""
    selected = meetings.select_meeting(client, meeting, join_url, event)
    items = meetings.list_transcripts(client, selected["id"])
    tz = client.tz
    return ListResult(
        items=items,
        columns=[
            Column("id", "id"),
            Column("created", lambda t: fmt_dt(t.get("createdDateTime"), tz)),
        ],
    )


@app.command("transcript")
@graph_command(scopes=["OnlineMeetingTranscript.Read.All"])
def transcript(
    client: GraphClient,
    ids: Annotated[
        list[str] | None,
        typer.Argument(
            metavar="[MEETING] TRANSCRIPT_ID", help="The meeting id, then the transcript id."
        ),
    ] = None,
    join_url: JoinUrlOpt = None,
    event: EventOpt = None,
    fmt: Annotated[str, typer.Option("--format", help="text or vtt.")] = "text",
    output: Annotated[
        Path | None, typer.Option("--output", help="Write to this file instead of stdout.")
    ] = None,
    json_: JsonFlag = False,
):
    """Show one transcript's content."""
    tokens = ids or []
    if len(tokens) == 2:
        meeting, transcript_id = tokens
    elif len(tokens) == 1:
        meeting, transcript_id = None, tokens[0]
    else:
        raise UsageError("USAGE", "give TRANSCRIPT_ID, and MEETING or --join-url or --event")
    if fmt not in FORMATS:
        raise UsageError("USAGE", f"--format must be one of {', '.join(FORMATS)}")
    selected = meetings.select_meeting(client, meeting, join_url, event)
    meeting_id = selected["id"]
    text = meetings.get_transcript_content(client, meeting_id, transcript_id, fmt=fmt)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        size = len(text.encode("utf-8"))
        return FileResult(
            path=output,
            bytes=size,
            meta=dict(meetingId=meeting_id, transcriptId=transcript_id, format=fmt),
            message=f"Wrote the {fmt} transcript ({fmt_size(size)}) to {output}",
        )
    payload = dict(meetingId=meeting_id, transcriptId=transcript_id, format=fmt, text=text)
    return TextResult(text=text, json_obj=payload)


@app.command("insights")
@graph_command(scopes=["OnlineMeetingAiInsight.Read.All"])
def insights(
    client: GraphClient,
    meeting: MeetingArg = None,
    join_url: JoinUrlOpt = None,
    event: EventOpt = None,
    json_: JsonFlag = False,
):
    """AI-generated meeting insights (recap, action items, mentions)."""
    selected = meetings.select_meeting(client, meeting, join_url, event)
    oid = auth.my_oid()
    items, note = meetings.insights(client, oid, selected["id"])
    return ListResult(
        items=items,
        columns=[Column("id", "id"), Column("title", "title")],
        empty_text=note or "No results.",
        extra={"note": note} if note else None,
    )


@app.command("recordings")
@graph_command(scopes=["OnlineMeetingRecording.Read.All"])
def recordings(
    client: GraphClient,
    meeting: MeetingArg = None,
    join_url: JoinUrlOpt = None,
    event: EventOpt = None,
    download: Annotated[
        str | None, typer.Option("--download", metavar="RID", help="Recording id to download.")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="File to write the recording to.")
    ] = None,
    json_: JsonFlag = False,
):
    """List recordings for one online meeting, or download one."""
    selected = meetings.select_meeting(client, meeting, join_url, event)
    meeting_id = selected["id"]
    if download is not None or output is not None:
        if download is None or output is None:
            raise UsageError("USAGE", "--download and --output must be given together")
        got = meetings.download_recording(client, meeting_id, download, output)
        return FileResult(
            path=got.path,
            bytes=got.bytes,
            meta=dict(contentType=got.content_type),
            message=f"Downloaded recording ({fmt_size(got.bytes)}) to {got.path}",
        )
    items = meetings.list_recordings(client, meeting_id)
    tz = client.tz
    return ListResult(
        items=items,
        columns=[
            Column("id", "id"),
            Column("created", lambda r: fmt_dt(r.get("createdDateTime"), tz)),
        ],
    )
