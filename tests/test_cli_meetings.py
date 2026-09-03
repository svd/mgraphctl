"""CLI tests for the meetings noun (spec §8.10)."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from helpers import GRAPH, covers, graph_error, mock_graph
from mgraphctl import auth, config


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
def test_meetings_list_truncated_reports_the_cap(invoke, graph):
    def online_event(event_id: str, subject: str, join_url: str) -> dict:
        return {
            "id": event_id,
            "subject": subject,
            "isOnlineMeeting": True,
            "onlineMeeting": {"joinUrl": join_url},
            "start": {"dateTime": "2026-08-10T09:00:00.0000000", "timeZone": "Europe/Warsaw"},
            "end": {"dateTime": "2026-08-10T09:30:00.0000000", "timeZone": "Europe/Warsaw"},
            "organizer": {"emailAddress": {"name": "Ada Example", "address": "ada@example.com"}},
        }

    graph.get(f"{GRAPH}/v1.0/me/calendarView").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    online_event("AAMkEvent-0001", "One", "https://teams.example.com/l/1"),
                    online_event("AAMkEvent-0002", "Two", "https://teams.example.com/l/2"),
                ]
            },
        )
    )
    r = invoke("meetings", "list", "--limit", "1", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 1 and doc["truncated"] is True

    r = invoke("meetings", "list", "--limit", "1")
    assert r.exit_code == 0, r.stderr
    assert "hit the 1-item cap" in r.stderr


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


@covers("meetings transcripts")
def test_meetings_transcripts_list(invoke, graph):
    mock_graph(graph, "meetings/transcripts")
    r = invoke("meetings", "transcripts", "MSpk-1", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 2 and doc["items"][0]["id"] == "tr-1"
    r = invoke("meetings", "transcripts", "MSpk-1")
    assert r.stdout.splitlines()[0].split() == ["id", "created"]


@covers("meetings transcript")
def test_meetings_transcript_text_vtt_output(invoke, graph, tmp_path):
    mock_graph(graph, "meetings/transcript")
    r = invoke("meetings", "transcript", "MSpk-1", "tr-1", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc == {
        "meetingId": "MSpk-1",
        "transcriptId": "tr-1",
        "format": "text",
        "text": "[00:00:01] Ada Example: Hello there",
    }
    r = invoke("meetings", "transcript", "MSpk-1", "tr-1", "--format", "vtt")
    assert r.exit_code == 0, r.stderr
    assert "WEBVTT" in r.stdout

    out = tmp_path / "t.txt"
    r = invoke("meetings", "transcript", "MSpk-1", "tr-1", "--output", str(out))
    assert r.exit_code == 0, r.stderr
    assert out.read_text() == "[00:00:01] Ada Example: Hello there"


@covers("meetings transcript")
def test_meetings_transcript_via_join_url_single_positional(invoke, graph):
    mock_graph(graph, "meetings/transcript")
    graph.get(f"{GRAPH}/v1.0/me/onlineMeetings").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "MSpk-1",
                        "subject": "Sprint Planning",
                        "joinWebUrl": "https://teams.example.com/l/1",
                    }
                ]
            },
        )
    )
    r = invoke(
        "meetings",
        "transcript",
        "tr-1",
        "--join-url",
        "https://teams.example.com/l/1",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["meetingId"] == "MSpk-1"


@covers("meetings transcript")
def test_meetings_transcript_speaker_attribution_fallback(invoke, graph):
    content_url = f"{GRAPH}/v1.0/me/onlineMeetings/MSpk-1/transcripts/tr-1/content"
    route = graph.get(content_url).mock(
        side_effect=[
            graph_error(403, "SpeakerAttributionNotAllowed", "not allowed"),
            httpx.Response(200, text="Ada Example: Hello there"),
        ]
    )
    r = invoke("meetings", "transcript", "MSpk-1", "tr-1", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["text"] == "Ada Example: Hello there"
    assert route.call_count == 2
    last = route.calls.last.request
    assert last.headers["Accept"] == "application/vnd.microsoft.graph.transcript+text"


@covers("meetings insights")
def test_meetings_insights_v1_404_then_beta_keeps_failed_item(invoke, graph):
    oid = auth.FIXTURE_OID
    v1_base = f"{GRAPH}/v1.0/copilot/users/{oid}/onlineMeetings/MSpk-1/aiInsights"
    beta_base = f"{GRAPH}/beta/copilot/users/{oid}/onlineMeetings/MSpk-1/aiInsights"
    graph.get(v1_base).mock(return_value=graph_error(404, "NotFound", "not on v1"))
    graph.get(beta_base).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {"id": "insight-1", "title": "Summary"},
                    {"id": "insight-2", "title": "Action items"},
                ]
            },
        )
    )
    graph.get(f"{beta_base}/insight-1").mock(
        return_value=httpx.Response(
            200, json={"id": "insight-1", "title": "Summary", "content": "It went well."}
        )
    )
    graph.get(f"{beta_base}/insight-2").mock(return_value=graph_error(500, "InternalError", "boom"))
    r = invoke("meetings", "insights", "MSpk-1", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 2
    assert doc["items"][0] == {
        "id": "insight-1",
        "title": "Summary",
        "content": "It went well.",
    }
    assert doc["items"][1] == {"id": "insight-2", "title": "Action items"}
    assert "note" not in doc


@covers("meetings insights")
def test_meetings_insights_global_beta_flag_keeps_item_detail_on_beta(invoke, graph):
    """`--beta` makes the summary call land on `/beta` directly (no 404 fallback needed); the
    per-item detail GET must follow it there rather than defaulting back to v1.0."""
    oid = auth.FIXTURE_OID
    beta_base = f"{GRAPH}/beta/copilot/users/{oid}/onlineMeetings/MSpk-4/aiInsights"
    graph.get(beta_base).mock(
        return_value=httpx.Response(200, json={"value": [{"id": "insight-9", "title": "Recap"}]})
    )
    detail_route = graph.get(f"{beta_base}/insight-9").mock(
        return_value=httpx.Response(
            200, json={"id": "insight-9", "title": "Recap", "content": "All good."}
        )
    )
    r = invoke("--beta", "meetings", "insights", "MSpk-4", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["items"] == [{"id": "insight-9", "title": "Recap", "content": "All good."}]
    assert detail_route.called
    assert "/beta/" in str(detail_route.calls.last.request.url)


@covers("meetings insights")
def test_meetings_insights_forbidden_is_a_soft_license_message(invoke, graph):
    base = f"{GRAPH}/v1.0/copilot/users/{auth.FIXTURE_OID}/onlineMeetings/MSpk-2/aiInsights"
    graph.get(base).mock(return_value=graph_error(403, "Forbidden", "no license"))
    r = invoke("meetings", "insights", "MSpk-2")
    assert r.exit_code == 0, r.stderr
    assert "AI insights require a Microsoft 365 Copilot license" in r.stdout
    r = invoke("meetings", "insights", "MSpk-2", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["items"] == [] and doc["count"] == 0 and doc["truncated"] is False
    assert "Copilot license" in doc["note"]


@covers("meetings insights")
def test_meetings_insights_empty_is_a_soft_message(invoke, graph):
    base = f"{GRAPH}/v1.0/copilot/users/{auth.FIXTURE_OID}/onlineMeetings/MSpk-3/aiInsights"
    graph.get(base).mock(return_value=httpx.Response(200, json={"value": []}))
    r = invoke("meetings", "insights", "MSpk-3", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["items"] == [] and doc["count"] == 0
    assert "No AI insights" in doc["note"]


@covers("meetings recordings")
def test_meetings_recordings_and_download(invoke, graph, tmp_path):
    mock_graph(graph, "meetings/recordings")
    r = invoke("meetings", "recordings", "MSpk-1", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 1 and doc["items"][0]["id"] == "rec-1"

    out = tmp_path / "rec.mp4"
    route = graph.get(f"{GRAPH}/v1.0/me/onlineMeetings/MSpk-1/recordings/rec-1/content").mock(
        return_value=httpx.Response(200, content=b"FAKEMP4", headers={"Content-Type": "video/mp4"})
    )
    r = invoke("meetings", "recordings", "MSpk-1", "--download", "rec-1", "--output", str(out))
    assert r.exit_code == 0, r.stderr
    assert out.read_bytes() == b"FAKEMP4"
    assert route.called


@covers("meetings recordings")
@pytest.mark.scopes(config.DEFAULT_SCOPES)
def test_meetings_recordings_on_demand_scope_hint(invoke, graph):
    r = invoke("meetings", "recordings", "MSpk-1")
    assert r.exit_code == 3 and graph.calls.call_count == 0
    assert "login --scope OnlineMeetingRecording.Read.All" in r.stderr


def test_meetings_group_help(invoke):
    r = invoke("meetings")
    assert r.exit_code == 0 and "Usage:" in r.stdout
