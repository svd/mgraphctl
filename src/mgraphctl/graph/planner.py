"""Graph operations for Planner plans and tasks (spec §8.14).

Pure: client and parameters in, Graph dicts / `Plan` out. Planner paths carry no OData query
parameters (spec §8.14); slicing (`--limit`) and filtering (bucket, completed) happen client-side
on values already returned by Graph. `list_plans` and `my_tasks` annotate merged items with
underscore-prefixed keys (`_groupName`, `_planTitle`, `_bucketName`) used only by text-mode
columns; JSON callers get them too since `render.emit` serialises `ListResult.items` unchanged.
"""

from __future__ import annotations

from typing import Any

from mgraphctl import odata
from mgraphctl.errors import GraphError, MsgraphError, UsageError
from mgraphctl.graph import users
from mgraphctl.http import BatchRequest, GraphClient, Plan, PlannedRequest
from mgraphctl.render import to_iso_offset
from mgraphctl.resolve import looks_like_id, pick_unique, split_id_prefix

JSON = {"Content-Type": "application/json"}
MY_TASKS_PLAN_TITLE_CAP = 20
PERCENT_VALUES = (0, 50, 100)


def _run(client: GraphClient, plan: Plan) -> Any:
    """Execute every step of `plan` in order, returning the last step's result."""
    result: Any = None
    for step in plan:
        result = client.execute(step)
    return result


# --------------------------------------------------------------------------- reads


def list_plans(client: GraphClient) -> list[dict]:
    """Plans the signed-in user owns, plus every plan of a group they belong to (§8.14).

    `GET /me/planner/plans` ∪ (for each unified group from `users.list_unified_groups`) a
    `$batch` of `GET /groups/{id}/planner/plans`, deduped by id. Plans found only via a group
    are annotated with `_groupName` (text column only); the owned list is authoritative and
    keeps no `_groupName`, but a plan seen in more than one place still gets one if a group
    supplied it.
    """
    own = client.get("/me/planner/plans") or {}
    merged: dict[str, dict] = {item["id"]: item for item in own.get("value") or []}
    groups = users.list_unified_groups(client)
    if groups:
        requests = [
            BatchRequest(
                id=str(i), method="GET", url=odata.p("groups", g["id"], "planner", "plans")
            )
            for i, g in enumerate(groups, 1)
        ]
        responses = client.batch(requests)
        for group, response in zip(groups, responses, strict=True):
            if response.error is not None:
                raise response.error
            for item in (response.body or {}).get("value") or []:
                existing = merged.get(item["id"])
                if existing is not None:
                    existing.setdefault("_groupName", group.get("displayName"))
                else:
                    merged[item["id"]] = {**item, "_groupName": group.get("displayName")}
    return list(merged.values())


def resolve_plan(client: GraphClient, value: str) -> dict:
    """A plan id, or `title` looked up among `list_plans` (§6.6)."""
    if looks_like_id(value, "planner"):
        bare, _ = split_id_prefix(value)
        return {"id": bare}
    return pick_unique(list_plans(client), "title", value, what="plan")


def get_plan(client: GraphClient, plan_id: str) -> dict:
    """`{...plan, "details": {...}}` (spec §8.14 `plan`)."""
    plan_obj = client.get(odata.p("planner", "plans", plan_id))
    details = client.get(odata.p("planner", "plans", plan_id, "details"))
    return {**plan_obj, "details": details}


def list_buckets(client: GraphClient, plan_id: str) -> list[dict]:
    payload = client.get(odata.p("planner", "plans", plan_id, "buckets")) or {}
    return payload.get("value") or []


def resolve_bucket(client: GraphClient, plan_id: str, value: str) -> dict:
    """A bucket id, or `name` looked up among the plan's buckets (§6.6)."""
    if looks_like_id(value, "planner"):
        bare, _ = split_id_prefix(value)
        return {"id": bare}
    return pick_unique(list_buckets(client, plan_id), "name", value, what="bucket")


def resolve_bucket_for_task(client: GraphClient, task_id: str, value: str) -> dict:
    """Resolve a `--bucket` name on `update`, where the plan is not already known.

    An id-shaped value never needs the task's plan; a name does, so this fetches the task
    first to learn `planId` before delegating to `resolve_bucket`.
    """
    if looks_like_id(value, "planner"):
        bare, _ = split_id_prefix(value)
        return {"id": bare}
    current = client.get(odata.p("planner", "tasks", task_id))
    return resolve_bucket(client, current["planId"], value)


