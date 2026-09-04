"""CLI tests for the teams noun (spec §8.7)."""

import json

import httpx
import pytest

from helpers import GRAPH, covers, graph_error, mock_graph

TEAM = "11111111-1111-4111-8111-111111111111"
CHANNEL = "19:channel-0001@thread.tacv2"
CHANNEL_URL = f"{GRAPH}/v1.0/teams/{TEAM}/channels/19%3Achannel-0001%40thread.tacv2"


def _msg(mid: str, modified: str, replies: list | None = None) -> dict:
    """A channel message shaped as Graph returns it, dated `modified`."""
    message = {
        "id": mid,
        "messageType": "message",
        "createdDateTime": modified,
        "lastModifiedDateTime": modified,
        "from": {"user": {"displayName": "Ada Example"}},
        "body": {"contentType": "text", "content": f"body {mid}"},
    }
    if replies is not None:
        message["replies"] = replies
    return message


@covers("teams list")
def test_teams_list_no_odata_params(invoke, graph):
    routes = mock_graph(graph, "teams/list")
    r = invoke("teams", "list")
    assert r.exit_code == 0, r.stderr
    assert routes[0].calls.last.request.url.query == b""
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["id", "name", "description"]
    assert lines[1].split("  ")[0] == TEAM
    assert "Engineering" in lines[1] and "Platform and tooling" in lines[1]
    assert r.stderr == ""


@covers("teams list")
def test_teams_list_json(invoke, graph):
    mock_graph(graph, "teams/list")
    doc = json.loads(invoke("teams", "list", "--json").stdout)
    assert set(doc) == {"items", "count", "fetched", "cap", "truncated", "query"}
    assert doc["count"] == 2 and doc["truncated"] is False
    assert doc["items"][0]["id"] == TEAM


@covers("teams get")
def test_teams_get(invoke, graph):
    routes = mock_graph(graph, "teams/get")
    r = invoke("teams", "get", TEAM)
    assert r.exit_code == 0, r.stderr
    assert routes[0].calls.last.request.url.query == b""
    assert "Name        : Engineering" in r.stdout
    assert f"Team id     : {TEAM}" in r.stdout
    doc = json.loads(invoke("teams", "get", TEAM, "--json").stdout)
    assert doc["id"] == TEAM and doc["visibility"] == "private"


@covers("teams get")
@pytest.mark.parametrize(
    "status,code,exit_code",
    [(404, "ErrorItemNotFound", 4), (403, "Forbidden", 3), (400, "BadRequest", 1)],
)
def test_teams_get_error_exit_codes(invoke, graph, status, code, exit_code):
    graph.get(f"{GRAPH}/v1.0/teams/{TEAM}").mock(return_value=graph_error(status, code))
    r = invoke("teams", "get", TEAM)
    assert r.exit_code == exit_code
    assert r.stdout == ""
    assert r.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("teams get")
def test_teams_get_401_after_refresh(invoke, graph):
    route = graph.get(f"{GRAPH}/v1.0/teams/{TEAM}").mock(
        return_value=graph_error(401, "InvalidAuthenticationToken")
    )
    r = invoke("teams", "get", TEAM)
    assert r.exit_code == 3 and route.call_count == 2
    assert r.stderr.startswith("error[UNAUTHORIZED]:") and "login --force" in r.stderr


@covers("teams get")
def test_teams_team_ambiguous_exit_2(invoke, graph):
    mock_graph(graph, "teams/ambiguous")
    r = invoke("teams", "get", "Engineering")
    assert r.exit_code == 2 and r.stdout == ""
    assert r.stderr.startswith("error[AMBIGUOUS]: team 'Engineering' matches 2 items\n")
    assert TEAM in r.stderr


@covers("teams members")
def test_teams_members(invoke, graph):
    routes = mock_graph(graph, "teams/members")
    r = invoke("teams", "members", TEAM)
    assert r.exit_code == 0, r.stderr
    assert routes[0].calls.last.request.url.params["$top"] == "50"
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["id", "name", "email", "roles"]
    assert "MCMjMSMj-0001" in lines[1] and "ada@example.com" in lines[1] and "owner" in lines[1]


@covers("teams members")
@pytest.mark.scopes(["Group.Read.All"])
def test_teams_members_scope_gate(invoke, graph):
    r = invoke("teams", "members", TEAM)
    assert r.exit_code == 3 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[MISSING_SCOPE]: this command needs TeamMember.Read.All;")


