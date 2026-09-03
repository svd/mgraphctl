"""CLI tests for the calendar noun (spec §8.4)."""

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from helpers import GRAPH, covers, graph_error, mock_graph
from mgraphctl import render

WARSAW = ZoneInfo("Europe/Warsaw")


def _fix_now(monkeypatch, hour: int = 9, minute: int = 0) -> None:
    fixed = datetime(2026, 9, 2, hour, minute, tzinfo=WARSAW)
    monkeypatch.setattr(render, "_now", lambda zone: fixed.astimezone(zone))


# ------------------------------------------------------------ list / calendars / get


@covers("calendar list")
def test_calendar_list_window_and_columns(invoke, graph, monkeypatch):
    _fix_now(monkeypatch)
    routes = mock_graph(graph, "calendar/list")
    r = invoke("calendar", "list", "--json")
    assert r.exit_code == 0, r.stderr
    req = routes[0].calls.last.request
    assert dict(req.url.params) == {
        "startDateTime": "2026-09-02T09:00:00+02:00",
        "endDateTime": "2026-09-09T09:00:00+02:00",
        "$select": "id,subject,start,end,location,organizer,attendees,isOnlineMeeting,"
        "onlineMeeting,isCancelled,isAllDay,showAs,responseStatus,seriesMasterId,bodyPreview,"
        "webLink",
        "$orderby": "start/dateTime",
        "$top": "50",
    }
    assert req.headers["Prefer"] == 'outlook.timezone="Europe/Warsaw"'
    doc = json.loads(r.stdout)
    assert doc["count"] == 2 and doc["items"][0]["subject"] == "Standup"
    r = invoke("calendar", "list")
    assert r.stdout.splitlines()[0].split() == [
        "start",
        "end",
        "flags",
        "subject",
        "organizer",
        "location",
        "id",
    ]
    assert "T" in r.stdout.splitlines()[1].split()[2]
    assert "2026-09-03 (all day)" in r.stdout


@covers("calendar list")
def test_calendar_list_start_end_days_and_aliases(invoke, graph, monkeypatch):
    _fix_now(monkeypatch)
    route = graph.get(f"{GRAPH}/v1.0/me/calendarView").mock(
        return_value=httpx.Response(200, json={"value": []})
    )

    r = invoke("calendar", "list", "--start", "2026-09-01", "--end", "2026-09-05", "--json")
    assert r.exit_code == 0, r.stderr
    params = dict(route.calls.last.request.url.params)
    assert params["startDateTime"] == "2026-09-01T00:00:00+02:00"
    assert params["endDateTime"] == "2026-09-05T23:59:59+02:00"

    r = invoke("calendar", "list", "--days", "3", "--json")
    assert r.exit_code == 0, r.stderr
    params = dict(route.calls.last.request.url.params)
    assert params["startDateTime"] == "2026-09-02T09:00:00+02:00"
    assert params["endDateTime"] == "2026-09-05T09:00:00+02:00"

    r = invoke("calendar", "list", "--after", "2026-09-01", "--before", "2026-09-05", "--json")
    assert r.exit_code == 0, r.stderr
    params = dict(route.calls.last.request.url.params)
    assert params["startDateTime"] == "2026-09-01T00:00:00+02:00"
    assert params["endDateTime"] == "2026-09-05T23:59:59+02:00"

    r = invoke("calendar", "list", "--start", "2026-09-01", "--days", "3")
    assert r.exit_code == 2


