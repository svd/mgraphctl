"""The parity goal's end-to-end sweep, run offline through the fixture transport.

One test per hop, sharing a fixture directory built here rather than checked in, so the
requests the CLI actually makes are what the fixtures are keyed by (spec §5.8).
"""

import json

import pytest

from mgraphctl import fixtures

TEAM = "11111111-1111-4111-8111-111111111111"
CHANNEL = "19:channel-0001@thread.tacv2"
CHAT = "19:chat-0001@thread.v2"
MAIL_SELECT = (
    "id,subject,from,toRecipients,ccRecipients,receivedDateTime,isRead,hasAttachments,"
    "importance,bodyPreview,conversationId,webLink,inferenceClassification"
)
EVENT_SELECT = (
    "id,subject,start,end,location,organizer,attendees,isOnlineMeeting,onlineMeeting,"
    "isCancelled,isAllDay,showAs,responseStatus,seriesMasterId,bodyPreview,webLink"
)


def _put(dir_, key, body):
    """Record one replayable response under the key the CLI will ask for."""
    path = fixtures.fixture_path(dir_, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "key": key,
                "responses": [
                    {"status": 200, "headers": {"content-type": "application/json"}, "body": body}
                ],
            }
        )
    )


def _put_text(dir_, key, text):
    path = fixtures.fixture_path(dir_, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "key": key,
                "responses": [
                    {"status": 200, "headers": {"content-type": "text/vtt"}, "body_text": text}
                ],
            }
        )
    )


def _message(mid, received, **over):
    return {
        "id": mid,
        "subject": "Budget",
        "isRead": True,
        "receivedDateTime": received,
        "from": {"emailAddress": {"name": "Ada Example", "address": "a@example.com"}},
        **over,
    }


