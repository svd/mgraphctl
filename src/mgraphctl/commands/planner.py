"""Planner commands: plans, buckets, tasks (spec §8.14)."""

from typing import Annotated, Literal

import typer

from mgraphctl.cli import DryRunFlag, JsonFlag, LimitOpt, graph_command, make_noun_app
from mgraphctl.errors import UsageError
from mgraphctl.graph import planner, users
from mgraphctl.http import GraphClient
from mgraphctl.render import (
    Column,
    DryRunResult,
    ListResult,
    ObjectResult,
    WriteResult,
    fmt_dt,
    note,
    parse_dt,
)

app = make_noun_app("Planner plans and tasks.")

SCOPES = ["Tasks.ReadWrite"]
SCOPES_PLANS = ["Tasks.ReadWrite", "Group.Read.All"]
DEFAULT_LIMIT = 50

PLAN_COLUMNS = [
    Column("id", "id"),
    Column("title", "title"),
    Column("group", lambda p: p.get("_groupName") or ""),
]
BUCKET_COLUMNS = [Column("id", "id"), Column("name", "name")]


def _task_columns(tz: str, *, my: bool) -> list[Column]:
    columns = [
        Column("id", "id"),
        Column("%", lambda t: t.get("percentComplete", "")),
        Column("priority", lambda t: t.get("priority", "")),
        Column("due", lambda t: fmt_dt(t.get("dueDateTime"), tz)),
    ]
    if my:
        columns.append(Column("plan", lambda t: t.get("_planTitle") or ""))
    else:
        columns.append(Column("bucket", lambda t: t.get("_bucketName") or ""))
    columns.append(Column("title", "title"))
    return columns


def _assignee_oids(client: GraphClient, upns: list[str]) -> list[str]:
    return [users.get_user(client, upn, select="id")["id"] for upn in upns]


@app.command("plans")
@graph_command(scopes=SCOPES_PLANS)
def plans(
    client: GraphClient,
    limit: LimitOpt = None,
    json_: JsonFlag = False,
):
    """List plans you own plus every plan of a Microsoft 365 group you belong to."""
    eff_limit = limit if limit is not None else DEFAULT_LIMIT
    page = planner.list_plans(client, limit=eff_limit, on_skip=note)
    return ListResult(items=page.items, columns=PLAN_COLUMNS, truncated=page.truncated)


@app.command("plan")
@graph_command(scopes=SCOPES)
def plan(
    client: GraphClient,
    plan_ref: Annotated[str, typer.Argument(metavar="PLAN")],
    json_: JsonFlag = False,
):
    """Show one plan, with its details."""
    resolved = planner.resolve_plan(client, plan_ref)
    obj = planner.get_plan(client, resolved["id"])
    fields = [
        ("Title", "title"),
        ("Plan id", "id"),
        ("Created", lambda o: fmt_dt(o.get("createdDateTime"), client.tz)),
        ("Description", lambda o: (o.get("details") or {}).get("description") or ""),
    ]
    return ObjectResult(obj=obj, fields=fields)


@app.command("buckets")
@graph_command(scopes=SCOPES)
def buckets(
    client: GraphClient,
    plan_ref: Annotated[str, typer.Argument(metavar="PLAN")],
    json_: JsonFlag = False,
):
    """List the buckets of a plan."""
    resolved = planner.resolve_plan(client, plan_ref)
    items = planner.list_buckets(client, resolved["id"])
    return ListResult(items=items, columns=BUCKET_COLUMNS)


@app.command("tasks")
@graph_command(scopes=SCOPES)
def tasks(
    client: GraphClient,
    plan_ref: Annotated[str | None, typer.Argument(metavar="PLAN")] = None,
    my: Annotated[bool, typer.Option("--my", help="Your tasks across every plan.")] = False,
    bucket: Annotated[str | None, typer.Option("--bucket", help="Bucket name or id.")] = None,
    include_completed: Annotated[bool, typer.Option("--include-completed")] = False,
    limit: LimitOpt = None,
    json_: JsonFlag = False,
):
    """List tasks in a plan, or your own tasks across every plan (--my)."""
    eff_limit = limit if limit is not None else DEFAULT_LIMIT
    if my:
        page = planner.my_tasks(
            client, include_completed=include_completed, limit=eff_limit, on_skip=note
        )
        return ListResult(
            items=page.items,
            columns=_task_columns(client.tz, my=True),
            truncated=page.truncated,
        )
    if plan_ref is None:
        raise UsageError("USAGE", "PLAN is required unless --my is given")
    resolved = planner.resolve_plan(client, plan_ref)
    bucket_id = None
    if bucket is not None:
        bucket_id = planner.resolve_bucket(client, resolved["id"], bucket)["id"]
    page = planner.list_tasks(
        client,
        resolved["id"],
        bucket_id=bucket_id,
        include_completed=include_completed,
        limit=eff_limit,
    )
    return ListResult(
        items=page.items,
        columns=_task_columns(client.tz, my=False),
        truncated=page.truncated,
    )


