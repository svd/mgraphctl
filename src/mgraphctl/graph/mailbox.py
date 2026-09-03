"""Graph operations for mailbox settings, automatic replies and the focused inbox (spec §8.3).

Pure: client and parameters in, Graph dicts / `PageResult` / `Plan` out.
"""

from __future__ import annotations

from datetime import datetime

from mgraphctl.graph import mail
from mgraphctl.html import text_to_html
from mgraphctl.http import GraphClient, PageResult, Plan, PlannedRequest
from mgraphctl.render import to_graph_dtz

SETTINGS_PATH = "/me/mailboxSettings"
OOF_PATH = "/me/mailboxSettings/automaticRepliesSetting"
FOCUSED_PATH = "/me/mailFolders/inbox/messages"

# `--external` values → the Graph `externalAudience` enum (spec §8.3 `oof set`).
AUDIENCE = {"all": "all", "contacts": "contactsOnly", "none": "none"}


def get_settings(client: GraphClient) -> dict:
    return client.get(SETTINGS_PATH)


def get_oof(client: GraphClient) -> dict:
    return client.get(OOF_PATH)


def plan_set_oof(
    client: GraphClient,
    *,
    message: str | None,
    external_message: str | None,
    start: datetime | None,
    end: datetime | None,
    audience: str,
    clear: bool,
    tz: str,
) -> Plan:
    """`scheduled` when both ends are given, `alwaysEnabled` otherwise, `disabled` for --clear."""
    if clear:
        setting: dict[str, object] = {"status": "disabled"}
    else:
        setting = {
            "status": "scheduled" if start and end else "alwaysEnabled",
            "externalAudience": audience,
        }
        if start and end:
            setting["scheduledStartDateTime"] = to_graph_dtz(start, tz)
            setting["scheduledEndDateTime"] = to_graph_dtz(end, tz)
        setting["internalReplyMessage"] = text_to_html(message or "")
        setting["externalReplyMessage"] = text_to_html(external_message or message or "")
    return [
        PlannedRequest(
            "PATCH",
            client.url(SETTINGS_PATH),
            dict(mail.JSON),
            {"automaticRepliesSetting": setting},
        )
    ]


def list_focused(
    client: GraphClient, *, other: bool, after: datetime, limit: int | None, all_: bool
) -> PageResult:
    """Inbox messages Outlook classified as focused (or `--other`), newest first.

    `receivedDateTime` leads the filter so Graph can serve the `$orderby` from the same index.
    """
    classification = "other" if other else "focused"
    params = {
        "$select": mail.LIST_SELECT,
        "$filter": (
            f"receivedDateTime ge {after.isoformat()} "
            f"and inferenceClassification eq '{classification}'"
        ),
        "$orderby": "receivedDateTime desc",
    }
    return client.paginate(
        FOCUSED_PATH,
        params=params,
        outlook_tz=True,
        limit=limit,
        all_=all_,
        cap=mail.CAP_LIST,
        page_size=mail.PAGE_FILTER,
    )