def list_tasks(
    client: GraphClient,
    plan_id: str,
    *,
    bucket_id: str | None = None,
    include_completed: bool = False,
    limit: int = 50,
) -> list[dict]:
    """A plan's tasks, hiding completed ones and naming buckets, sliced to `limit` (§8.14)."""
    payload = client.get(odata.p("planner", "plans", plan_id, "tasks")) or {}
    items = payload.get("value") or []
    if not include_completed:
        items = [t for t in items if t.get("percentComplete") != 100]
    if bucket_id is not None:
        items = [t for t in items if t.get("bucketId") == bucket_id]
    names = {b["id"]: b.get("name") for b in list_buckets(client, plan_id)}
    for item in items:
        item["_bucketName"] = names.get(item.get("bucketId"), "")
    return items[:limit]


def my_tasks(
    client: GraphClient, *, include_completed: bool = False, limit: int = 50
) -> list[dict]:
    """The signed-in user's tasks across every plan, annotated with plan titles (§8.14 `--my`)."""
    payload = client.get("/me/planner/tasks") or {}
    items = payload.get("value") or []
    if not include_completed:
        items = [t for t in items if t.get("percentComplete") != 100]
    plan_ids = list(dict.fromkeys(t["planId"] for t in items if t.get("planId")))
    plan_ids = plan_ids[:MY_TASKS_PLAN_TITLE_CAP]
    titles: dict[str, str] = {}
    if plan_ids:
        requests = [
            BatchRequest(id=str(i), method="GET", url=odata.p("planner", "plans", pid))
            for i, pid in enumerate(plan_ids, 1)
        ]
        responses = client.batch(requests)
        for pid, response in zip(plan_ids, responses, strict=True):
            if response.error is None and isinstance(response.body, dict):
                titles[pid] = response.body.get("title", "")
    for item in items:
        item["_planTitle"] = titles.get(item.get("planId"), "")
    return items[:limit]


def get_task(client: GraphClient, task_id: str) -> dict:
    """`{...task, "details": {...}}`; a details fetch failure is swallowed (§8.14 `task`)."""
    task_obj = client.get(odata.p("planner", "tasks", task_id))
    try:
        details = client.get(odata.p("planner", "tasks", task_id, "details"))
    except MsgraphError:
        details = {}
    return {**task_obj, "details": details}


# --------------------------------------------------------------------------- writes


def _create_body(
    *,
    plan_id: str,
    bucket_id: str | None,
    title: str,
    due: Any,
    assignee_oids: list[str],
    priority: int | None,
) -> dict:
    body: dict[str, Any] = {"planId": plan_id}
    if bucket_id is not None:
        body["bucketId"] = bucket_id
    body["title"] = title
    if due is not None:
        body["dueDateTime"] = to_iso_offset(due)
    if priority is not None:
        body["priority"] = priority
    if assignee_oids:
        body["assignments"] = {
            oid: {"@odata.type": "#microsoft.graph.plannerAssignment", "orderHint": " !"}
            for oid in assignee_oids
        }
    return body


def _description_step(tasks_url: str, task_id: str, description: str) -> PlannedRequest:
    url = f"{tasks_url}/{task_id}/details"
    return PlannedRequest(
        "PATCH", url, {**JSON, "If-Match": "{etag}"}, {"description": description}
    )


def _write_description(client: GraphClient, task_id: str, description: str) -> dict:
    path = odata.p("planner", "tasks", task_id, "details")
    details = client.get(path) or {}
    etag = details.get("@odata.etag")
    headers = {"If-Match": etag} if etag else {}
    return client.patch(path, json={"description": description}, headers=headers)


def plan_create_task(
    client: GraphClient,
    *,
    plan_id: str,
    bucket_id: str | None = None,
    title: str,
    due: Any = None,
    assignee_oids: list[str] | None = None,
    priority: int | None = None,
    description: str | None = None,
) -> Plan:
    body = _create_body(
        plan_id=plan_id,
        bucket_id=bucket_id,
        title=title,
        due=due,
        assignee_oids=assignee_oids or [],
        priority=priority,
    )
    tasks_url = client.url(odata.p("planner", "tasks"))
    steps: Plan = [PlannedRequest("POST", tasks_url, dict(JSON), body)]
    if description is not None:
        steps.append(_description_step(tasks_url, "{taskId}", description))
    return steps


