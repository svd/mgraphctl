"""Graph operations for online meetings, transcripts and AI insights (spec §8.10).

Pure: client and parameters in, Graph dicts / lists out. `meetings list` resolves its own
calendar window (its own `$select`, no import of `graph/calendar` — that module is owned by
a different task and this one must not depend on it).
"""

from __future__ import annotations

from datetime import datetime

from mgraphctl import odata
from mgraphctl.errors import NotFoundError, UsageError
from mgraphctl.http import BatchRequest, GraphClient
from mgraphctl.render import to_iso_offset

EVENT_SELECT = "id,subject,start,end,organizer,isOnlineMeeting,onlineMeeting"
PAGE_SIZE = 50
CAP = 200


def list_online_events(
    client: GraphClient,
    *,
    start: datetime,
    end: datetime,
    subject: str | None,
    limit: int,
    tz: str,
) -> list[dict]:
    """Calendar events in `[start, end]` that are online meetings with a join URL."""
    params = {
        "startDateTime": to_iso_offset(start),
        "endDateTime": to_iso_offset(end),
        "$select": EVENT_SELECT,
    }
    page = client.paginate(
        "/me/calendarView",
        params=params,
        outlook_tz=True,
        limit=limit,
        all_=False,
        cap=CAP,
        page_size=PAGE_SIZE,
    )
    events = [
        e
        for e in page.items
        if e.get("isOnlineMeeting") and (e.get("onlineMeeting") or {}).get("joinUrl")
    ]
    if subject:
        needle = subject.casefold()
        events = [e for e in events if needle in (e.get("subject") or "").casefold()]
    return events


def resolve_meetings(client: GraphClient, events: list[dict]) -> dict[str, dict]:
    """`$batch` of one `onlineMeetings` join-URL filter per event; keyed by event id."""
    targets = [e for e in events if (e.get("onlineMeeting") or {}).get("joinUrl")]
    if not targets:
        return {}
    requests = [
        BatchRequest(
            id=event["id"],
            method="GET",
            url=odata.with_query(
                "/me/onlineMeetings",
                {"$filter": _join_url_filter(event["onlineMeeting"]["joinUrl"])},
            ),
        )
        for event in targets
    ]
    resolved: dict[str, dict] = {}
    for response in client.batch(requests):
        if response.error is not None:
            continue
        values = (response.body or {}).get("value") or []
        if values:
            resolved[response.id] = values[0]
    return resolved


def transcripts_for(client: GraphClient, meeting_ids: list[str]) -> dict[str, list]:
    """`GET /me/onlineMeetings/{id}/transcripts` for each meeting id, one call per id."""
    result: dict[str, list] = {}
    for meeting_id in meeting_ids:
        if meeting_id in result:
            continue
        page = client.get(odata.p("me", "onlineMeetings", meeting_id, "transcripts"))
        result[meeting_id] = (page or {}).get("value") or []
    return result


def _join_url_filter(join_url: str) -> str:
    return f"JoinWebUrl eq '{odata.odata_str(join_url)}'"


def _by_join_url(client: GraphClient, join_url: str) -> dict:
    result = client.get("/me/onlineMeetings", params={"$filter": _join_url_filter(join_url)})
    values = (result or {}).get("value") or []
    if not values:
        raise NotFoundError("NOT_FOUND", f"no online meeting found for join URL {join_url!r}")
    return values[0]


def select_meeting(
    client: GraphClient, meeting: str | None, join_url: str | None, event: str | None
) -> dict:
    """Resolve exactly one of MEETING / `--join-url` / `--event` to a meeting dict (spec §6.6).

    A bare `MEETING` id costs no request (`{"id": meeting}`); `--join-url` and `--event` both
    end in the `$filter` lookup, which already returns the full record.
    """
    given = [v for v in (meeting, join_url, event) if v is not None]
    if len(given) != 1:
        raise UsageError("USAGE", "give exactly one of MEETING, --join-url, or --event")
    if meeting is not None:
        return {"id": meeting}
    if event is not None:
        ev = client.get(odata.p("me", "events", event), params={"$select": "onlineMeeting"})
        join_url = (ev.get("onlineMeeting") or {}).get("joinUrl")
        if not join_url:
            raise NotFoundError("NOT_FOUND", f"event {event!r} has no online meeting")
    return _by_join_url(client, join_url)
