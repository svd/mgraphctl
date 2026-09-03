"""Microsoft To Do commands: lists and tasks (spec §8.15)."""

from typing import Annotated

import typer

from mgraphctl.cli import (
    AllFlag,
    DryRunFlag,
    JsonFlag,
    LimitOpt,
    graph_command,
    make_noun_app,
    page_bounds,
)
from mgraphctl.graph import todo
from mgraphctl.http import GraphClient
from mgraphctl.render import (
    Column,
    DryRunResult,
    ListResult,
    ObjectResult,
    WriteResult,
    fmt_dtz,
    parse_dt,
)

app = make_noun_app("Microsoft To Do lists and tasks.")

SCOPES = ["Tasks.ReadWrite"]
SCOPES_FROM_MAIL = ["Tasks.ReadWrite", "Mail.Read"]
DEFAULT_LIMIT = 50

LIST_COLUMNS = [
    Column("id", "id"),
    Column("wellknown", lambda item: item.get("wellknownListName") or ""),
    Column("name", "displayName"),
]


def _task_columns(tz: str) -> list[Column]:
    return [
        Column("id", "id"),
        Column("status", "status"),
        Column("importance", "importance"),
        Column("due", lambda t: fmt_dtz(t.get("dueDateTime"), tz)),
        Column("title", "title"),
    ]


@app.command("lists")
@graph_command(scopes=SCOPES)
def lists(client: GraphClient, json_: JsonFlag = False):
    """List your To Do lists."""
    return ListResult(items=todo.list_lists(client), columns=LIST_COLUMNS)


