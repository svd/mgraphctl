"""CLI tests for the mailbox noun (spec §8.3)."""

import json
from datetime import datetime

import httpx
import pytest

from helpers import GRAPH, covers, mock_graph
from mgraphctl import render

SETTINGS = f"{GRAPH}/v1.0/me/mailboxSettings"
INBOX = f"{GRAPH}/v1.0/me/mailFolders/inbox/messages"
LIST_SELECT = (
    "id,subject,from,toRecipients,ccRecipients,receivedDateTime,isRead,hasAttachments,"
    "importance,bodyPreview,conversationId,webLink,inferenceClassification"
)


@pytest.fixture
def frozen_now(monkeypatch):
    """`-30d` and friends resolve against a fixed 2026-09-02 12:00 local."""
    monkeypatch.setattr(render, "_now", lambda zone: datetime(2026, 9, 2, 12, 0, tzinfo=zone))


# --------------------------------------------------------------------------- settings


@covers("mailbox settings")
def test_mailbox_settings(invoke, graph):
    routes = mock_graph(graph, "mailbox/settings")
    result = invoke("mailbox", "settings")
    assert result.exit_code == 0, result.stderr
    assert "Time zone         : Central European Standard Time\n" in result.stdout
    assert "Language          : English (United Kingdom)\n" in result.stdout
    assert "Working hours     : Mon,Tue,Wed,Thu,Fri 08:00-17:00 (Europe/Warsaw)\n" in result.stdout
    assert "Automatic replies : disabled\n" in result.stdout
    assert routes[0].called and result.stderr == ""


@covers("mailbox settings")
def test_mailbox_settings_json_is_raw_object(invoke, graph):
    mock_graph(graph, "mailbox/settings")
    result = invoke("mailbox", "settings", "--json")
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["timeZone"] == "Central European Standard Time"
    assert doc["automaticRepliesSetting"]["status"] == "disabled"


# --------------------------------------------------------------------------- oof get


@covers("mailbox oof get")
def test_mailbox_oof_get(invoke, graph):
    mock_graph(graph, "mailbox/oof")
    result = invoke("mailbox", "oof", "get")
    assert result.exit_code == 0, result.stderr
    assert "Status            : scheduled\n" in result.stdout
    assert "External audience : contactsOnly\n" in result.stdout
    assert "Start             : 2026-09-10T08:00+02:00\n" in result.stdout
    assert "End               : 2026-09-12T18:00+02:00\n" in result.stdout
    assert "Internal reply\nAway until Monday." in result.stdout
    result = invoke("mailbox", "oof", "get", "--json")
    assert json.loads(result.stdout)["externalAudience"] == "contactsOnly"


# --------------------------------------------------------------------------- oof set


@covers("mailbox oof set")
def test_mailbox_oof_set_scheduled_external_contacts(invoke, graph):
    route = graph.patch(SETTINGS).mock(
        return_value=httpx.Response(200, json={"automaticRepliesSetting": {"status": "scheduled"}})
    )
    result = invoke(
        "mailbox",
        "oof",
        "set",
        "--message",
        "Away",
        "--start",
        "2026-09-10",
        "--end",
        "2026-09-12",
        "--external",
        "contacts",
    )
    assert result.exit_code == 0, result.stderr
    assert json.loads(route.calls.last.request.content) == {
        "automaticRepliesSetting": {
            "status": "scheduled",
            "externalAudience": "contactsOnly",
            "scheduledStartDateTime": {
                "dateTime": "2026-09-10T00:00:00",
                "timeZone": "Europe/Warsaw",
            },
            "scheduledEndDateTime": {
                "dateTime": "2026-09-12T23:59:59",
                "timeZone": "Europe/Warsaw",
            },
            "internalReplyMessage": "<p>Away</p>",
            "externalReplyMessage": "<p>Away</p>",
        }
    }
    assert result.stdout == "Automatic replies updated.\n"


@covers("mailbox oof set")
def test_mailbox_oof_set_always_and_internal_only(invoke, graph):
    route = graph.patch(SETTINGS).mock(return_value=httpx.Response(200, json={}))
    result = invoke(
        "mailbox",
        "oof",
        "set",
        "--message",
        "Away",
        "--external-message",
        "Out of office",
        "--internal-only",
    )
    assert result.exit_code == 0, result.stderr
    assert json.loads(route.calls.last.request.content) == {
        "automaticRepliesSetting": {
            "status": "alwaysEnabled",
            "externalAudience": "none",
            "internalReplyMessage": "<p>Away</p>",
            "externalReplyMessage": "<p>Out of office</p>",
        }
    }


