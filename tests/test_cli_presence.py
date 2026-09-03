"""CLI tests for the presence noun (spec §8.9)."""

import json

import httpx
import pytest

from helpers import GRAPH, covers, graph_error, mock_graph

ME = "00000000-0000-0000-0000-000000000001"
BOB = "00000000-0000-0000-0000-0000000000b0"
PRESENCE_URL = f"{GRAPH}/v1.0/users/{ME}/presence"


@covers("presence get")
def test_presence_get_self_and_others(invoke, graph):
    routes = mock_graph(graph, "presence/me")
    r = invoke("presence", "get")
    assert r.exit_code == 0, r.stderr
    assert routes[0].calls.last.request.url.query == b""
    assert "Availability : Available" in r.stdout
    assert "Activity     : Available" in r.stdout
    assert f"User id      : {ME}" in r.stdout
    doc = json.loads(invoke("presence", "get", "--json").stdout)
    assert doc["availability"] == "Available" and doc["id"] == ME

    other_routes = mock_graph(graph, "presence/others")
    r = invoke("presence", "get", "bob@example.com")
    assert r.exit_code == 0, r.stderr
    assert other_routes[0].calls.last.request.url.params["$select"] == "id,displayName"
    assert json.loads(other_routes[1].calls.last.request.content) == {"ids": [BOB]}
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["id", "name", "availability", "activity"]
    assert BOB in lines[1] and "Bob Example" in lines[1] and "InACall" in lines[1]


@covers("presence get")
@pytest.mark.scopes(["Presence.Read", "User.Read"])
def test_presence_get_others_needs_read_all(invoke, graph):
    r = invoke("presence", "get", "bob@example.com")
    assert r.exit_code == 3 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[MISSING_SCOPE]: this command needs Presence.Read.All;")
    assert "--scope Presence.Read.All" in r.stderr


@covers("presence get")
def test_presence_get_error_exit_codes(invoke, graph):
    graph.get(f"{GRAPH}/v1.0/me/presence").mock(return_value=graph_error(404, "ErrorItemNotFound"))
    r = invoke("presence", "get")
    assert r.exit_code == 4 and r.stdout == ""
    assert r.stderr.startswith("error[ErrorItemNotFound]: boom\n  request-id: req-0001\n")


@covers("presence set")
def test_presence_set_pairs_expiration_and_message(invoke, graph):
    prefer = graph.post(f"{PRESENCE_URL}/setUserPreferredPresence").mock(
        return_value=httpx.Response(200)
    )
    status = graph.post(f"{PRESENCE_URL}/setStatusMessage").mock(return_value=httpx.Response(200))
    r = invoke("presence", "set", "dnd", "--expiration", "2h", "--message", "Heads down")
    assert r.exit_code == 0, r.stderr
    assert r.stdout == "Presence set to DoNotDisturb.\n"
    assert json.loads(prefer.calls.last.request.content) == {
        "availability": "DoNotDisturb",
        "activity": "DoNotDisturb",
        "expirationDuration": "PT2H",
    }
    assert json.loads(status.calls.last.request.content) == {
        "statusMessage": {"message": {"content": "Heads down", "contentType": "text"}}
    }

    r = invoke("presence", "set", "offline", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout) == {"status": "ok"}
    assert json.loads(prefer.calls.last.request.content) == {
        "availability": "Offline",
        "activity": "OffWork",
        "expirationDuration": "PT1H",
    }
    assert status.call_count == 1  # no --message, no second call

    invoke("presence", "set", "brb")
    assert json.loads(prefer.calls.last.request.content)["availability"] == "BeRightBack"


@covers("presence set")
def test_presence_set_dry_run(invoke, graph):
    r = invoke("presence", "set", "busy", "--message", "In a call", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["dryRun"] is True
    assert doc["requests"] == [
        {
            "method": "POST",
            "url": f"{PRESENCE_URL}/setUserPreferredPresence",
            "headers": {"Content-Type": "application/json"},
            "body": {
                "availability": "Busy",
                "activity": "Busy",
                "expirationDuration": "PT1H",
            },
        },
        {
            "method": "POST",
            "url": f"{PRESENCE_URL}/setStatusMessage",
            "headers": {"Content-Type": "application/json"},
            "body": {"statusMessage": {"message": {"content": "In a call", "contentType": "text"}}},
        },
    ]
    assert graph.calls.call_count == 0


@covers("presence set")
def test_presence_set_rejects_unknown_state(invoke, graph):
    r = invoke("presence", "set", "napping")
    assert r.exit_code == 2 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[USAGE]: unknown presence 'napping'; use one of available")


@covers("presence set")
@pytest.mark.scopes(["Presence.Read"])
def test_presence_set_scope_gate(invoke, graph):
    r = invoke("presence", "set", "busy")
    assert r.exit_code == 3 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[MISSING_SCOPE]: this command needs Presence.ReadWrite;")


@covers("presence clear")
def test_presence_clear(invoke, graph):
    route = graph.post(f"{PRESENCE_URL}/clearUserPreferredPresence").mock(
        return_value=httpx.Response(200)
    )
    r = invoke("presence", "clear")
    assert r.exit_code == 0, r.stderr
    assert r.stdout == "Preferred presence cleared.\n"
    assert route.called and route.calls.last.request.content == b""


@covers("presence clear")
def test_presence_clear_dry_run(invoke, graph):
    r = invoke("presence", "clear", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout) == {
        "dryRun": True,
        "requests": [
            {
                "method": "POST",
                "url": f"{PRESENCE_URL}/clearUserPreferredPresence",
                "headers": {},
                "body": None,
            }
        ],
    }
    assert graph.calls.call_count == 0
    text = invoke("presence", "clear", "--dry-run")
    assert text.stdout == (
        f"DRY RUN — nothing sent\n1. POST {PRESENCE_URL}/clearUserPreferredPresence\n"
    )


def test_presence_group_help_exits_zero(invoke):
    assert invoke("presence").exit_code == 0