@covers("teams members")
def test_teams_members_limit_zero_is_usage_error(invoke, graph):
    r = invoke("teams", "members", TEAM, "--limit", "0")
    assert r.exit_code == 2 and graph.calls.call_count == 0


@covers("teams channels")
def test_teams_channels_select(invoke, graph):
    routes = mock_graph(graph, "teams/channels")
    r = invoke("teams", "channels", TEAM)
    assert r.exit_code == 0, r.stderr
    params = routes[0].calls.last.request.url.params
    assert params["$select"] == "id,displayName,description,membershipType"
    assert "$top" not in params
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["id", "name", "membership", "description"]
    assert CHANNEL in lines[1] and "General" in lines[1] and "standard" in lines[1]


@covers("teams channel get")
def test_teams_channel_get(invoke, graph):
    mock_graph(graph, "teams/channel_get")
    r = invoke("teams", "channel", "get", TEAM, CHANNEL)
    assert r.exit_code == 0, r.stderr
    assert f"Channel id  : {CHANNEL}" in r.stdout
    assert "Name        : General" in r.stdout


@covers("teams channel get")
def test_teams_channel_missing_exit_4(invoke, graph):
    mock_graph(graph, "teams/channels")
    r = invoke("teams", "channel", "get", TEAM, "Nope")
    assert r.exit_code == 4 and r.stdout == ""
    assert r.stderr.startswith("error[NOT_FOUND]: channel 'Nope' not found\n")


@covers("teams channel messages")
def test_channel_messages_by_names_chronological_markdown(invoke, graph):
    routes = mock_graph(graph, "teams/channel_messages")
    r = invoke("teams", "channel", "messages", "Engineering", "General")
    assert r.exit_code == 0, r.stderr
    assert routes[2].calls.last.request.url.params["$top"] == "50"
    lines = [line for line in r.stdout.splitlines() if line.strip()]
    assert lines[0].split() == ["created", "id", "from", "body"]
    # Oldest first in text mode; the deleted and unknownFutureValue messages are dropped.
    assert lines[1].startswith("2026-08-30T13:00+02:00")
    assert lines[2].startswith("2026-08-31T10:15+02:00")
    assert len(lines) == 3
    assert "@Ada Example" in r.stdout and "[image: hostedContents/aWQ=]" in r.stdout
    assert "deleted" not in r.stdout and "reserved for future use" not in r.stdout
    doc = json.loads(
        invoke("teams", "channel", "messages", "Engineering", "General", "--json").stdout
    )
    assert [m["id"] for m in doc["items"]] == ["3", "2"]  # Graph order kept


@covers("teams channel messages")
def test_channel_messages_full_lifts_300(invoke, graph):
    mock_graph(graph, "teams/channel_messages")
    capped = invoke("teams", "channel", "messages", TEAM, CHANNEL)
    assert capped.exit_code == 0, capped.stderr
    assert "A" * 299 + "…" in capped.stdout
    assert "A" * 300 not in capped.stdout
    full = invoke("teams", "channel", "messages", TEAM, CHANNEL, "--full")
    assert full.exit_code == 0, full.stderr
    assert "A" * 400 in full.stdout


@covers("teams channel messages")
def test_channel_messages_with_replies_expand(invoke, graph):
    routes = mock_graph(graph, "teams/channel_messages_expand")
    r = invoke("teams", "channel", "messages", TEAM, CHANNEL, "--with-replies")
    assert r.exit_code == 0, r.stderr
    params = routes[0].calls.last.request.url.params
    assert params["$expand"] == "replies" and params["$top"] == "50"


@covers("teams channel messages")
def test_channel_replies_paged_with_limit(invoke, graph):
    routes = mock_graph(graph, "teams/channel_replies")
    r = invoke("teams", "channel", "messages", TEAM, CHANNEL, "--replies", "3", "--limit", "3")
    assert r.exit_code == 0, r.stderr
    request = routes[0].calls.last.request
    assert request.url.path.endswith("/messages/3/replies")
    assert request.url.params["$top"] == "50"
    assert len([line for line in r.stdout.splitlines() if line.strip()]) == 4  # header + 3


