"""CLI tests for the chats noun (spec §8.8)."""

import json

import httpx
import pytest

from helpers import GRAPH, covers, graph_error, mock_graph
from mgraphctl import config

CHAT = "19:chat-0001@thread.v2"
CHAT_URL = f"{GRAPH}/v1.0/chats/19%3Achat-0001%40thread.v2"
ME = "00000000-0000-0000-0000-000000000001"
BOB = "00000000-0000-0000-0000-0000000000b0"
TEAM = "11111111-1111-4111-8111-111111111111"
CHANNEL = "19:channel-0001@thread.tacv2"
PNG = b"\x89PNG\r\n\x1a\n"


def bind(user_id: str) -> dict:
    return {
        "@odata.type": "#microsoft.graph.aadUserConversationMember",
        "roles": ["owner"],
        "user@odata.bind": f"{GRAPH}/v1.0/users('{user_id}')",
    }


@covers("chats list")
def test_chats_list_query_unread_and_titles(invoke, graph):
    routes = mock_graph(graph, "chats/list")
    r = invoke("chats", "list")
    assert r.exit_code == 0, r.stderr
    params = routes[0].calls.last.request.url.params
    assert params["$top"] == "50"
    assert params["$expand"] == "members,lastMessagePreview"
    assert params["$orderby"] == "lastMessagePreview/createdDateTime desc"
    assert params["$select"] == "id,topic,chatType,lastUpdatedDateTime,viewpoint,webUrl"
    assert "$filter" not in params
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["id", "flags", "type", "updated", "title"]
    assert lines[1].startswith(CHAT) and "*" in lines[1]
    assert lines[1].rstrip().endswith("Bob Example")
    assert lines[2].rstrip().endswith("Launch plan") and "*" not in lines[2]
    assert lines[3].rstrip().endswith("Bob Example, Cleo Example, Dan Example")


