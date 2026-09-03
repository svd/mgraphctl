"""Graph operations for Outlook calendar (spec §8.4).

Pure: client and parameters in, Graph dicts / PageResult / Plan out.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from mgraphctl import odata
from mgraphctl.http import JSON_HEADERS, GraphClient, PageResult, Plan, PlannedRequest
from mgraphctl.render import fmt_person, iso_duration, to_graph_dtz, to_iso_offset
from mgraphctl.resolve import looks_like_id, pick_unique, split_id_prefix

LIST_SELECT = (
    "id,subject,start,end,location,organizer,attendees,isOnlineMeeting,onlineMeeting,"
    "isCancelled,isAllDay,showAs,responseStatus,seriesMasterId,bodyPreview,webLink"
)
PAGE_LIST, CAP_LIST = 50, 200

CALENDARS_SELECT = "id,name,isDefaultCalendar,canEdit,owner,color"
PAGE_CALENDARS, CAP_CALENDARS = 100, 500

RESPOND_ENDPOINTS = {"accept": "accept", "decline": "decline", "tentative": "tentativelyAccept"}
RESPOND_STATUS = {
    "accept": "accepted",
    "decline": "declined",
    "tentative": "tentativelyAccepted",
}


# --------------------------------------------------------------------------- resolution


def list_calendars(client: GraphClient) -> list[dict]:
    """Every calendar the signed-in user has, id and display fields only."""
    return client.paginate(
        "/me/calendars",
        params={"$select": CALENDARS_SELECT},
        limit=None,
        all_=True,
        cap=CAP_CALENDARS,
        page_size=PAGE_CALENDARS,
    ).items


def resolve_calendar(client: GraphClient, value: str | None) -> str | None:
    """`--calendar` resolution (spec §6.6): an id, or a case-insensitive name in /me/calendars.

    `None` (no `--calendar` given) resolves to `None`, meaning "use the default calendar".
    """
    if value is None:
        return None
    bare, forced = split_id_prefix(value)
    if forced or looks_like_id(value, "calendar"):
        return bare
    calendars = list_calendars(client)
    return pick_unique(calendars, "name", value, what="calendar")["id"]


# --------------------------------------------------------------------------- list / get


def flags(event: dict) -> str:
    """`T` for an online meeting, `X` for a cancelled event (spec §8.4 `list` Notes)."""
    marks = []
    if event.get("isOnlineMeeting"):
        marks.append("T")
    if event.get("isCancelled"):
        marks.append("X")
    return "".join(marks)


def _search_haystack(event: dict) -> str:
    parts = [event.get("subject") or ""]
    organizer = (event.get("organizer") or {}).get("emailAddress") or {}
    parts += [organizer.get("name") or "", organizer.get("address") or ""]
    for attendee in event.get("attendees") or []:
        email = attendee.get("emailAddress") or {}
        parts += [email.get("name") or "", email.get("address") or ""]
    return " ".join(parts).casefold()


def filter_search(items: list[dict], term: str) -> list[dict]:
    """Client-side `--search`: keep events whose subject/organizer/attendees contain `term`."""
    needle = term.casefold()
    return [event for event in items if needle in _search_haystack(event)]


def calendar_view(
    client: GraphClient,
    *,
    start: datetime,
    end: datetime,
    calendar_id: str | None,
    select: str | None,
    limit: int | None,
    all_: bool,
    tz: str,
) -> PageResult:
    """`calendar list` (spec §8.4): a `calendarView` window, default or a named calendar."""
    path = (
        "/me/calendarView"
        if calendar_id is None
        else odata.p("me", "calendars", calendar_id, "calendarView")
    )
    params = {
        "startDateTime": to_iso_offset(start),
        "endDateTime": to_iso_offset(end),
        "$select": select or LIST_SELECT,
        "$orderby": "start/dateTime",
    }
    return client.paginate(
        path,
        params=params,
        outlook_tz=True,
        limit=limit,
        all_=all_,
        cap=CAP_LIST,
        page_size=PAGE_LIST,
    )


def get_event(client: GraphClient, event_id: str, *, html: bool, tz: str) -> dict:
    """`calendar get` (spec §8.4): the full event, text body unless `--html`."""
    return client.get(odata.p("me", "events", event_id), outlook_tz=True, text_body=not html)


def attendees_block(event: dict) -> str:
    """`Attendees` section for `calendar get` text output: one `Name <addr> (status)` per line."""
    lines = ["Attendees"]
    for attendee in event.get("attendees") or []:
        status = (attendee.get("status") or {}).get("response") or "none"
        lines.append(f"  {fmt_person(attendee)} ({status})")
    return "\n".join(lines)


# --------------------------------------------------------------------------- create / update


@dataclass
class EventParams:
    """The options every event write verb shares (spec §8.4 `create`/`update`)."""

    subject: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    duration: timedelta | None = None
    all_day: bool | None = None
    attendees: list[str] = field(default_factory=list)
    optional: list[str] = field(default_factory=list)
    body: str | None = None
    html: bool = False
    location: str | None = None
    teams: bool | None = None
    reminder: int | None = None
    show_as: str | None = None
    categories: list[str] = field(default_factory=list)
    calendar: str | None = None
    transaction_id: str | None = None


def event_body(p: EventParams, tz: str, *, partial: bool) -> dict:
    """The JSON body for `create` (`partial=False`) or `update` (`partial=True`, given fields)."""
    body: dict[str, Any] = {}
    if p.subject is not None:
        body["subject"] = p.subject
    if p.start is not None:
        body["start"] = to_graph_dtz(p.start, tz)
    end_dt: datetime | None = None
    if p.end is not None:
        end_dt = p.end
    elif p.start is not None and p.duration is not None:
        end_dt = p.start + p.duration
    elif p.start is not None and p.all_day:
        end_dt = p.start + timedelta(days=1)
    if end_dt is not None:
        body["end"] = to_graph_dtz(end_dt, tz)
    if not partial:
        body["isAllDay"] = bool(p.all_day)
    elif p.all_day is not None:
        body["isAllDay"] = p.all_day
    attendees = [{"emailAddress": {"address": a}, "type": "required"} for a in p.attendees]
    attendees += [{"emailAddress": {"address": a}, "type": "optional"} for a in p.optional]
    if attendees:
        body["attendees"] = attendees
    if p.body is not None:
        body["body"] = {"contentType": "HTML" if p.html else "Text", "content": p.body}
    if p.location is not None:
        body["location"] = {"displayName": p.location}
    if p.teams is not None:
        body["isOnlineMeeting"] = p.teams
        if p.teams:
            body["onlineMeetingProvider"] = "teamsForBusiness"
    if p.reminder is not None:
        body["reminderMinutesBeforeStart"] = p.reminder
    if p.show_as is not None:
        body["showAs"] = p.show_as
    if p.categories:
        body["categories"] = list(p.categories)
    if not partial:
        body["transactionId"] = p.transaction_id or str(uuid.uuid4())
    return body


def plan_create(client: GraphClient, p: EventParams, tz: str) -> Plan:
    body = event_body(p, tz, partial=False)
    path = "/me/events" if p.calendar is None else odata.p("me", "calendars", p.calendar, "events")
    return [PlannedRequest("POST", client.url(path), dict(JSON_HEADERS), body)]


def plan_update(client: GraphClient, event_id: str, p: EventParams, tz: str) -> Plan:
    body = event_body(p, tz, partial=True)
    url = client.url(odata.p("me", "events", event_id))
    return [PlannedRequest("PATCH", url, dict(JSON_HEADERS), body)]


def plan_delete(client: GraphClient, event_id: str) -> Plan:
    url = client.url(odata.p("me", "events", event_id))
    return [PlannedRequest("DELETE", url, {}, None, expect="none")]


def plan_respond(
    client: GraphClient,
    event_id: str,
    action: str,
    *,
    comment: str | None,
    send: bool,
    propose: tuple[datetime, datetime] | None,
    tz: str,
) -> Plan:
    endpoint = RESPOND_ENDPOINTS[action]
    body: dict[str, Any] = {"sendResponse": send}
    if comment is not None:
        body["comment"] = comment
    if propose is not None:
        start, end = propose
        body["proposedNewTime"] = {"start": to_graph_dtz(start, tz), "end": to_graph_dtz(end, tz)}
    url = client.url(odata.p("me", "events", event_id, endpoint))
    return [PlannedRequest("POST", url, dict(JSON_HEADERS), body)]


def run_plan(client: GraphClient, plan: Plan) -> list:
    """Execute a plan whose steps are independent (no ids threaded between them)."""
    return [client.execute(step) for step in plan]


# --------------------------------------------------------------------------- availability


def get_schedule(
    client: GraphClient, *, users: list[str], start: datetime, end: datetime, interval: int, tz: str
) -> dict:
    """`calendar availability` (spec §8.4): `getSchedule` for one or more mailboxes."""
    body = {
        "schedules": list(users),
        "startTime": to_graph_dtz(start, tz),
        "endTime": to_graph_dtz(end, tz),
        "availabilityViewInterval": interval,
    }
    return client.post("/me/calendar/getSchedule", json=body)


def free_windows(
    schedule_item: dict, start: datetime, interval: int
) -> list[tuple[datetime, datetime]]:
    """Free windows from `availabilityView` (`0` = free), merging consecutive free slots."""
    view = schedule_item.get("availabilityView") or ""
    windows: list[tuple[datetime, datetime]] = []
    slot_start: datetime | None = None
    for i, ch in enumerate(view):
        slot_time = start + timedelta(minutes=interval * i)
        if ch == "0":
            if slot_start is None:
                slot_start = slot_time
        elif slot_start is not None:
            windows.append((slot_start, slot_time))
            slot_start = None
    if slot_start is not None:
        windows.append((slot_start, start + timedelta(minutes=interval * len(view))))
    return windows


def find_times(
    client: GraphClient,
    *,
    attendees: list[str],
    duration: timedelta,
    start: datetime,
    end: datetime,
    max_candidates: int,
    domain: str,
    tz: str,
) -> dict:
    """`calendar find-times` (spec §8.4): `findMeetingTimes`."""
    body = {
        "attendees": [{"emailAddress": {"address": a}, "type": "required"} for a in attendees],
        "timeConstraint": {
            "activityDomain": domain,
            "timeSlots": [{"start": to_graph_dtz(start, tz), "end": to_graph_dtz(end, tz)}],
        },
        "meetingDuration": iso_duration(duration),
        "maxCandidates": max_candidates,
        "returnSuggestionReasons": True,
    }
    return client.post("/me/findMeetingTimes", json=body)