@app.command("tasks")
@graph_command(scopes=SCOPES)
def tasks(
    client: GraphClient,
    list_ref: Annotated[str, typer.Argument(metavar="LIST")],
    include_completed: Annotated[bool, typer.Option("--include-completed")] = False,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List the tasks of a To Do list."""
    bounded_limit, bounded_all = page_bounds(limit, all_, default=DEFAULT_LIMIT)
    resolved = todo.resolve_list(client, list_ref)
    page = todo.list_tasks(
        client,
        resolved["id"],
        include_completed=include_completed,
        limit=bounded_limit,
        all_=bounded_all,
    )
    return ListResult(items=page.items, truncated=page.truncated, columns=_task_columns(client.tz))


@app.command("task")
@graph_command(scopes=SCOPES)
def task(
    client: GraphClient,
    list_ref: Annotated[str, typer.Argument(metavar="LIST")],
    task_id: Annotated[str, typer.Argument(metavar="ID")],
    json_: JsonFlag = False,
):
    """Show one task."""
    resolved = todo.resolve_list(client, list_ref)
    obj = todo.get_task(client, resolved["id"], task_id)
    fields = [
        ("Title", "title"),
        ("Status", "status"),
        ("Importance", "importance"),
        ("Due", lambda o: fmt_dtz(o.get("dueDateTime"), client.tz)),
    ]
    return ObjectResult(obj=obj, fields=fields)


def _create_opts(
    *,
    title,
    due,
    body,
    importance,
    reminder,
    start,
    tz,
) -> dict:
    return dict(
        title=title,
        due=parse_dt(due, tz) if due is not None else None,
        body_text=body,
        importance=importance,
        reminder=parse_dt(reminder, tz) if reminder is not None else None,
        start=parse_dt(start, tz) if start is not None else None,
        tz=tz,
    )


@app.command("create")
@graph_command(scopes=SCOPES)
def create(
    client: GraphClient,
    list_ref: Annotated[str, typer.Argument(metavar="LIST")],
    title: Annotated[str, typer.Option("--title")],
    due: Annotated[str | None, typer.Option("--due")] = None,
    body: Annotated[str | None, typer.Option("--body")] = None,
    importance: Annotated[str | None, typer.Option("--importance")] = None,
    reminder: Annotated[str | None, typer.Option("--reminder")] = None,
    start: Annotated[str | None, typer.Option("--start")] = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Create a task."""
    resolved = todo.resolve_list(client, list_ref)
    opts = _create_opts(
        title=title,
        due=due,
        body=body,
        importance=importance,
        reminder=reminder,
        start=start,
        tz=client.tz,
    )
    if dry_run:
        return DryRunResult(todo.plan_create(client, resolved["id"], **opts))
    obj = todo.run_create(client, resolved["id"], **opts)
    return WriteResult(obj=obj, message=f"Created task {obj.get('id')}.")


@app.command("update")
@graph_command(scopes=SCOPES)
def update(
    client: GraphClient,
    list_ref: Annotated[str, typer.Argument(metavar="LIST")],
    task_id: Annotated[str, typer.Argument(metavar="ID")],
    title: Annotated[str | None, typer.Option("--title")] = None,
    due: Annotated[str | None, typer.Option("--due")] = None,
    body: Annotated[str | None, typer.Option("--body")] = None,
    importance: Annotated[str | None, typer.Option("--importance")] = None,
    reminder: Annotated[str | None, typer.Option("--reminder")] = None,
    start: Annotated[str | None, typer.Option("--start")] = None,
    status: Annotated[str | None, typer.Option("--status")] = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Update a task."""
    resolved = todo.resolve_list(client, list_ref)
    opts = _create_opts(
        title=title,
        due=due,
        body=body,
        importance=importance,
        reminder=reminder,
        start=start,
        tz=client.tz,
    )
    opts["status"] = status
    if dry_run:
        return DryRunResult(todo.plan_update(client, resolved["id"], task_id, **opts))
    obj = todo.run_update(client, resolved["id"], task_id, **opts)
    return WriteResult(obj=obj, message=f"Updated task {task_id}.")


@app.command("complete")
@graph_command(scopes=SCOPES)
def complete(
    client: GraphClient,
    list_ref: Annotated[str, typer.Argument(metavar="LIST")],
    task_id: Annotated[str, typer.Argument(metavar="ID")],
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Mark a task complete."""
    resolved = todo.resolve_list(client, list_ref)
    if dry_run:
        return DryRunResult(todo.plan_complete(client, resolved["id"], task_id, tz=client.tz))
    obj = todo.run_complete(client, resolved["id"], task_id, tz=client.tz)
    return WriteResult(obj=obj, message=f"Completed task {task_id}.")


@app.command("delete")
@graph_command(scopes=SCOPES)
def delete(
    client: GraphClient,
    list_ref: Annotated[str, typer.Argument(metavar="LIST")],
    task_id: Annotated[str, typer.Argument(metavar="ID")],
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Delete a task."""
    resolved = todo.resolve_list(client, list_ref)
    if dry_run:
        return DryRunResult(todo.plan_delete(client, resolved["id"], task_id))
    todo.run_delete(client, resolved["id"], task_id)
    return WriteResult(obj={"status": "deleted", "id": task_id}, message=f"Deleted task {task_id}.")


@app.command("from-mail")
@graph_command(scopes=SCOPES_FROM_MAIL)
def from_mail(
    client: GraphClient,
    list_ref: Annotated[str, typer.Argument(metavar="LIST")],
    message_id: Annotated[str, typer.Argument(metavar="MSGID")],
    title: Annotated[str | None, typer.Option("--title")] = None,
    due: Annotated[str | None, typer.Option("--due")] = None,
    importance: Annotated[str | None, typer.Option("--importance")] = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Create a task linked to a mail message."""
    resolved = todo.resolve_list(client, list_ref)
    message = todo.fetch_message_for_task(client, message_id)
    opts = dict(
        title=title,
        due=parse_dt(due, client.tz) if due is not None else None,
        importance=importance,
        tz=client.tz,
    )
    if dry_run:
        return DryRunResult(todo.plan_from_mail(client, resolved["id"], message, **opts))
    obj = todo.run_from_mail(client, resolved["id"], message, **opts)
    return WriteResult(obj=obj, message=f"Created task {obj.get('id')}.")