@app.command("task")
@graph_command(scopes=SCOPES)
def task(
    client: GraphClient,
    task_id: Annotated[str, typer.Argument(metavar="ID")],
    json_: JsonFlag = False,
):
    """Show one task, with its details."""
    obj = planner.get_task(client, task_id)
    fields = [
        ("Title", "title"),
        ("Plan id", "planId"),
        ("Bucket id", "bucketId"),
        ("%", "percentComplete"),
        ("Priority", "priority"),
        ("Due", lambda o: fmt_dt(o.get("dueDateTime"), client.tz)),
        ("Description", lambda o: (o.get("details") or {}).get("description") or ""),
    ]
    return ObjectResult(obj=obj, fields=fields)


@app.command("create")
@graph_command(scopes=SCOPES)
def create(
    client: GraphClient,
    plan_opt: Annotated[str, typer.Option("--plan", help="Plan name or id.")],
    title: Annotated[str, typer.Option("--title")],
    bucket: Annotated[str | None, typer.Option("--bucket", help="Bucket name or id.")] = None,
    due: Annotated[str | None, typer.Option("--due")] = None,
    assign: Annotated[
        list[str] | None, typer.Option("--assign", help="Assignee UPN (repeatable).")
    ] = None,
    priority: Annotated[int | None, typer.Option("--priority", min=0, max=10)] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Create a task."""
    resolved_plan = planner.resolve_plan(client, plan_opt)
    bucket_id = None
    if bucket is not None:
        bucket_id = planner.resolve_bucket(client, resolved_plan["id"], bucket)["id"]
    due_dt = parse_dt(due, client.tz) if due is not None else None
    oids = _assignee_oids(client, assign or [])
    kwargs = dict(
        plan_id=resolved_plan["id"],
        bucket_id=bucket_id,
        title=title,
        due=due_dt,
        assignee_oids=oids,
        priority=priority,
        description=description,
    )
    if dry_run:
        return DryRunResult(planner.plan_create_task(client, **kwargs))
    obj = planner.run_create_task(client, **kwargs)
    return WriteResult(obj=obj, message=f"Created task {obj.get('id')}.")


@app.command("update")
@graph_command(scopes=SCOPES)
def update(
    client: GraphClient,
    task_id: Annotated[str, typer.Argument(metavar="ID")],
    title: Annotated[str | None, typer.Option("--title")] = None,
    due: Annotated[str | None, typer.Option("--due")] = None,
    percent: Annotated[
        Literal[0, 50, 100] | None,
        typer.Option("--percent", help="Completion; Graph accepts only these three values."),
    ] = None,
    bucket: Annotated[str | None, typer.Option("--bucket", help="Bucket name or id.")] = None,
    priority: Annotated[int | None, typer.Option("--priority", min=0, max=10)] = None,
    assign: Annotated[list[str] | None, typer.Option("--assign")] = None,
    unassign: Annotated[list[str] | None, typer.Option("--unassign")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Update a task."""
    due_dt = parse_dt(due, client.tz) if due is not None else None
    bucket_id = planner.resolve_bucket_for_task(client, task_id, bucket)["id"] if bucket else None
    kwargs = dict(
        title=title,
        due=due_dt,
        percent=percent,
        bucket_id=bucket_id,
        priority=priority,
        assign_oids=_assignee_oids(client, assign or []),
        unassign_oids=_assignee_oids(client, unassign or []),
        description=description,
    )
    if dry_run:
        return DryRunResult(planner.plan_update_task(client, task_id, **kwargs))
    obj = planner.run_update_task(client, task_id, **kwargs)
    return WriteResult(obj=obj, message=f"Updated task {task_id}.")


@app.command("complete")
@graph_command(scopes=SCOPES)
def complete(
    client: GraphClient,
    task_id: Annotated[str, typer.Argument(metavar="ID")],
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Mark a task complete (percent 100)."""
    if dry_run:
        return DryRunResult(planner.plan_update_task(client, task_id, percent=100))
    obj = planner.run_update_task(client, task_id, percent=100)
    return WriteResult(obj=obj, message=f"Completed task {task_id}.")


@app.command("delete")
@graph_command(scopes=SCOPES)
def delete(
    client: GraphClient,
    task_id: Annotated[str, typer.Argument(metavar="ID")],
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Delete a task."""
    if dry_run:
        return DryRunResult(planner.plan_delete_task(client, task_id))
    planner.run_delete_task(client, task_id)
    return WriteResult(obj={"status": "deleted", "id": task_id}, message=f"Deleted task {task_id}.")
