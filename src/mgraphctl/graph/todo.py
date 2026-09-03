"""Graph operations for Microsoft To Do (spec §8.15).

Pure: client and parameters in, Graph dicts / `PageResult` / `Plan` out.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mgraphctl import odata, render
from mgraphctl.errors import UsageError
from mgraphctl.http import GraphClient, PageResult, Plan, PlannedRequest
from mgraphctl.resolve import looks_like_id, pick_unique, split_id_prefix

JSON = {"Content-Type": "application/json"}
LIST_PAGE = 100
TASK_PAGE = 100
CAP_TASKS = 500
MESSAGE_SELECT = "subject,webLink,bodyPreview,from,receivedDateTime"
IMPORTANCE_VALUES = ("low", "normal", "high")
STATUS_VALUES = ("notStarted", "inProgress", "completed", "waitingOnOthers", "deferred")
WELLKNOWN_ALIASES = {"defaultlist": "defaultList", "flaggedemails": "flaggedEmails"}


def _run(client: GraphClient, plan: Plan) -> Any:
    """Execute every step of `plan` in order, returning the last step's result."""
    result: Any = None
    for step in plan:
        result = client.execute(step)
    return result


# --------------------------------------------------------------------------- reads


def list_lists(client: GraphClient) -> list[dict]:
    payload = client.get("/me/todo/lists", params={"$top": LIST_PAGE}) or {}
    return payload.get("value") or []


def resolve_list(client: GraphClient, value: str) -> dict:
    """A list id, well-known name (`defaultList`/`flaggedEmails`), or `displayName` (§6.6)."""
    if looks_like_id(value, "todo_list"):
        bare, _ = split_id_prefix(value)
        return {"id": bare}
    lists_ = list_lists(client)
    wellknown = WELLKNOWN_ALIASES.get(value.strip().lower())
    if wellknown is not None:
        return pick_unique(lists_, "wellknownListName", wellknown, what="list")
    return pick_unique(lists_, "displayName", value, what="list")


def list_tasks(
    client: GraphClient,
    list_id: str,
    *,
    include_completed: bool = False,
    limit: int | None,
    all_: bool,
) -> PageResult:
    params: dict[str, object] = {}
    if not include_completed:
        params["$filter"] = "status ne 'completed'"
    path = odata.p("me", "todo", "lists", list_id, "tasks")
    return client.paginate(
        path,
        params=params,
        outlook_tz=True,
        limit=limit,
        all_=all_,
        cap=CAP_TASKS,
        page_size=TASK_PAGE,
    )


def get_task(client: GraphClient, list_id: str, task_id: str) -> dict:
    path = odata.p("me", "todo", "lists", list_id, "tasks", task_id)
    return client.get(path, params={"$expand": "checklistItems,linkedResources"}, outlook_tz=True)


# --------------------------------------------------------------------------- writes


def task_body(
    *,
    title: str | None = None,
    due: datetime | None = None,
    body_text: str | None = None,
    importance: str | None = None,
    reminder: datetime | None = None,
    start: datetime | None = None,
    status: str | None = None,
    tz: str,
) -> dict:
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if body_text is not None:
        body["body"] = {"content": body_text, "contentType": "text"}
    if importance is not None:
        if importance not in IMPORTANCE_VALUES:
            raise UsageError("USAGE", "--importance must be low, normal or high")
        body["importance"] = importance
    if due is not None:
        body["dueDateTime"] = render.to_graph_dtz(due, tz)
    if reminder is not None:
        body["reminderDateTime"] = render.to_graph_dtz(reminder, tz)
        body["isReminderOn"] = True
    if start is not None:
        body["startDateTime"] = render.to_graph_dtz(start, tz)
    if status is not None:
        if status not in STATUS_VALUES:
            raise UsageError("USAGE", f"--status must be one of {', '.join(STATUS_VALUES)}")
        body["status"] = status
    return body


def plan_create(client: GraphClient, list_id: str, **opts: Any) -> Plan:
    body = task_body(**opts)
    url = client.url(odata.p("me", "todo", "lists", list_id, "tasks"))
    return [PlannedRequest("POST", url, dict(JSON), body)]


def run_create(client: GraphClient, list_id: str, **opts: Any) -> dict:
    return _run(client, plan_create(client, list_id, **opts))


def plan_update(client: GraphClient, list_id: str, task_id: str, **opts: Any) -> Plan:
    body = task_body(**opts)
    url = client.url(odata.p("me", "todo", "lists", list_id, "tasks", task_id))
    return [PlannedRequest("PATCH", url, dict(JSON), body)]


def run_update(client: GraphClient, list_id: str, task_id: str, **opts: Any) -> dict:
    return _run(client, plan_update(client, list_id, task_id, **opts))


def plan_complete(client: GraphClient, list_id: str, task_id: str, *, tz: str) -> Plan:
    return plan_update(client, list_id, task_id, status="completed", tz=tz)


def run_complete(client: GraphClient, list_id: str, task_id: str, *, tz: str) -> dict:
    return _run(client, plan_complete(client, list_id, task_id, tz=tz))


def plan_delete(client: GraphClient, list_id: str, task_id: str) -> Plan:
    url = client.url(odata.p("me", "todo", "lists", list_id, "tasks", task_id))
    return [PlannedRequest("DELETE", url, {}, None, expect="none")]


def run_delete(client: GraphClient, list_id: str, task_id: str) -> None:
    _run(client, plan_delete(client, list_id, task_id))


def fetch_message_for_task(client: GraphClient, msg_id: str) -> dict:
    """A minimal mail message view for `from-mail` (spec §8.15). Not shared with `graph/mail.py`."""
    path = odata.p("me", "messages", msg_id)
    return client.get(path, params={"$select": MESSAGE_SELECT})


def plan_from_mail(
    client: GraphClient,
    list_id: str,
    message: dict,
    *,
    title: str | None = None,
    due: datetime | None = None,
    importance: str | None = None,
    tz: str,
) -> Plan:
    subject = message.get("subject") or ""
    sender = render.fmt_person(message.get("from"))
    received = message.get("receivedDateTime")
    received_str = render.fmt_dt(received, tz) if received else "N/A"
    content = f"From: {sender}\nReceived: {received_str}\n\n{message.get('bodyPreview') or ''}"
    body: dict[str, Any] = {
        "title": title or subject,
        "body": {"content": content, "contentType": "text"},
        "linkedResources": [
            {
                "webUrl": message.get("webLink"),
                "applicationName": "Microsoft Outlook",
                "displayName": subject,
                "externalId": message.get("id"),
            }
        ],
    }
    if due is not None:
        body["dueDateTime"] = render.to_graph_dtz(due, tz)
    if importance is not None:
        if importance not in IMPORTANCE_VALUES:
            raise UsageError("USAGE", "--importance must be low, normal or high")
        body["importance"] = importance
    url = client.url(odata.p("me", "todo", "lists", list_id, "tasks"))
    return [PlannedRequest("POST", url, dict(JSON), body)]


def run_from_mail(client: GraphClient, list_id: str, message: dict, **opts: Any) -> dict:
    return _run(client, plan_from_mail(client, list_id, message, **opts))