@covers("chats list")
def test_chats_list_unread_only(invoke, graph):
    mock_graph(graph, "chats/list")
    r = invoke("chats", "list", "--unread", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 1 and [c["id"] for c in doc["items"]] == [CHAT]


@covers("chats list")
def test_chats_list_type_filter(invoke, graph):
    routes = mock_graph(graph, "chats/list_group")
    r = invoke("chats", "list", "--type", "group")
    assert r.exit_code == 0, r.stderr
    assert routes[0].calls.last.request.url.params["$filter"] == "chatType eq 'group'"
    bad = invoke("chats", "list", "--type", "nope")
    assert bad.exit_code == 2
    assert bad.stderr.startswith("error[USAGE]: unknown chat type 'nope'; use one of oneOnOne")


@covers("chats list")
def test_chats_list_envelope_carries_the_window(invoke, graph):
    mock_graph(graph, "chats/list")
    doc = json.loads(invoke("chats", "list", "--json").stdout)
    assert doc["window"] == {"after": None, "before": None}
    doc = json.loads(invoke("chats", "list", "--since", "2026-08-30T09:00", "--json").stdout)
    assert doc["window"] == {"after": "2026-08-30T09:00:00+02:00", "before": None}
    assert doc["count"] == 2 and doc["fetched"] == 3 and doc["cap"] == 20


@covers("chats list")
def test_chats_list_since_stops_at_the_boundary(invoke, graph):
    """The feed is already ordered by last message, so `--since` needs no server-side filter."""
    routes = mock_graph(graph, "chats/list")
    r = invoke("chats", "list", "--since", "2026-08-30T09:00", "--json")
    assert r.exit_code == 0, r.stderr
    params = routes[0].calls.last.request.url.params
    # The request is exactly the plain one: no extra parameter carries `--since`.
    assert "$filter" not in params
    assert params["$orderby"] == "lastMessagePreview/createdDateTime desc"
    assert params["$expand"] == "members,lastMessagePreview"
    doc = json.loads(r.stdout)
    # 09:00Z on the 31st and 11:00Z on the 30th are inside; 07:30Z on the 29th is not.
    assert [c["id"] for c in doc["items"]] == [CHAT, "19:chat-0002@thread.v2"]
    # Reaching the far edge of the window is not a truncation.
    assert doc["truncated"] is False


@covers("chats list")
def test_chats_list_since_adds_a_last_message_column(invoke, graph):
    mock_graph(graph, "chats/list")
    plain = invoke("chats", "list")
    assert plain.exit_code == 0, plain.stderr
    assert plain.stdout.splitlines()[0].split() == ["id", "flags", "type", "updated", "title"]

    r = invoke("chats", "list", "--since", "2026-08-01")
    assert r.exit_code == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["id", "flags", "type", "updated", "lastMessage", "title"]
    assert "2026-08-31T11:00+02:00" in lines[1]


@covers("chats list")
def test_chats_list_since_combines_with_unread_and_type(invoke, graph):
    mock_graph(graph, "chats/list")
    r = invoke("chats", "list", "--since", "2026-08-01", "--unread", "--json")
    assert r.exit_code == 0, r.stderr
    assert [c["id"] for c in json.loads(r.stdout)["items"]] == [CHAT]

    routes = mock_graph(graph, "chats/list_group")
    r = invoke("chats", "list", "--since", "2026-08-01", "--type", "group")
    assert r.exit_code == 0, r.stderr
    # `--type` still filters server-side; `--since` still adds nothing to the query.
    params = routes[0].calls.last.request.url.params
    assert params["$filter"] == "chatType eq 'group'"
    assert params["$orderby"] == "lastMessagePreview/createdDateTime desc"


@covers("chats list")
def test_chats_list_since_keeps_a_chat_with_no_preview_timestamp(invoke, graph):
    """An undatable chat says nothing about the boundary: it neither stops nor is dropped."""
    graph.get(f"{GRAPH}/v1.0/me/chats").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {"id": "19:a@thread.v2", "chatType": "group", "topic": "Undated"},
                    {
                        "id": "19:b@thread.v2",
                        "chatType": "group",
                        "topic": "Recent",
                        "lastMessagePreview": {"createdDateTime": "2026-08-31T09:00:00Z"},
                    },
                    {
                        "id": "19:c@thread.v2",
                        "chatType": "group",
                        "topic": "Old",
                        "lastMessagePreview": {"createdDateTime": "2026-07-01T09:00:00Z"},
                    },
                ]
            },
        )
    )
    r = invoke("chats", "list", "--since", "2026-08-01", "--json")
    assert r.exit_code == 0, r.stderr
    assert [c["id"] for c in json.loads(r.stdout)["items"]] == [
        "19:a@thread.v2",
        "19:b@thread.v2",
    ]


@covers("chats list")
def test_chats_list_since_keeps_a_chat_exactly_on_the_bound(invoke, graph):
    graph.get(f"{GRAPH}/v1.0/me/chats").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "19:on@thread.v2",
                        "chatType": "group",
                        "topic": "On the bound",
                        # 2026-08-01T00:00 in Europe/Warsaw is 2026-07-31T22:00Z.
                        "lastMessagePreview": {"createdDateTime": "2026-07-31T22:00:00Z"},
                    }
                ]
            },
        )
    )
    r = invoke("chats", "list", "--since", "2026-08-01", "--json")
    assert r.exit_code == 0, r.stderr
    assert [c["id"] for c in json.loads(r.stdout)["items"]] == ["19:on@thread.v2"]


@covers("chats list")
def test_chats_list_limit_zero_is_usage_error(invoke, graph):
    assert invoke("chats", "list", "--limit", "0").exit_code == 2
    assert graph.calls.call_count == 0