def run_create_task(
    client: GraphClient,
    *,
    plan_id: str,
    bucket_id: str | None = None,
    title: str,
    due: Any = None,
    assignee_oids: list[str] | None = None,
    priority: int | None = None,
    description: str | None = None,
) -> dict:
    body = _create_body(
        plan_id=plan_id,
        bucket_id=bucket_id,
        title=title,
        due=due,
        assignee_oids=assignee_oids or [],
        priority=priority,
    )
    task = client.post(odata.p("planner", "tasks"), json=body)
    if description is not None:
        details = _write_description(client, task["id"], description)
        task = {**task, "details": details}
    return task


def _update_body(
    *,
    title: str | None = None,
    due: Any = None,
    percent: int | None = None,
    bucket_id: str | None = None,
    priority: int | None = None,
    assign_oids: list[str] | None = None,
    unassign_oids: list[str] | None = None,
) -> dict:
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if due is not None:
        body["dueDateTime"] = to_iso_offset(due)
    if percent is not None:
        if percent not in PERCENT_VALUES:
            raise UsageError("USAGE", "--percent must be 0, 50 or 100")
        body["percentComplete"] = percent
    if bucket_id is not None:
        body["bucketId"] = bucket_id
    if priority is not None:
        body["priority"] = priority
    assignments: dict[str, Any] = {}
    for oid in assign_oids or []:
        assignments[oid] = {"@odata.type": "#microsoft.graph.plannerAssignment", "orderHint": " !"}
    for oid in unassign_oids or []:
        assignments[oid] = None
    if assignments:
        body["assignments"] = assignments
    return body


def plan_update_task(
    client: GraphClient,
    task_id: str,
    *,
    title: str | None = None,
    due: Any = None,
    percent: int | None = None,
    bucket_id: str | None = None,
    priority: int | None = None,
    assign_oids: list[str] | None = None,
    unassign_oids: list[str] | None = None,
    description: str | None = None,
) -> Plan:
    body = _update_body(
        title=title,
        due=due,
        percent=percent,
        bucket_id=bucket_id,
        priority=priority,
        assign_oids=assign_oids,
        unassign_oids=unassign_oids,
    )
    tasks_url = client.url(odata.p("planner", "tasks"))
    steps: Plan = []
    if body:
        headers = {**JSON, "If-Match": "{etag}", "Prefer": "return=representation"}
        steps.append(PlannedRequest("PATCH", f"{tasks_url}/{task_id}", headers, body))
    if description is not None:
        steps.append(_description_step(tasks_url, task_id, description))
    return steps


def run_update_task(
    client: GraphClient,
    task_id: str,
    *,
    title: str | None = None,
    due: Any = None,
    percent: int | None = None,
    bucket_id: str | None = None,
    priority: int | None = None,
    assign_oids: list[str] | None = None,
    unassign_oids: list[str] | None = None,
    description: str | None = None,
) -> dict:
    body = _update_body(
        title=title,
        due=due,
        percent=percent,
        bucket_id=bucket_id,
        priority=priority,
        assign_oids=assign_oids,
        unassign_oids=unassign_oids,
    )
    result: dict | None = None
    if body:
        path = odata.p("planner", "tasks", task_id)
        etag = (client.get(path) or {}).get("@odata.etag")
        headers = {"If-Match": etag, "Prefer": "return=representation"}
        try:
            result = client.patch(path, json=body, headers=headers)
        except GraphError as exc:
            if exc.status != 412:
                raise
            etag = (client.get(path) or {}).get("@odata.etag")
            headers = {"If-Match": etag, "Prefer": "return=representation"}
            result = client.patch(path, json=body, headers=headers)
    if description is not None:
        details = _write_description(client, task_id, description)
        result = {**(result or {}), "details": details}
    return result or {}


def plan_delete_task(client: GraphClient, task_id: str) -> Plan:
    url = client.url(odata.p("planner", "tasks", task_id))
    return [PlannedRequest("DELETE", url, {"If-Match": "{etag}"}, None, expect="none")]


def run_delete_task(client: GraphClient, task_id: str) -> None:
    path = odata.p("planner", "tasks", task_id)
    etag = (client.get(path) or {}).get("@odata.etag")
    client.delete(path, headers={"If-Match": etag}, expect="none")
