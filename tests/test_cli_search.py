"""CLI tests for the unified `search` command (spec §8.17)."""

import json

import httpx
import pytest

from helpers import GRAPH, covers, graph_error, mock_graph


@covers("search")
def test_search_message_kql_dates_and_paging(invoke, graph):
    routes = mock_graph(graph, "search/message")
    r = invoke(
        "search", "budget", "--after", "2026-08-01", "--before", "2026-08-31", "--all", "--json"
    )
    assert r.exit_code == 0, r.stderr
    first = json.loads(routes[0].calls[0].request.content)
    assert first == {
        "requests": [
            {
                "entityTypes": ["message"],
                "query": {"queryString": "budget received>=2026-08-01 received<=2026-08-31"},
                "from": 0,
                "size": 25,
            }
        ]
    }
    assert json.loads(routes[0].calls[1].request.content)["requests"][0]["from"] == 25
    doc = json.loads(r.stdout)
    assert doc["count"] == 3 and doc["truncated"] is False
    assert doc["items"][0]["resource"]["subject"] == "Budget review"


@covers("search")
def test_search_message_text_columns(invoke, graph):
    mock_graph(graph, "search/message")
    text = invoke("search", "budget").stdout
    lines = text.splitlines()
    assert lines[0].split() == ["id", "received", "subject", "from", "webUrl"]
    assert "AAMk-msg-0001" in lines[1] and "Budget review" in lines[1]


@covers("search")
def test_search_event_columns(invoke, graph):
    mock_graph(graph, "search/event")
    r = invoke("search", "budget", "--type", "event")
    assert r.exit_code == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["id", "start", "subject", "organizer", "webUrl"]
    assert "AAMk-evt-0001" in lines[1] and "Ada Example" in lines[1]


@covers("search")
def test_search_drive_item_columns(invoke, graph):
    mock_graph(graph, "search/drive_item")
    r = invoke("search", "budget", "--type", "driveItem")
    assert r.exit_code == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["id", "modified", "name", "author", "webUrl"]
    assert "Budget.xlsx" in lines[1] and "Ada Example" in lines[1]


@covers("search")
def test_search_person_columns(invoke, graph):
    mock_graph(graph, "search/person")
    r = invoke("search", "budget", "--type", "person")
    assert r.exit_code == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["id", "name", "email", "title"]
    assert "Ada Example" in lines[1] and "ada@example.com" in lines[1]


@covers("search")
def test_search_chat_message_uses_shape_chat_hit(invoke, graph):
    routes = mock_graph(graph, "search/chat_message")
    r = invoke("search", "budget", "--type", "chatMessage", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(routes[0].calls.last.request.content) == {
        "requests": [
            {
                "entityTypes": ["chatMessage"],
                "query": {"queryString": "budget"},
                "from": 0,
                "size": 25,
            }
        ]
    }
    doc = json.loads(r.stdout)
    assert doc["items"][0]["where"] == "chat:19:chat-0001@thread.v2"
    assert (
        doc["items"][1]["where"]
        == "channel:11111111-1111-4111-8111-111111111111/19:channel-0001@thread.tacv2"
    )
    text = invoke("search", "budget", "--type", "chatMessage").stdout
    assert text.splitlines()[0].split() == ["id", "created", "from", "where", "summary"]


@covers("search")
def test_search_client_side_dates_for_events(invoke, graph):
    mock_graph(graph, "search/event")
    doc = json.loads(
        invoke("search", "budget", "--type", "event", "--after", "2026-08-15", "--json").stdout
    )
    assert [h["resource"]["id"] for h in doc["items"]] == ["AAMk-evt-0002", "AAMk-evt-0003"]
    doc = json.loads(
        invoke("search", "budget", "--type", "event", "--before", "2026-08-15", "--json").stdout
    )
    assert [h["resource"]["id"] for h in doc["items"]] == ["AAMk-evt-0001"]


@covers("search")
def test_search_fields_option(invoke, graph):
    routes = mock_graph(graph, "search/message")
    r = invoke("search", "budget", "--fields", "subject,from", "--json")
    assert r.exit_code == 0, r.stderr
    body = json.loads(routes[0].calls[0].request.content)
    assert body["requests"][0]["fields"] == ["subject", "from"]


@covers("search")
@pytest.mark.scopes(["Mail.Read"])
def test_search_scope_gate_by_type(invoke, graph):
    denied = invoke("search", "budget", "--type", "driveItem")
    assert denied.exit_code == 3
    assert graph.calls.call_count == 0
    assert "Sites.Read.All" in denied.stderr

    mock_graph(graph, "search/message")
    allowed = invoke("search", "budget")
    assert allowed.exit_code == 0, allowed.stderr


@covers("search")
def test_search_limit_and_cap(invoke, graph):
    routes = mock_graph(graph, "search/limit")
    r = invoke("search", "budget", "--limit", "5", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 5
    assert doc["truncated"] is True
    assert routes[0].call_count == 1


@covers("search")
def test_search_all_stops_at_cap(invoke, graph):
    page = [
        {
            "hitId": str(i),
            "rank": i,
            "summary": "budget",
            "resource": {
                "id": f"AAMk-msg-{i:04d}",
                "subject": "Budget",
                "receivedDateTime": "2026-08-01T00:00:00Z",
                "webUrl": f"https://outlook.office.com/mail/AAMk-msg-{i:04d}",
            },
        }
        for i in range(120)
    ]
    body = {
        "value": [{"hitsContainers": [{"hits": page, "total": 500, "moreResultsAvailable": True}]}]
    }
    route = graph.post(f"{GRAPH}/v1.0/search/query").mock(
        side_effect=[httpx.Response(200, json=body), httpx.Response(200, json=body)]
    )
    r = invoke("search", "budget", "--all", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 200
    assert doc["truncated"] is True
    assert route.call_count == 2


@covers("search")
def test_search_limit_zero_is_usage_error(invoke):
    assert invoke("search", "budget", "--limit", "0").exit_code == 2


@covers("search")
def test_search_is_a_top_level_command(invoke):
    result = invoke("search")
    assert result.exit_code == 2


@covers("search")
@pytest.mark.parametrize(
    "status,code,exit_code",
    [(404, "ErrorItemNotFound", 4), (403, "ErrorAccessDenied", 3), (400, "BadRequest", 1)],
)
def test_search_error_exit_codes(invoke, graph, status, code, exit_code):
    graph.post(f"{GRAPH}/v1.0/search/query").mock(return_value=graph_error(status, code))
    result = invoke("search", "budget")
    assert result.exit_code == exit_code
    assert result.stdout == ""
    assert result.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("search")
def test_search_401_after_refresh(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/search/query").mock(
        return_value=graph_error(401, "InvalidAuthenticationToken")
    )
    result = invoke("search", "budget")
    assert result.exit_code == 3 and route.call_count == 2
    assert result.stderr.startswith("error[UNAUTHORIZED]:") and "login --force" in result.stderr