@covers("chats get")
@covers("chats members")
def test_chats_get_and_members(invoke, graph):
    routes = mock_graph(graph, "chats/get")
    r = invoke("chats", "get", CHAT)
    assert r.exit_code == 0, r.stderr
    assert routes[0].calls.last.request.url.params["$expand"] == "members"
    assert f"Chat id : {CHAT}" in r.stdout
    assert "Title   : Bob Example" in r.stdout
    assert "Type    : oneOnOne" in r.stdout

    member_routes = mock_graph(graph, "chats/members")
    r = invoke("chats", "members", CHAT)
    assert r.exit_code == 0, r.stderr
    assert member_routes[0].calls.last.request.url.query == b""
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["id", "name", "email", "userId"]
    assert "Bob Example" in r.stdout and BOB in r.stdout


@covers("chats messages")
def test_chats_messages_after_filter_and_order(invoke, graph):
    routes = mock_graph(graph, "chats/messages")
    r = invoke("chats", "messages", CHAT)
    assert r.exit_code == 0, r.stderr
    params = routes[0].calls.last.request.url.params
    assert params["$top"] == "50" and params["$orderby"] == "createdDateTime desc"
    assert "$filter" not in params
    lines = [line for line in r.stdout.splitlines() if line.strip()]
    assert lines[0].split() == ["created", "id", "from", "body"]
    assert lines[1].startswith("2026-08-30T13:00+02:00")  # oldest first
    assert lines[2].startswith("2026-08-31T10:15+02:00")
    assert "@Ada Example" in r.stdout and "[image: hostedContents/aWQ=]" in r.stdout
    doc = json.loads(invoke("chats", "messages", CHAT, "--json").stdout)
    assert [m["id"] for m in doc["items"]] == ["AAMk-chat-0003", "AAMk-chat-0002"]

    # A window switches both $filter and $orderby to lastModifiedDateTime: Graph filters chat
    # messages on that property, and ignores a $filter whose property $orderby does not name.
    after_routes = mock_graph(graph, "chats/messages_after")
    r = invoke("chats", "messages", CHAT, "--after", "2026-08-01")
    assert r.exit_code == 0, r.stderr
    params = after_routes[0].calls.last.request.url.params
    assert params["$filter"] == "lastModifiedDateTime gt 2026-08-01T00:00:00+02:00"
    assert params["$orderby"] == "lastModifiedDateTime desc"


@covers("chats messages")
def test_chats_messages_before_and_both_bounds(invoke, graph):
    route = graph.get(f"{GRAPH}/v1.0/chats/19%3Achat-0001%40thread.v2/messages").mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    r = invoke("chats", "messages", CHAT, "--before", "2026-08-31")
    assert r.exit_code == 0, r.stderr
    params = route.calls.last.request.url.params
    assert params["$filter"] == "lastModifiedDateTime lt 2026-08-31T23:59:59+02:00"
    assert params["$orderby"] == "lastModifiedDateTime desc"

    r = invoke("chats", "messages", CHAT, "--after", "2026-08-01", "--before", "2026-08-31")
    assert r.exit_code == 0, r.stderr
    assert route.calls.last.request.url.params["$filter"] == (
        "lastModifiedDateTime gt 2026-08-01T00:00:00+02:00 "
        "and lastModifiedDateTime lt 2026-08-31T23:59:59+02:00"
    )


@covers("chats messages")
def test_chats_messages_rejects_an_inverted_window(invoke, graph):
    r = invoke("chats", "messages", CHAT, "--after", "2026-08-31", "--before", "2026-08-01")
    assert r.exit_code == 2 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[USAGE]: --after must not be later than --before")


@covers("chats messages")
@pytest.mark.parametrize(
    "status,code,exit_code",
    [(404, "ErrorItemNotFound", 4), (403, "Forbidden", 3), (400, "BadRequest", 1)],
)
def test_chats_messages_error_exit_codes(invoke, graph, status, code, exit_code):
    graph.get(f"{CHAT_URL}/messages").mock(return_value=graph_error(status, code))
    r = invoke("chats", "messages", CHAT)
    assert r.exit_code == exit_code and r.stdout == ""
    assert r.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("chats messages")