@covers("teams channel messages")
def test_channel_messages_envelope_carries_the_window(invoke, graph):
    graph.get(f"{CHANNEL_URL}/messages").mock(
        return_value=httpx.Response(200, json={"value": [_msg("30", "2026-08-31T12:00:00Z")]})
    )
    doc = json.loads(invoke("teams", "channel", "messages", TEAM, CHANNEL, "--json").stdout)
    # Present even with both bounds unset, so a consumer never branches on the key.
    assert doc["window"] == {"after": None, "before": None}
    assert doc["fetched"] == 1 and doc["cap"] == 20

    doc = json.loads(
        invoke(
            "teams", "channel", "messages", TEAM, CHANNEL, "--after", "2026-08-01", "--json"
        ).stdout
    )
    assert doc["window"] == {"after": "2026-08-01T00:00:00+02:00", "before": None}


@covers("teams list")
def test_teams_list_envelope_has_no_window(invoke, graph):
    """`teams list` takes no date options, so it reports no window."""
    mock_graph(graph, "teams/list")
    doc = json.loads(invoke("teams", "list", "--json").stdout)
    assert "window" not in doc


@covers("teams channel messages")
def test_channel_messages_window_sends_no_filter(invoke, graph):
    """Graph documents only $top and $expand here, so the window is applied client-side."""
    route = graph.get(f"{CHANNEL_URL}/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    _msg("30", "2026-08-31T12:00:00Z"),
                    _msg("20", "2026-08-31T09:00:00Z"),
                    _msg("10", "2026-08-30T09:00:00Z"),
                ]
            },
        )
    )
    r = invoke(
        "teams",
        "channel",
        "messages",
        TEAM,
        CHANNEL,
        "--after",
        "2026-08-31T13:00",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    params = route.calls.last.request.url.params
    assert "$filter" not in params and "$orderby" not in params
    assert params["$top"] == "50" and len(params) == 1
    # The bound is 13:00+02:00: 12:00Z is 14:00 local and inside it, 09:00Z is 11:00 and out.
    assert [m["id"] for m in json.loads(r.stdout)["items"]] == ["30"]


@covers("teams channel messages")
def test_channel_messages_window_stops_paging_at_the_boundary(invoke, graph):
    """The feed is newest-modified first, so the first message past `--after` ends the fetch."""
    first = f"{CHANNEL_URL}/messages"
    second = f"{first}?$skiptoken=page2"
    graph.get(url=first, params__eq={"$top": "50"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [_msg("30", "2026-08-31T12:00:00Z")],
                "@odata.nextLink": second,
            },
        )
    )
    page2 = graph.get(url=first, params__eq={"$skiptoken": "page2"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [_msg("20", "2026-08-30T09:00:00Z")],
                "@odata.nextLink": f"{first}?$skiptoken=page3",
            },
        )
    )
    r = invoke(
        "teams",
        "channel",
        "messages",
        TEAM,
        CHANNEL,
        "--after",
        "2026-08-31T10:00",
        "--all",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert [m["id"] for m in doc["items"]] == ["30"]
    # The third page is never asked for, and stopping at the boundary is not a truncation.
    assert page2.call_count == 1 and doc["truncated"] is False


@covers("teams channel messages")
def test_channel_messages_window_orders_on_the_whole_reply_chain(invoke, graph):
    """Graph orders on the reply chain's last-modified, so `--with-replies` must use it too."""
    graph.get(f"{CHANNEL_URL}/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    _msg(
                        "30",
                        "2026-08-20T09:00:00Z",
                        replies=[_msg("31", "2026-08-31T12:00:00Z")],
                    ),
                    _msg("20", "2026-08-20T09:00:00Z", replies=[]),
                ]
            },
        )
    )
    r = invoke(
        "teams",
        "channel",
        "messages",
        TEAM,
        CHANNEL,
        "--with-replies",
        "--after",
        "2026-08-31T10:00",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    # The root is old but its reply is recent, so the chain is inside the window.
    assert [m["id"] for m in json.loads(r.stdout)["items"]] == ["30"]


@covers("teams channel messages")
def test_channel_messages_before_bound_drops_newer_messages(invoke, graph):
    graph.get(f"{CHANNEL_URL}/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    _msg("30", "2026-09-05T12:00:00Z"),
                    _msg("20", "2026-08-31T12:00:00Z"),
                ]
            },
        )
    )
    r = invoke("teams", "channel", "messages", TEAM, CHANNEL, "--before", "2026-09-01", "--json")
    assert r.exit_code == 0, r.stderr
    assert [m["id"] for m in json.loads(r.stdout)["items"]] == ["20"]