@covers("calendar list")
def test_calendar_list_search_client_side(invoke, graph, monkeypatch):
    _fix_now(monkeypatch)
    graph.get(f"{GRAPH}/v1.0/me/calendarView").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "AAMkEvt-1001",
                        "subject": "1:1 with Ada",
                        "organizer": {
                            "emailAddress": {"name": "Bob Example", "address": "bob@example.com"}
                        },
                        "attendees": [],
                    },
                    {
                        "id": "AAMkEvt-1002",
                        "subject": "Budget Review",
                        "organizer": {
                            "emailAddress": {"name": "Cid Example", "address": "cid@example.com"}
                        },
                        "attendees": [
                            {
                                "emailAddress": {
                                    "name": "Dee Example",
                                    "address": "dee@example.com",
                                }
                            }
                        ],
                    },
                    {
                        "id": "AAMkEvt-1003",
                        "subject": "Standup",
                        "organizer": {
                            "emailAddress": {"name": "Eve Example", "address": "eve@example.com"}
                        },
                        "attendees": [
                            {
                                "emailAddress": {
                                    "name": "Ada Example",
                                    "address": "ada@example.com",
                                }
                            }
                        ],
                    },
                ]
            },
        )
    )
    r = invoke("calendar", "list", "--search", "ada", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    ids = {item["id"] for item in doc["items"]}
    assert ids == {"AAMkEvt-1001", "AAMkEvt-1003"}


@covers("calendar list")
def test_calendar_list_calendar_by_name(invoke, graph, monkeypatch):
    _fix_now(monkeypatch)
    routes = mock_graph(graph, "calendar/list_by_name")
    r = invoke("calendar", "list", "--calendar", "team calendar", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 1 and doc["items"][0]["subject"] == "Team Sync"
    assert routes[0].calls.last.request.url.path == "/v1.0/me/calendars"
    assert (
        routes[1].calls.last.request.url.path
        == "/v1.0/me/calendars/AAMkCal-team-00000000000000000000000000000000/calendarView"
    )


@covers("calendar list")
def test_calendar_list_cancelled_marker_x(invoke, graph, monkeypatch):
    _fix_now(monkeypatch)
    mock_graph(graph, "calendar/list_cancelled")
    r = invoke("calendar", "list")
    assert r.exit_code == 0, r.stderr
    lines = r.stdout.splitlines()
    assert "X" in lines[1].split()[2]


@covers("calendar list")
def test_calendar_list_all_cap_200(invoke, graph):
    mock_graph(graph, "calendar/list_all_cap")
    r = invoke(
        "calendar", "list", "--start", "2026-09-01", "--end", "2026-09-08", "--all", "--json"
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 200 and doc["truncated"] is True


@covers("calendar list")
def test_calendar_list_limit_zero_is_usage_error(invoke):
    assert invoke("calendar", "list", "--limit", "0").exit_code == 2


@covers("calendar calendars")
def test_calendar_calendars(invoke, graph):
    routes = mock_graph(graph, "calendar/calendars")
    r = invoke("calendar", "calendars", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 2 and doc["items"][0]["name"] == "Calendar"
    assert dict(routes[0].calls.last.request.url.params) == {
        "$select": "id,name,isDefaultCalendar,canEdit,owner,color",
        "$top": "100",
    }
    r = invoke("calendar", "calendars")
    assert r.exit_code == 0
    assert "Team Calendar" in r.stdout and "yes" in r.stdout


@covers("calendar get")
def test_calendar_get_text_attendees_and_join_url(invoke, graph):
    mock_graph(graph, "calendar/get")
    r = invoke("calendar", "get", "AAMkEvt-0001")
    assert r.exit_code == 0, r.stderr
    assert "Attendees" in r.stdout
    assert "Bob Example <bob@example.com> (accepted)" in r.stdout
    assert "Cid Example <cid@example.com> (tentativelyAccepted)" in r.stdout
    assert "Join URL: https://teams.microsoft.com/l/meetup-join/sprintreview" in r.stdout
    assert "**agenda**" in r.stdout

    r = invoke("calendar", "get", "AAMkEvt-0001", "--html")
    assert r.exit_code == 0, r.stderr
    assert "<b>agenda</b>" in r.stdout

    r = invoke("calendar", "get", "AAMkEvt-0001", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["id"] == "AAMkEvt-0001" and doc["body"]["content"].startswith("<p>")


@covers("calendar get")
@pytest.mark.parametrize(
    "status,code,exit_code",
    [(404, "ErrorItemNotFound", 4), (403, "ErrorAccessDenied", 3), (400, "BadRequest", 1)],
)
def test_calendar_get_error_exit_codes(invoke, graph, status, code, exit_code):
    graph.get(f"{GRAPH}/v1.0/me/events/AAMkEvt-x").mock(return_value=graph_error(status, code))
    r = invoke("calendar", "get", "AAMkEvt-x")
    assert r.exit_code == exit_code
    assert r.stdout == ""
    assert r.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("calendar get")
def test_calendar_get_401_after_refresh(invoke, graph):
    route = graph.get(f"{GRAPH}/v1.0/me/events/AAMkEvt-x").mock(
        return_value=graph_error(401, "InvalidAuthenticationToken")
    )
    r = invoke("calendar", "get", "AAMkEvt-x")
    assert r.exit_code == 3 and route.call_count == 2
    assert r.stderr.startswith("error[UNAUTHORIZED]:") and "login --force" in r.stderr


# ------------------------------------------------------------ create / update / delete / respond


@covers("calendar create")
def test_calendar_create_full_body(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/me/events").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": "AAMkEvt-2001",
                "subject": "S",
                "start": {"dateTime": "2026-09-05T14:00:00.0000000", "timeZone": "Europe/Warsaw"},
                "end": {"dateTime": "2026-09-05T14:45:00.0000000", "timeZone": "Europe/Warsaw"},
                "isAllDay": False,
                "onlineMeeting": {"joinUrl": "https://teams.microsoft.com/l/meetup-join/s"},
            },
        )
    )
    r = invoke(
        "calendar",
        "create",
        "--subject",
        "S",
        "--start",
        "2026-09-05T14:00",
        "--duration",
        "45m",
        "--attendees",
        "a@example.com",
        "--optional",
        "b@example.com",
        "--body",
        "Hi",
        "--location",
        "Room",
        "--teams",
        "--reminder",
        "10",
        "--show-as",
        "busy",
        "--category",
        "Work",
        "--category",
        "Ops",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    body = json.loads(route.calls.last.request.content)
    transaction_id = body.pop("transactionId")
    assert re.fullmatch(r"[0-9a-f-]{36}", transaction_id)
    assert body == {
        "subject": "S",
        "start": {"dateTime": "2026-09-05T14:00:00", "timeZone": "Europe/Warsaw"},
        "end": {"dateTime": "2026-09-05T14:45:00", "timeZone": "Europe/Warsaw"},
        "isAllDay": False,
        "attendees": [
            {"emailAddress": {"address": "a@example.com"}, "type": "required"},
            {"emailAddress": {"address": "b@example.com"}, "type": "optional"},
        ],
        "body": {"contentType": "Text", "content": "Hi"},
        "location": {"displayName": "Room"},
        "isOnlineMeeting": True,
        "onlineMeetingProvider": "teamsForBusiness",
        "reminderMinutesBeforeStart": 10,
        "showAs": "busy",
        "categories": ["Work", "Ops"],
    }
    doc = json.loads(r.stdout)
    assert doc["onlineMeeting"]["joinUrl"] == "https://teams.microsoft.com/l/meetup-join/s"

    r2 = invoke(
        "calendar", "create", "--subject", "S", "--start", "2026-09-05T14:00", "--duration", "45m"
    )
    assert r2.exit_code == 0, r2.stderr
    assert "Created S" in r2.stdout and "id: AAMkEvt-2001" in r2.stdout
    assert "Join URL: https://teams.microsoft.com/l/meetup-join/s" in r2.stdout


@covers("calendar create")
def test_calendar_create_all_day_rejects_a_start_with_a_time(invoke, graph):
    r = invoke(
        "calendar", "create", "--subject", "Offsite", "--start", "2026-09-05T09:00", "--all-day"
    )
    assert r.exit_code == 2 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[USAGE]: --all-day needs a date-only --start/--end")


@covers("calendar create")
def test_calendar_create_all_day_defaults_end(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/me/events").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": "AAMkEvt-2002",
                "subject": "Offsite",
                "start": {"dateTime": "2026-09-05T00:00:00.0000000", "timeZone": "Europe/Warsaw"},
                "isAllDay": True,
            },
        )
    )
    r = invoke(
        "calendar", "create", "--subject", "Offsite", "--start", "2026-09-05", "--all-day", "--json"
    )
    assert r.exit_code == 0, r.stderr
    body = json.loads(route.calls.last.request.content)
    assert body["end"] == {"dateTime": "2026-09-06T00:00:00", "timeZone": "Europe/Warsaw"}
    assert body["isAllDay"] is True


@covers("calendar create")
def test_calendar_create_end_and_duration_conflict_exit_2(invoke, graph):
    r = invoke(
        "calendar",
        "create",
        "--subject",
        "S",
        "--start",
        "2026-09-05T14:00",
        "--end",
        "2026-09-05T15:00",
        "--duration",
        "30m",
    )
    assert r.exit_code == 2
    assert graph.calls.call_count == 0


@covers("calendar create")
def test_calendar_create_calendar_option(invoke, graph):
    cal_id = "AAMkCal-team-00000000000000000000000000000000"
    route = graph.post(f"{GRAPH}/v1.0/me/calendars/{cal_id}/events").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": "AAMkEvt-2003",
                "subject": "S",
                "start": {"dateTime": "2026-09-05T14:00:00.0000000", "timeZone": "Europe/Warsaw"},
                "isAllDay": False,
            },
        )
    )
    r = invoke(
        "calendar",
        "create",
        "--subject",
        "S",
        "--start",
        "2026-09-05T14:00",
        "--calendar",
        cal_id,
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    assert route.called


@covers("calendar create")
def test_calendar_create_dry_run(invoke, graph):
    r = invoke(
        "calendar",
        "create",
        "--subject",
        "S",
        "--start",
        "2026-09-05T14:00",
        "--dry-run",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["dryRun"] is True
    assert doc["requests"][0]["method"] == "POST"
    assert doc["requests"][0]["url"] == f"{GRAPH}/v1.0/me/events"
    assert graph.calls.call_count == 0
    r = invoke("calendar", "create", "--subject", "S", "--start", "2026-09-05T14:00", "--dry-run")
    assert r.stdout.startswith("DRY RUN — nothing sent\n1. POST")


@covers("calendar create")
@pytest.mark.scopes(["Calendars.Read"])
def test_calendar_create_missing_scope(invoke, graph):
    r = invoke("calendar", "create", "--subject", "S", "--start", "2026-09-05T14:00")
    assert r.exit_code == 3 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[MISSING_SCOPE]:")


@covers("calendar update")
def test_calendar_update_only_given_fields(invoke, graph):
    route = graph.patch(f"{GRAPH}/v1.0/me/events/AAMkEvt-3001").mock(
        return_value=httpx.Response(200, json={"id": "AAMkEvt-3001", "subject": "New Subject"})
    )
    r = invoke("calendar", "update", "AAMkEvt-3001", "--subject", "New Subject", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(route.calls.last.request.content) == {"subject": "New Subject"}


@covers("calendar update")
def test_calendar_update_no_teams_disables_online_meeting(invoke, graph):
    route = graph.patch(f"{GRAPH}/v1.0/me/events/AAMkEvt-3002").mock(
        return_value=httpx.Response(200, json={"id": "AAMkEvt-3002"})
    )
    r = invoke("calendar", "update", "AAMkEvt-3002", "--no-teams", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(route.calls.last.request.content) == {"isOnlineMeeting": False}


@covers("calendar update")
def test_calendar_update_teams_enables_online_meeting(invoke, graph):
    route = graph.patch(f"{GRAPH}/v1.0/me/events/AAMkEvt-3003").mock(
        return_value=httpx.Response(200, json={"id": "AAMkEvt-3003"})
    )
    r = invoke("calendar", "update", "AAMkEvt-3003", "--teams", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(route.calls.last.request.content) == {
        "isOnlineMeeting": True,
        "onlineMeetingProvider": "teamsForBusiness",
    }


@covers("calendar update")
def test_calendar_update_without_teams_flag_leaves_online_meeting_untouched(invoke, graph):
    route = graph.patch(f"{GRAPH}/v1.0/me/events/AAMkEvt-3004").mock(
        return_value=httpx.Response(200, json={"id": "AAMkEvt-3004"})
    )
    r = invoke("calendar", "update", "AAMkEvt-3004", "--subject", "New", "--json")
    assert r.exit_code == 0, r.stderr
    body = json.loads(route.calls.last.request.content)
    assert "isOnlineMeeting" not in body and "onlineMeetingProvider" not in body


@covers("calendar update")
def test_calendar_update_dry_run(invoke, graph):
    r = invoke("calendar", "update", "AAMkEvt-3001", "--subject", "New", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc == {
        "dryRun": True,
        "requests": [
            {
                "method": "PATCH",
                "url": f"{GRAPH}/v1.0/me/events/AAMkEvt-3001",
                "headers": {"Content-Type": "application/json"},
                "body": {"subject": "New"},
            }
        ],
    }
    assert graph.calls.call_count == 0


@covers("calendar delete")
def test_calendar_delete(invoke, graph):
    route = graph.delete(f"{GRAPH}/v1.0/me/events/AAMkEvt-4001").mock(
        return_value=httpx.Response(204)
    )
    r = invoke("calendar", "delete", "AAMkEvt-4001", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout) == {"status": "deleted", "id": "AAMkEvt-4001"}
    assert route.called


@covers("calendar delete")
def test_calendar_delete_dry_run(invoke, graph):
    r = invoke("calendar", "delete", "AAMkEvt-4001", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["dryRun"] is True and doc["requests"][0]["method"] == "DELETE"
    assert graph.calls.call_count == 0


@covers("calendar respond")
def test_calendar_respond_accept(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/me/events/AAMkEvt-5001/accept").mock(
        return_value=httpx.Response(202)
    )
    r = invoke("calendar", "respond", "AAMkEvt-5001", "accept", "--comment", "ok", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(route.calls.last.request.content) == {"comment": "ok", "sendResponse": True}
    assert json.loads(r.stdout) == {"status": "accepted"}


@covers("calendar respond")
def test_calendar_respond_decline_no_send(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/me/events/AAMkEvt-5002/decline").mock(
        return_value=httpx.Response(202)
    )
    r = invoke("calendar", "respond", "AAMkEvt-5002", "decline", "--no-send", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(route.calls.last.request.content) == {"sendResponse": False}
    assert json.loads(r.stdout) == {"status": "declined"}


@covers("calendar respond")
def test_calendar_respond_tentative_propose(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/me/events/AAMkEvt-5003/tentativelyAccept").mock(
        return_value=httpx.Response(202)
    )
    r = invoke(
        "calendar",
        "respond",
        "AAMkEvt-5003",
        "tentative",
        "--propose-start",
        "2026-09-05T15:00",
        "--propose-end",
        "2026-09-05T15:30",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    assert json.loads(route.calls.last.request.content) == {
        "sendResponse": True,
        "proposedNewTime": {
            "start": {"dateTime": "2026-09-05T15:00:00", "timeZone": "Europe/Warsaw"},
            "end": {"dateTime": "2026-09-05T15:30:00", "timeZone": "Europe/Warsaw"},
        },
    }
    assert json.loads(r.stdout) == {"status": "tentativelyAccepted"}


@covers("calendar respond")
def test_calendar_respond_propose_only_for_decline_tentative_exit_2(invoke, graph):
    r = invoke(
        "calendar",
        "respond",
        "AAMkEvt-5004",
        "accept",
        "--propose-start",
        "2026-09-05T15:00",
        "--propose-end",
        "2026-09-05T15:30",
    )
    assert r.exit_code == 2 and graph.calls.call_count == 0


@covers("calendar respond")
def test_calendar_respond_dry_run(invoke, graph):
    r = invoke("calendar", "respond", "AAMkEvt-5005", "accept", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["dryRun"] is True
    assert doc["requests"][0]["url"] == f"{GRAPH}/v1.0/me/events/AAMkEvt-5005/accept"
    assert graph.calls.call_count == 0


# ------------------------------------------------------------ availability / find-times


@covers("calendar availability")
def test_calendar_availability_defaults_me(invoke, graph, monkeypatch):
    _fix_now(monkeypatch, hour=9, minute=7)
    routes = mock_graph(graph, "calendar/availability")
    r = invoke("calendar", "availability", "--json")
    assert r.exit_code == 0, r.stderr
    body = json.loads(routes[1].calls.last.request.content)
    assert body == {
        "schedules": ["ada@example.com"],
        "startTime": {"dateTime": "2026-09-02T09:00:00", "timeZone": "Europe/Warsaw"},
        "endTime": {"dateTime": "2026-09-02T23:59:59", "timeZone": "Europe/Warsaw"},
        "availabilityViewInterval": 30,
    }
    doc = json.loads(r.stdout)
    assert doc["count"] == 1

    r = invoke("calendar", "availability")
    assert r.exit_code == 0, r.stderr
    assert "busy 2026-09-02T10:00+02:00 – 11:00 Standup" in r.stdout
    assert "tentative 2026-09-02T11:00+02:00 – 11:30 Maybe Sync" in r.stdout
    assert "oof 2026-09-02T12:00+02:00 – 12:30 Out" in r.stdout
    assert "free 09:00 – 10:00" in r.stdout


@covers("calendar availability")
def test_calendar_availability_users_and_interval_bounds(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/me/calendar/getSchedule").mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    r = invoke(
        "calendar",
        "availability",
        "--users",
        "a@example.com",
        "--users",
        "b@example.com",
        "--interval",
        "15",
        "--start",
        "2026-09-02T09:00",
        "--end",
        "2026-09-02T10:00",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    body = json.loads(route.calls.last.request.content)
    assert body["schedules"] == ["a@example.com", "b@example.com"]
    assert body["availabilityViewInterval"] == 15

    r = invoke("calendar", "availability", "--interval", "3")
    assert r.exit_code == 2


@covers("calendar find-times")
def test_calendar_find_times_body(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/me/findMeetingTimes").mock(
        return_value=httpx.Response(
            200,
            json={
                "meetingTimeSuggestions": [
                    {
                        "confidence": 100.0,
                        "meetingTimeSlot": {
                            "start": {
                                "dateTime": "2026-09-03T09:00:00.0000000",
                                "timeZone": "Europe/Warsaw",
                            },
                            "end": {
                                "dateTime": "2026-09-03T10:00:00.0000000",
                                "timeZone": "Europe/Warsaw",
                            },
                        },
                        "attendeeAvailability": [
                            {
                                "attendee": {"emailAddress": {"address": "a@example.com"}},
                                "availability": "free",
                            }
                        ],
                    }
                ],
                "emptySuggestionsReason": "AttendeesUnavailable",
            },
        )
    )
    r = invoke(
        "calendar",
        "find-times",
        "--attendees",
        "a@example.com",
        "--duration",
        "1h",
        "--start",
        "2026-09-03",
        "--end",
        "2026-09-05",
        "--max",
        "3",
        "--domain",
        "unrestricted",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "attendees": [{"emailAddress": {"address": "a@example.com"}, "type": "required"}],
        "timeConstraint": {
            "activityDomain": "unrestricted",
            "timeSlots": [
                {
                    "start": {"dateTime": "2026-09-03T00:00:00", "timeZone": "Europe/Warsaw"},
                    "end": {"dateTime": "2026-09-05T23:59:59", "timeZone": "Europe/Warsaw"},
                }
            ],
        },
        "meetingDuration": "PT1H",
        "maxCandidates": 3,
        "returnSuggestionReasons": True,
    }
    doc = json.loads(r.stdout)
    assert doc["emptySuggestionsReason"] == "AttendeesUnavailable"

    r = invoke(
        "calendar",
        "find-times",
        "--attendees",
        "a@example.com",
        "--duration",
        "1h",
        "--start",
        "2026-09-03",
        "--end",
        "2026-09-05",
        "--domain",
        "unrestricted",
    )
    assert r.exit_code == 0, r.stderr
    assert "confidence: 100.0" in r.stdout
    assert "a@example.com: free" in r.stdout
    assert "No suggestions: AttendeesUnavailable" in r.stdout


@covers("calendar find-times")
@pytest.mark.scopes(["Calendars.Read"])
def test_calendar_find_times_missing_scope(invoke, graph):
    r = invoke("calendar", "find-times", "--attendees", "a@example.com")
    assert r.exit_code == 3 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[MISSING_SCOPE]:")


# ------------------------------------------------------------ help


def test_calendar_group_help(invoke):
    r = invoke("calendar")
    assert r.exit_code == 0
    assert "Calendar events" in r.stdout