def test_chats_chat_by_upn_resolves_one_on_one(invoke, graph):
    routes = mock_graph(graph, "chats/by_upn")
    r = invoke("chats", "messages", "bob@example.com")
    assert r.exit_code == 0, r.stderr
    assert routes[0].calls.last.request.url.params["$select"] == "id,displayName"
    assert routes[1].calls.last.request.url.params["$filter"] == "chatType eq 'oneOnOne'"
    assert routes[2].called
    bad = invoke("chats", "messages", "Team standup")
    assert bad.exit_code == 2
    assert bad.stderr.startswith("error[USAGE]: 'Team standup' is not a chat id or a UPN;")


@covers("chats send")
def test_chats_send_text(invoke, graph):
    route = graph.post(f"{CHAT_URL}/messages").mock(
        return_value=httpx.Response(201, json={"id": "AAMk-chat-0100", "chatId": CHAT})
    )
    r = invoke("chats", "send", CHAT, "--body", "On my way")
    assert r.exit_code == 0, r.stderr
    assert r.stdout == "Sent.\n"
    assert json.loads(route.calls.last.request.content) == {
        "body": {"contentType": "text", "content": "On my way"}
    }
    r = invoke("chats", "send", CHAT, "--body", "<p>Hi</p>", "--html", "--json")
    assert json.loads(r.stdout)["id"] == "AAMk-chat-0100"
    assert json.loads(route.calls.last.request.content)["body"]["contentType"] == "html"


@covers("chats send")
def test_chats_send_dry_run(invoke, graph):
    r = invoke("chats", "send", CHAT, "--body", "Hi", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout) == {
        "dryRun": True,
        "requests": [
            {
                "method": "POST",
                "url": f"{CHAT_URL}/messages",
                "headers": {"Content-Type": "application/json"},
                "body": {"body": {"contentType": "text", "content": "Hi"}},
            }
        ],
    }
    assert graph.calls.call_count == 0


@covers("chats dm")
def test_chats_dm_existing_chat(invoke, graph):
    routes = mock_graph(graph, "chats/dm_existing")
    send = graph.post(f"{CHAT_URL}/messages").mock(
        return_value=httpx.Response(201, json={"id": "AAMk-chat-0100", "chatId": CHAT})
    )
    r = invoke("chats", "dm", "bob@example.com", "--body", "Ping")
    assert r.exit_code == 0, r.stderr
    assert r.stdout == "Sent.\n"
    assert routes[0].calls.last.request.url.params["$select"] == "id,displayName"
    params = routes[1].calls.last.request.url.params
    assert params["$filter"] == "chatType eq 'oneOnOne'"
    assert params["$expand"] == "members" and params["$top"] == "50"
    assert json.loads(send.calls.last.request.content) == {
        "body": {"contentType": "text", "content": "Ping"}
    }