@covers("mailbox oof set")
def test_mailbox_oof_set_clear(invoke, graph):
    route = graph.patch(SETTINGS).mock(return_value=httpx.Response(200, json={}))
    assert invoke("mailbox", "oof", "set", "--clear").exit_code == 0
    assert json.loads(route.calls.last.request.content) == {
        "automaticRepliesSetting": {"status": "disabled"}
    }


@covers("mailbox oof set")
def test_mailbox_oof_set_requires_message_unless_clear(invoke, graph):
    result = invoke("mailbox", "oof", "set", "--start", "2026-09-10", "--end", "2026-09-12")
    assert result.exit_code == 2 and graph.calls.call_count == 0
    assert result.stderr.startswith("error[USAGE]: --message is required unless --clear")
    result = invoke("mailbox", "oof", "set", "--message", "Away", "--start", "2026-09-10")
    assert result.exit_code == 2 and graph.calls.call_count == 0
    assert "--start and --end go together" in result.stderr
    result = invoke("mailbox", "oof", "set", "--message", "Away", "--external", "everyone")
    assert result.exit_code == 2 and graph.calls.call_count == 0
    assert result.stderr.startswith("error[USAGE]: --external must be one of")


@covers("mailbox oof set")
def test_mailbox_oof_set_dry_run(invoke, graph):
    result = invoke("mailbox", "oof", "set", "--message", "Away", "--dry-run", "--json")
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["requests"] == [
        {
            "method": "PATCH",
            "url": SETTINGS,
            "headers": {"Content-Type": "application/json"},
            "body": {
                "automaticRepliesSetting": {
                    "status": "alwaysEnabled",
                    "externalAudience": "all",
                    "internalReplyMessage": "<p>Away</p>",
                    "externalReplyMessage": "<p>Away</p>",
                }
            },
        }
    ]
    assert graph.calls.call_count == 0


@covers("mailbox oof set")
@pytest.mark.scopes(["Mail.Read", "MailboxSettings.Read"])
def test_mailbox_oof_set_missing_scope(invoke, graph):
    result = invoke("mailbox", "oof", "set", "--message", "Away")
    assert result.exit_code == 3 and graph.calls.call_count == 0
    assert result.stderr.startswith(
        "error[MISSING_SCOPE]: this command needs MailboxSettings.ReadWrite; "
        "the current token has MailboxSettings.Read\n"
    )


# --------------------------------------------------------------------------- focused


@covers("mailbox focused")
def test_mailbox_focused_filter(invoke, graph, frozen_now):
    routes = mock_graph(graph, "mailbox/focused")
    result = invoke("mailbox", "focused", "--json")
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert set(doc) == {"items", "count", "fetched", "cap", "truncated", "query", "window"}
    assert doc["count"] == 1 and doc["items"][0]["id"] == "AAMk-msg-0001"
    request = routes[0].calls.last.request
    assert request.headers["Prefer"] == 'outlook.timezone="Europe/Warsaw"'
    assert request.url.params["$select"] == LIST_SELECT


@covers("mailbox focused")
def test_mailbox_focused_other_and_limit(invoke, graph, frozen_now):
    route = graph.get(INBOX).mock(return_value=httpx.Response(200, json={"value": []}))
    result = invoke("mailbox", "focused", "--other", "--after", "2026-08-01")
    assert result.exit_code == 0, result.stderr
    params = route.calls.last.request.url.params
    assert params["$filter"] == (
        "receivedDateTime ge 2026-08-01T00:00:00+02:00 and inferenceClassification eq 'other'"
    )
    assert params["$orderby"] == "receivedDateTime desc" and params["$top"] == "50"
    assert result.stdout == "No results.\n"


@covers("mailbox focused")
def test_mailbox_focused_text_columns(invoke, graph, frozen_now):
    mock_graph(graph, "mailbox/focused")
    result = invoke("mailbox", "focused")
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["id", "received", "flags", "from", "subject"]
    assert "AAMk-msg-0001" in lines[1] and "*A!" in lines[1]


# --------------------------------------------------------------------------- help


def test_mailbox_group_help(invoke):
    result = invoke("mailbox")
    assert result.exit_code == 0 and "Usage:" in result.stdout
    assert "settings" in result.stdout and "focused" in result.stdout
    result = invoke("mailbox", "oof")
    assert result.exit_code == 0 and "Usage:" in result.stdout