@covers("teams channel messages")
def test_channel_messages_rejects_an_inverted_window(invoke, graph):
    r = invoke(
        "teams",
        "channel",
        "messages",
        TEAM,
        CHANNEL,
        "--after",
        "2026-09-05",
        "--before",
        "2026-09-01",
    )
    assert r.exit_code == 2 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[USAGE]: --after must not be later than --before")


@covers("teams channel messages")
def test_channel_messages_window_does_not_apply_to_replies(invoke, graph):
    r = invoke(
        "teams", "channel", "messages", TEAM, CHANNEL, "--replies", "3", "--after", "2026-09-01"
    )
    assert r.exit_code == 2 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[USAGE]: --after/--before do not apply to --replies")


@covers("teams channel messages")
def test_channel_messages_replies_and_with_replies_conflict(invoke, graph):
    r = invoke("teams", "channel", "messages", TEAM, CHANNEL, "--replies", "3", "--with-replies")
    assert r.exit_code == 2 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[USAGE]: --replies and --with-replies are mutually exclusive")


@covers("teams channel send")
def test_channel_send_text_and_html_and_reply(invoke, graph):
    route = graph.post(f"{CHANNEL_URL}/messages").mock(
        return_value=httpx.Response(201, json={"id": "9", "chatId": None})
    )
    r = invoke("teams", "channel", "send", TEAM, CHANNEL, "--body", "Hi <b>")
    assert r.exit_code == 0, r.stderr
    assert r.stdout == "Sent.\n"
    assert json.loads(route.calls.last.request.content) == {
        "body": {"contentType": "text", "content": "Hi <b>"}
    }

    r = invoke("teams", "channel", "send", TEAM, CHANNEL, "--body", "<p>Hi</p>", "--html")
    assert r.exit_code == 0, r.stderr
    assert json.loads(route.calls.last.request.content) == {
        "body": {"contentType": "html", "content": "<p>Hi</p>"}
    }

    r = invoke(
        "teams", "channel", "send", TEAM, CHANNEL, "--body", "Hi", "--subject", "Standup", "--json"
    )
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["id"] == "9"
    assert json.loads(route.calls.last.request.content) == {
        "subject": "Standup",
        "body": {"contentType": "text", "content": "Hi"},
    }

    reply = graph.post(f"{CHANNEL_URL}/messages/3/replies").mock(
        return_value=httpx.Response(201, json={"id": "10"})
    )
    r = invoke("teams", "channel", "send", TEAM, CHANNEL, "--body", "Hi", "--reply-to", "3")
    assert r.exit_code == 0, r.stderr
    assert json.loads(reply.calls.last.request.content) == {
        "body": {"contentType": "text", "content": "Hi"}
    }


@covers("teams channel send")
def test_channel_send_dry_run(invoke, graph):
    r = invoke("teams", "channel", "send", TEAM, CHANNEL, "--body", "Hi", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["dryRun"] is True
    assert doc["requests"] == [
        {
            "method": "POST",
            "url": f"{CHANNEL_URL}/messages",
            "headers": {"Content-Type": "application/json"},
            "body": {"body": {"contentType": "text", "content": "Hi"}},
        }
    ]
    assert graph.calls.call_count == 0
    text = invoke("teams", "channel", "send", TEAM, CHANNEL, "--body", "Hi", "--dry-run")
    assert text.stdout.startswith(f"DRY RUN — nothing sent\n1. POST {CHANNEL_URL}/messages\n")
    assert graph.calls.call_count == 0


@covers("teams channel send")
def test_channel_send_needs_exactly_one_body_option(invoke, graph):
    r = invoke("teams", "channel", "send", TEAM, CHANNEL)
    assert r.exit_code == 2 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[USAGE]: give exactly one of --body or --body-file")


@covers("teams channel send")
def test_channel_send_body_file(invoke, graph, tmp_path):
    route = graph.post(f"{CHANNEL_URL}/messages").mock(
        return_value=httpx.Response(201, json={"id": "9"})
    )
    body_file = tmp_path / "note.txt"
    body_file.write_text("From a file")
    r = invoke("teams", "channel", "send", TEAM, CHANNEL, "--body-file", str(body_file))
    assert r.exit_code == 0, r.stderr
    assert json.loads(route.calls.last.request.content)["body"]["content"] == "From a file"


def test_teams_group_help_exits_zero(invoke):
    assert invoke("teams").exit_code == 0
    assert invoke("teams", "channel").exit_code == 0