@covers("chats dm")
def test_chats_dm_creates_chat(invoke, graph):
    mock_graph(graph, "chats/dm_new")
    created = graph.post(f"{GRAPH}/v1.0/chats").mock(
        return_value=httpx.Response(201, json={"id": "19:chat-0009@thread.v2"})
    )
    send = graph.post(f"{GRAPH}/v1.0/chats/19%3Achat-0009%40thread.v2/messages").mock(
        return_value=httpx.Response(201, json={"id": "AAMk-chat-0200"})
    )
    r = invoke("chats", "dm", "bob@example.com", "--body", "Ping", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(created.calls.last.request.content) == {
        "chatType": "oneOnOne",
        "members": [bind(ME), bind(BOB)],
    }
    assert send.called
    doc = json.loads(r.stdout)
    assert doc["id"] == "AAMk-chat-0200" and doc["chatId"] == "19:chat-0009@thread.v2"


@covers("chats dm")
@pytest.mark.scopes(config.DEFAULT_SCOPES)
def test_chats_dm_create_requires_chat_create(invoke, graph):
    routes = mock_graph(graph, "chats/dm_new")
    r = invoke("chats", "dm", "bob@example.com", "--body", "Ping")
    assert r.exit_code == 3 and r.stdout == ""
    assert r.stderr.startswith("error[MISSING_SCOPE]: this command needs Chat.Create;")
    assert routes[0].called and routes[1].called
    assert graph.calls.call_count == 2  # the lookups only; no POST /chats


@covers("chats dm")
def test_chats_dm_dry_run_shows_both_steps(invoke, graph):
    r = invoke("chats", "dm", "bob@example.com", "--body", "Ping", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["dryRun"] is True
    assert [step["method"] for step in doc["requests"]] == ["POST", "POST"]
    assert doc["requests"][0]["url"] == f"{GRAPH}/v1.0/chats"
    assert doc["requests"][0]["note"] == "only when no 1:1 chat exists"
    assert doc["requests"][1]["url"] == f"{GRAPH}/v1.0/chats/{{chatId}}/messages"
    assert doc["requests"][1]["body"] == {"body": {"contentType": "text", "content": "Ping"}}
    assert graph.calls.call_count == 0


@covers("chats create")
def test_chats_create_group_and_one_on_one(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/chats").mock(
        return_value=httpx.Response(201, json={"id": "19:chat-0009@thread.v2", "chatType": "group"})
    )
    r = invoke(
        "chats",
        "create",
        "--members",
        "bob@example.com",
        "--members",
        "cleo@example.com",
        "--topic",
        "Launch plan",
    )
    assert r.exit_code == 0, r.stderr
    assert r.stdout == "Created chat 19:chat-0009@thread.v2.\n"
    assert json.loads(route.calls.last.request.content) == {
        "chatType": "group",
        "topic": "Launch plan",
        "members": [bind(ME), bind("bob@example.com"), bind("cleo@example.com")],
    }
    r = invoke("chats", "create", "--members", "bob@example.com", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(route.calls.last.request.content) == {
        "chatType": "oneOnOne",
        "members": [bind(ME), bind("bob@example.com")],
    }


@covers("chats create")
def test_chats_create_dry_run(invoke, graph):
    r = invoke("chats", "create", "--members", "bob@example.com", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["requests"] == [
        {
            "method": "POST",
            "url": f"{GRAPH}/v1.0/chats",
            "headers": {"Content-Type": "application/json"},
            "body": {"chatType": "oneOnOne", "members": [bind(ME), bind("bob@example.com")]},
        }
    ]
    assert graph.calls.call_count == 0
    bare = invoke("chats", "create", "--dry-run")
    assert bare.exit_code == 2
    assert bare.stderr.startswith("error[USAGE]: give at least one --members UPN")


@covers("chats create")
@pytest.mark.scopes(config.DEFAULT_SCOPES)
def test_chats_create_scope_gate(invoke, graph):
    r = invoke("chats", "create", "--members", "bob@example.com")
    assert r.exit_code == 3 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[MISSING_SCOPE]: this command needs Chat.Create;")


@covers("chats search")
def test_chats_search_labels_chat_and_channel_hits(invoke, graph):
    routes = mock_graph(graph, "chats/search")
    r = invoke("chats", "search", "budget")
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
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["id", "created", "from", "where", "summary"]
    assert "chat:19:chat-0001@thread.v2" in lines[1]
    assert f"channel:{TEAM}/{CHANNEL}" in lines[2]
    doc = json.loads(invoke("chats", "search", "budget", "--json").stdout)
    assert doc["count"] == 2
    assert doc["items"][0]["where"] == "chat:19:chat-0001@thread.v2"


@covers("chats search")
def test_chats_search_date_window_is_client_side(invoke, graph):
    mock_graph(graph, "chats/search")
    doc = json.loads(invoke("chats", "search", "budget", "--after", "2026-08-25", "--json").stdout)
    assert [h["id"] for h in doc["items"]] == ["AAMk-chat-0003"]
    doc = json.loads(invoke("chats", "search", "budget", "--before", "2026-08-25", "--json").stdout)
    assert [h["id"] for h in doc["items"]] == ["3"]


@covers("chats search")
def test_chats_search_all_pages_on_more_results(invoke, graph):
    routes = mock_graph(graph, "chats/search_paged")
    doc = json.loads(invoke("chats", "search", "budget", "--all", "--json").stdout)
    assert doc["count"] == 3
    assert routes[0].call_count == 2
    assert json.loads(routes[0].calls[1].request.content)["requests"][0]["from"] == 25


def test_shape_chat_hit_unit():
    from mgraphctl.graph.chats import shape_chat_hit

    shaped = shape_chat_hit(
        {
            "summary": "the  budget\nis ready",
            "resource": {
                "id": "AAMk-chat-0003",
                "createdDateTime": "2026-08-31T08:15:00Z",
                "chatId": CHAT,
                "from": {"user": {"displayName": "Bob Example"}},
                "webUrl": "https://teams.microsoft.com/l/message/x",
            },
        }
    )
    assert set(shaped) == {"id", "created", "from", "where", "summary", "webUrl"}
    assert shaped["id"] == "AAMk-chat-0003"
    assert shaped["created"] == "2026-08-31T08:15:00Z"
    assert shaped["from"] == "Bob Example"
    assert shaped["where"] == f"chat:{CHAT}"
    assert shaped["summary"] == "the budget is ready"
    assert shaped["webUrl"] == "https://teams.microsoft.com/l/message/x"

    channel = shape_chat_hit(
        {
            "summary": "notes",
            "resource": {
                "id": "3",
                "createdDateTime": "2026-08-20T10:00:00Z",
                "channelIdentity": {"teamId": TEAM, "channelId": CHANNEL},
            },
        }
    )
    assert channel["where"] == f"channel:{TEAM}/{CHANNEL}"
    assert channel["from"] == "" and channel["webUrl"] is None


@covers("chats hosted-content")
def test_hosted_content_triplet_and_url(invoke, graph, tmp_path, monkeypatch):
    triplet = graph.get(f"{CHAT_URL}/messages/AAMk-chat-0003/hostedContents/aWQ%3D/$value").mock(
        return_value=httpx.Response(200, content=PNG)
    )
    dest = tmp_path / "x.png"
    r = invoke(
        "chats",
        "hosted-content",
        CHAT,
        "AAMk-chat-0003",
        "aWQ=",
        "--output",
        str(dest),
    )
    assert r.exit_code == 0, r.stderr
    assert triplet.called and dest.read_bytes() == PNG
    assert r.stdout == f"Downloaded x.png (8 B) to {dest}\n"

    channel_url = (
        f"{GRAPH}/v1.0/teams/{TEAM}/channels/19%3Achannel-0001%40thread.tacv2"
        "/messages/1/hostedContents/aWQ=/$value"
    )
    verbatim = graph.get(channel_url).mock(return_value=httpx.Response(200, content=PNG))
    monkeypatch.chdir(tmp_path)
    r = invoke("chats", "hosted-content", channel_url, "--json")
    assert r.exit_code == 0, r.stderr
    assert verbatim.called
    doc = json.loads(r.stdout)
    assert doc == {"path": "teams_hosted_aWQ=.png", "bytes": 8}
    assert (tmp_path / "teams_hosted_aWQ=.png").read_bytes() == PNG


@covers("chats hosted-content")
@pytest.mark.scopes(["ChannelMessage.Read.All"])
def test_hosted_content_channel_url_does_not_need_chat_read(invoke, graph, monkeypatch, tmp_path):
    """The verb declares no scope; a channel target is gated on ChannelMessage.Read.All alone."""
    monkeypatch.chdir(tmp_path)
    channel_url = (
        f"{GRAPH}/v1.0/teams/{TEAM}/channels/19%3Achannel-0001%40thread.tacv2"
        "/messages/1/hostedContents/aWQ=/$value"
    )
    route = graph.get(channel_url).mock(return_value=httpx.Response(200, content=PNG))
    r = invoke("chats", "hosted-content", channel_url, "--json")
    assert r.exit_code == 0, r.stderr
    assert route.called and json.loads(r.stdout) == {"path": "teams_hosted_aWQ=.png", "bytes": 8}


@covers("chats hosted-content")
@pytest.mark.scopes(["ChannelMessage.Read.All"])
def test_hosted_content_chat_target_still_needs_chat_read(invoke, graph):
    r = invoke("chats", "hosted-content", CHAT, "AAMk-chat-0003", "aWQ=")
    assert r.exit_code == 3 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[MISSING_SCOPE]: this command needs Chat.Read;")


@covers("chats hosted-content")
@pytest.mark.scopes(["Chat.Read"])
def test_hosted_content_channel_url_needs_channel_scope(invoke, graph):
    channel_url = (
        f"{GRAPH}/v1.0/teams/{TEAM}/channels/19%3Achannel-0001%40thread.tacv2"
        "/messages/1/hostedContents/aWQ=/$value"
    )
    r = invoke("chats", "hosted-content", channel_url)
    assert r.exit_code == 3 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[MISSING_SCOPE]: this command needs ChannelMessage.Read.All;")


@covers("chats hosted-content")
@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.example/v1.0/chats/c/messages/1/hostedContents/aWQ=/$value",
        # The Graph host as userinfo, not as the authority.
        "https://graph.microsoft.com@attacker.example/v1.0/chats/c/messages/1"
        "/hostedContents/aWQ=/$value",
        # Right host, wrong scheme: the token must never travel in clear text.
        "http://graph.microsoft.com/v1.0/chats/c/messages/1/hostedContents/aWQ=/$value",
        # Right host and scheme, but not a hosted-contents address.
        "https://graph.microsoft.com/v1.0/me/messages",
    ],
)
def test_hosted_content_refuses_foreign_urls(invoke, graph, url):
    r = invoke("chats", "hosted-content", url)
    assert r.exit_code == 2 and r.stdout == ""
    assert graph.calls.call_count == 0
    assert r.stderr.startswith("error[USAGE]: ")


@covers("chats hosted-content")
def test_hosted_content_accepts_v1_and_beta_graph_urls(invoke, graph, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for base in (f"{GRAPH}/v1.0", f"{GRAPH}/beta"):
        url = f"{base}/chats/19%3Achat-0001%40thread.v2/messages/1/hostedContents/aWQ=/$value"
        route = graph.get(url).mock(return_value=httpx.Response(200, content=PNG))
        r = invoke("chats", "hosted-content", url, "--json")
        assert r.exit_code == 0, r.stderr
        assert route.called
        assert json.loads(r.stdout) == {"path": "teams_hosted_aWQ=.png", "bytes": 8}


@covers("chats create")
def test_chats_create_escapes_apostrophes_in_the_bind(invoke, graph):
    r = invoke("chats", "create", "--members", "o'brien@example.com", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    members = json.loads(r.stdout)["requests"][0]["body"]["members"]
    assert members[1]["user@odata.bind"] == f"{GRAPH}/v1.0/users('o''brien@example.com')"
    assert graph.calls.call_count == 0


@covers("chats hosted-content")
def test_hosted_content_needs_three_arguments(invoke, graph):
    r = invoke("chats", "hosted-content", CHAT, "AAMk-chat-0003")
    assert r.exit_code == 2 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[USAGE]: give CHAT MSGID HCID, or one hostedContents URL")


def test_chats_group_help_exits_zero(invoke):
    assert invoke("chats").exit_code == 0