@pytest.fixture
def sweep(tmp_path, monkeypatch):
    """A fixture directory the CLI replays from, with every hop of the sweep recorded."""
    dir_ = tmp_path / "fixtures"
    dir_.mkdir()
    monkeypatch.setenv("MGRAPHCTL_FIXTURE_DIR", str(dir_))

    # mail: the KQL bound is day-granular, so the 08:00 local message comes back and has to be
    # dropped here; 501 more take the page past the 500-item cap.
    early = _message("m-early", "2026-08-31T06:00:00Z")
    late = [_message(f"m-{i}", "2026-08-31T12:00:00Z") for i in range(501)]
    _put(
        dir_,
        "GET /v1.0/me/mailFolders/inbox/messages?"
        f"$select={MAIL_SELECT.replace(',', '%2C')}"
        "&$search=%22from%3Aa%40example.com%20AND%20received%3E%3D2026-08-31%22&$top=25",
        {"value": [early, *late]},
    )
    _put(
        dir_,
        "GET /v1.0/me/chats?$expand=members%2ClastMessagePreview"
        "&$orderby=lastMessagePreview%2FcreatedDateTime%20desc"
        "&$select=id%2Ctopic%2CchatType%2ClastUpdatedDateTime%2Cviewpoint%2CwebUrl&$top=50",
        {
            "value": [
                {
                    "id": CHAT,
                    "chatType": "oneOnOne",
                    "lastMessagePreview": {"createdDateTime": "2026-08-31T09:00:00Z"},
                },
                {
                    "id": "19:chat-0002@thread.v2",
                    "chatType": "group",
                    "topic": "Launch",
                    "lastMessagePreview": {"createdDateTime": "2026-08-30T09:00:00Z"},
                },
                {  # older than --since: ends the fetch, and is dropped
                    "id": "19:chat-0003@thread.v2",
                    "chatType": "group",
                    "topic": "Archive",
                    "lastMessagePreview": {"createdDateTime": "2026-07-01T09:00:00Z"},
                },
            ]
        },
    )
    _put(
        dir_,
        "GET /v1.0/chats/19%3Achat-0001%40thread.v2/messages"
        "?$orderby=lastModifiedDateTime%20desc"
        "&$filter=lastModifiedDateTime%20gt%202026-08-29T00%3A00%3A00%2B02%3A00"
        "%20and%20lastModifiedDateTime%20lt%202026-08-31T23%3A59%3A00%2B02%3A00&$top=50",
        {
            "value": [
                {
                    "id": "cm-2",
                    "messageType": "message",
                    "createdDateTime": "2026-08-31T09:00:00Z",
                    "body": {"contentType": "text", "content": "later"},
                },
                {
                    "id": "cm-1",
                    "messageType": "message",
                    "createdDateTime": "2026-08-30T09:00:00Z",
                    "body": {"contentType": "text", "content": "earlier"},
                },
            ]
        },
    )
    _put(
        dir_,
        f"GET /v1.0/teams/{TEAM}/channels/19%3Achannel-0001%40thread.tacv2/messages?$top=50",
        {
            "value": [
                {
                    "id": "chan-2",
                    "messageType": "message",
                    "lastModifiedDateTime": "2026-08-31T09:00:00Z",
                    "body": {"contentType": "text", "content": "inside"},
                },
                {  # before --after: ends the fetch, and is dropped
                    "id": "chan-1",
                    "messageType": "message",
                    "lastModifiedDateTime": "2026-07-01T09:00:00Z",
                    "body": {"contentType": "text", "content": "outside"},
                },
            ]
        },
    )
    _put(
        dir_,
        "GET /v1.0/me/calendarView?startDateTime=2026-08-31T09%3A00%3A00%2B02%3A00"
        "&endDateTime=2026-08-31T18%3A00%3A00%2B02%3A00"
        f"&$select={EVENT_SELECT.replace(',', '%2C')}"
        "&$orderby=start%2FdateTime&$top=50",
        {
            "value": [
                {
                    "id": "ev-1",
                    "subject": "Standup",
                    "start": {"dateTime": "2026-08-31T09:30:00.0000000", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-08-31T09:45:00.0000000", "timeZone": "UTC"},
                }
            ]
        },
    )
    _put_text(
        dir_,
        "GET /v1.0/me/onlineMeetings/MSpk-1/transcripts/tr-1/content?$format=text%2Fvtt",
        "WEBVTT\n\n"
        "1\n00:00:01.000 --> 00:00:04.000\n<v Ada Example>Hello there</v>\n\n"
        "2\n00:00:04.000 --> 00:00:07.000\n<v Ada Example>and one more thing</v>\n\n"
        "3\n00:00:07.000 --> 00:00:10.000\n<v Bob Example>Agreed</v>\n",
    )
    return dir_


def test_sweep_status_answers_offline(invoke, sweep):
    r = invoke("status", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["loggedIn"] is True


def test_sweep_mail_reports_window_cap_and_the_filtered_page(invoke, sweep):
    r = invoke(
        "mail", "list", "--from", "a@example.com", "--after", "2026-08-31T09:00", "--all", "--json"
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["window"] == {"after": "2026-08-31T09:00:00+02:00", "before": None}
    assert doc["cap"] == 500
    # 500 fetched under the cap, one of them before the bound the day-granular KQL kept.
    assert doc["fetched"] == 500 and doc["count"] == 499
    assert doc["truncated"] is True
    assert all(m["id"] != "m-early" for m in doc["items"])


def test_sweep_chats_list_since_stops_and_reports_the_window(invoke, sweep):
    r = invoke("chats", "list", "--since", "2026-08-29T00:00", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["window"] == {"after": "2026-08-29T00:00:00+02:00", "before": None}
    assert [c["id"] for c in doc["items"]] == [CHAT, "19:chat-0002@thread.v2"]
    assert doc["count"] == 2 and doc["fetched"] == 3
    # Reaching the far edge of the window is not a truncation.
    assert doc["truncated"] is False


def test_sweep_chat_messages_window_is_server_side(invoke, sweep):
    r = invoke(
        "chats",
        "messages",
        CHAT,
        "--after",
        "2026-08-29T00:00",
        "--before",
        "2026-08-31T23:59",
        "--all",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["window"] == {
        "after": "2026-08-29T00:00:00+02:00",
        "before": "2026-08-31T23:59:00+02:00",
    }
    # Graph filtered it, so nothing was dropped here.
    assert doc["count"] == 2 and doc["fetched"] == 2 and doc["truncated"] is False
    assert doc["query"]["$filter"].startswith("lastModifiedDateTime gt ")
    # Every message can be routed back to its chat.
    assert {m["chatId"] for m in doc["items"]} == {CHAT}


def test_sweep_channel_messages_window_is_client_side(invoke, sweep):
    r = invoke(
        "teams",
        "channel",
        "messages",
        f"id:{TEAM}",
        f"id:{CHANNEL}",
        "--after",
        "2026-08-29T00:00",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["window"] == {"after": "2026-08-29T00:00:00+02:00", "before": None}
    # No $filter is sent; the window is applied after paging, so fetched exceeds count.
    assert "$filter" not in doc["query"]
    assert [m["id"] for m in doc["items"]] == ["chan-2"]
    assert doc["count"] == 1 and doc["fetched"] == 2 and doc["truncated"] is False
    assert doc["items"][0]["teamId"] == TEAM and doc["items"][0]["channelId"] == CHANNEL


def test_sweep_calendar_list_reports_its_window(invoke, sweep):
    r = invoke(
        "calendar", "list", "--after", "2026-08-31T09:00", "--before", "2026-08-31T18:00", "--json"
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["window"] == {
        "after": "2026-08-31T09:00:00+02:00",
        "before": "2026-08-31T18:00:00+02:00",
    }
    assert doc["count"] == 1 and doc["fetched"] == 1 and doc["cap"] == 50


def test_sweep_transcript_merges_consecutive_cues_from_one_speaker(invoke, sweep):
    r = invoke("meetings", "transcript", "MSpk-1", "tr-1", "--speakers")
    assert r.exit_code == 0, r.stderr
    assert r.stdout == (
        "**Ada Example:** Hello there and one more thing\n\n**Bob Example:** Agreed\n"
    )
