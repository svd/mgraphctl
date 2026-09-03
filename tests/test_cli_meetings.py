"""CLI tests for the meetings noun (spec §8.10)."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from helpers import GRAPH, covers, graph_error, mock_graph


@covers("meetings list")
def test_meetings_list_default_window_resolve_and_transcripts(invoke, graph, monkeypatch):
    from mgraphctl import render

    fixed = datetime(2026, 9, 2, 15, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    monkeypatch.setattr(render, "_now", lambda zone: fixed.astimezone(zone))
    routes = mock_graph(graph, "meetings/list_resolve")
    r = invoke("meetings", "list", "--resolve", "--with-transcripts", "--json")
    assert r.exit_code == 0, r.stderr
    view = routes[0].calls.last.request
    assert (
        view.url.params["startDateTime"] == "2026-08-26T00:00:00+02:00"
        and view.url.params["endDateTime"] == "2026-09-02T23:59:59+02:00"
    )
    batch = json.loads(routes[1].calls.last.request.content)
    assert [b["url"] for b in batch["requests"]] == [
        "/me/onlineMeetings?$filter=JoinWebUrl%20eq%20%27https%3A%2F%2Fteams.example.com%2Fl%2F1%27",
        "/me/onlineMeetings?$filter=JoinWebUrl%20eq%20%27https%3A%2F%2Fteams.example.com%2Fl%2F2%27",
    ]
    doc = json.loads(r.stdout)
    assert doc["count"] == 2 and doc["items"][0]["meetingId"] == "MSpk-1"
    assert doc["items"][0]["transcriptIds"] == ["tr-1"]
    text = invoke("meetings", "list", "--resolve", "--with-transcripts").stdout.splitlines()
    assert text[0].split() == ["start", "subject", "event_id", "meeting_id", "transcripts"]


@covers("meetings list")
def test_meetings_list_with_transcripts_implies_resolve(invoke, graph, monkeypatch):
    from mgraphctl import render

    fixed = datetime(2026, 9, 2, 15, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    monkeypatch.setattr(render, "_now", lambda zone: fixed.astimezone(zone))
    mock_graph(graph, "meetings/list_resolve")
    r = invoke("meetings", "list", "--with-transcripts", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["items"][0]["meetingId"] == "MSpk-1"
    assert doc["items"][0]["transcriptIds"] == ["tr-1"]


@covers("meetings list")
def test_meetings_list_subject_filter_and_window_options(invoke, graph):
    route = graph.get(f"{GRAPH}/v1.0/me/calendarView").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "AAMkEvent-0001",
                        "subject": "Sprint Planning",
                        "isOnlineMeeting": True,
                        "onlineMeeting": {"joinUrl": "https://teams.example.com/l/1"},
                        "start": {
                            "dateTime": "2026-08-10T09:00:00.0000000",
                            "timeZone": "Europe/Warsaw",
                        },
                        "end": {
                            "dateTime": "2026-08-10T09:30:00.0000000",
                            "timeZone": "Europe/Warsaw",
                        },
                        "organizer": {
                            "emailAddress": {"name": "Ada Example", "address": "ada@example.com"}
                        },
                    },
                    {
                        "id": "AAMkEvent-0002",
                        "subject": "Design Review",
                        "isOnlineMeeting": True,
                        "onlineMeeting": {"joinUrl": "https://teams.example.com/l/2"},
                        "start": {
                            "dateTime": "2026-08-11T09:00:00.0000000",
                            "timeZone": "Europe/Warsaw",
                        },
                        "end": {
                            "dateTime": "2026-08-11T09:30:00.0000000",
                            "timeZone": "Europe/Warsaw",
                        },
                        "organizer": {
                            "emailAddress": {"name": "Bob Example", "address": "bob@example.com"}
                        },
                    },
                ]
            },
        )
    )
    r = invoke(
        "meetings",
        "list",
        "--start",
        "2026-08-01",
        "--end",
        "2026-08-31",
        "--subject",
        "sprint",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 1 and doc["items"][0]["subject"] == "Sprint Planning"
    assert route.calls.last.request.url.params["startDateTime"] == "2026-08-01T00:00:00+02:00"
    assert route.calls.last.request.url.params["endDateTime"] == "2026-08-31T23:59:59+02:00"


@covers("meetings list")
def test_meetings_list_limit_zero_is_usage_error(invoke):
    assert invoke("meetings", "list", "--limit", "0").exit_code == 2


@covers("meetings list")
@pytest.mark.scopes(["Calendars.Read"])
def test_meetings_list_resolve_requires_online_meetings_scope(invoke, graph):
    route = graph.get(f"{GRAPH}/v1.0/me/calendarView").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "AAMkEvent-0001",
                        "subject": "Sprint Planning",
                        "isOnlineMeeting": True,
                        "onlineMeeting": {"joinUrl": "https://teams.example.com/l/1"},
                        "start": {
                            "dateTime": "2026-08-10T09:00:00.0000000",
                            "timeZone": "Europe/Warsaw",
                        },
                        "end": {
                            "dateTime": "2026-08-10T09:30:00.0000000",
                            "timeZone": "Europe/Warsaw",
                        },
                        "organizer": {
                            "emailAddress": {"name": "Ada Example", "address": "ada@example.com"}
                        },
                    }
                ]
            },
        )
    )
    r = invoke("meetings", "list", "--resolve")
    assert r.exit_code == 3
    assert r.stderr.startswith("error[MISSING_SCOPE]:")
    assert route.called


@covers("meetings get")
def test_meetings_get_by_id_join_url_event(invoke, graph):
    mock_graph(graph, "meetings/get")
    r = invoke("meetings", "get", "MSpk-1", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["subject"] == "Sprint Planning"

    r = invoke("meetings", "get", "--join-url", "https://teams.example.com/l/2", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["id"] == "MSpk-2"

    r = invoke("meetings", "get", "--event", "AAMkEvent-0009", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["id"] == "MSpk-9"

    r = invoke("meetings", "get", "MSpk-1")
    assert r.exit_code == 0
    assert "Sprint Planning" in r.stdout


@covers("meetings get")
def test_meetings_get_selector_conflict_exit_2(invoke, graph):
    r = invoke("meetings", "get", "MSpk-1", "--join-url", "https://teams.example.com/l/2")
    assert r.exit_code == 2 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[USAGE]:")
    r = invoke("meetings", "get")
    assert r.exit_code == 2 and graph.calls.call_count == 0


@covers("meetings get")
@pytest.mark.parametrize(
    "status,code,exit_code",
    [(404, "ErrorItemNotFound", 4), (403, "ErrorAccessDenied", 3), (400, "BadRequest", 1)],
)
def test_meetings_get_error_exit_codes(invoke, graph, status, code, exit_code):
    graph.get(f"{GRAPH}/v1.0/me/onlineMeetings/MSpk-x").mock(return_value=graph_error(status, code))
    r = invoke("meetings", "get", "MSpk-x")
    assert r.exit_code == exit_code
    assert r.stdout == ""
    assert r.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("meetings get")
def test_meetings_get_401_after_refresh(invoke, graph):
    route = graph.get(f"{GRAPH}/v1.0/me/onlineMeetings/MSpk-x").mock(
        return_value=graph_error(401, "InvalidAuthenticationToken")
    )
    r = invoke("meetings", "get", "MSpk-x")
    assert r.exit_code == 3 and route.call_count == 2
    assert r.stderr.startswith("error[UNAUTHORIZED]:") and "login --force" in r.stderr
