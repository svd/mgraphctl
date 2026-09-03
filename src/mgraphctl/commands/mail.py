"""Outlook mail commands (spec §8.2)."""

from pathlib import Path
from typing import Annotated

import typer

from mgraphctl.cli import (
    AllFlag,
    DryRunFlag,
    JsonFlag,
    LimitOpt,
    gate,
    graph_command,
    make_noun_app,
    page_bounds,
)
from mgraphctl.errors import MsgraphError, NotFoundError, UsageError
from mgraphctl.graph import mail
from mgraphctl.http import GraphClient
from mgraphctl.render import (
    Column,
    DryRunResult,
    FileResult,
    ListResult,
    ObjectResult,
    TextResult,
    WriteResult,
    fmt_dt,
    fmt_person,
    fmt_size,
    note,
    parse_dt,
    truncate,
)

app = make_noun_app("Outlook mail: list, read, send, reply, organise.")
drafts = make_noun_app("Draft messages.")
app.add_typer(drafts, name="drafts")
rules = make_noun_app("Inbox rules.")
app.add_typer(rules, name="rules")

BODY_LIMIT = 4000

FolderOpt = Annotated[str, typer.Option("--folder", help="Folder name, id, or 'all'.")]
ToOpt = Annotated[
    list[str] | None, typer.Option("--to", help="Recipient address (repeatable, comma-separated).")
]
CcOpt = Annotated[list[str] | None, typer.Option("--cc", help="Copy recipient (repeatable).")]
BccOpt = Annotated[list[str] | None, typer.Option("--bcc", help="Blind copy (repeatable).")]
SubjectOpt = Annotated[str | None, typer.Option("--subject", help="Subject line.")]
BodyOpt = Annotated[str | None, typer.Option("--body", help="Message body.")]
BodyFileOpt = Annotated[str | None, typer.Option("--body-file", help="Body file, or - for stdin.")]
HtmlOpt = Annotated[bool, typer.Option("--html", help="The body is HTML, not plain text.")]
AttachOpt = Annotated[
    list[Path] | None, typer.Option("--attach", help="File to attach (repeatable).")
]
ImportanceOpt = Annotated[str, typer.Option("--importance", help="low, normal or high.")]
MessageIdArg = Annotated[str, typer.Argument(metavar="ID", help="Message id.")]


def _split(values: list[str] | None) -> list[str]:
    """`--to a,b --to c` → `["a", "b", "c"]`."""
    out: list[str] = []
    for value in values or []:
        out += [part.strip() for part in value.split(",") if part.strip()]
    return out


def _read_fields(tz: str) -> list[tuple[str, object]]:
    return [
        ("Subject", "subject"),
        ("From", lambda m: fmt_person(m.get("from"))),
        ("To", lambda m: mail.recipients_text(m, "toRecipients")),
        ("Cc", lambda m: mail.recipients_text(m, "ccRecipients")),
        ("Received", lambda m: fmt_dt(m.get("receivedDateTime"), tz)),
        ("Id", "id"),
        ("Web link", "webLink"),
    ]


def _send_params(
    *,
    to: list[str] | None,
    body: str | None,
    body_file: str | None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    subject: str | None = None,
    html: bool = False,
    attach: list[Path] | None = None,
    importance: str = "normal",
    save_to_sent: bool = True,
) -> mail.SendParams:
    """Turn the shared `send` / `drafts create` options into a validated `SendParams`."""
    recipients = _split(to)
    if not recipients:
        raise UsageError("USAGE", "--to is required (one or more addresses)")
    if importance not in mail.IMPORTANCE:
        raise UsageError(
            "USAGE",
            f"--importance must be one of {', '.join(mail.IMPORTANCE)} (got {importance!r})",
        )
    return mail.SendParams(
        to=recipients,
        body=mail.read_body(body, body_file),
        cc=_split(cc),
        bcc=_split(bcc),
        subject=subject,
        html=html,
        attachments=list(attach or []),
        importance=importance,
        save_to_sent=save_to_sent,
    )


def _mark_patch(
    *,
    read: bool,
    unread: bool,
    flag: bool,
    unflag: bool,
    flag_complete: bool,
    category: list[str] | None,
    clear_categories: bool,
    importance: str | None,
) -> dict:
    """The PATCH body `mail mark` sends; every contradictory pair is a usage error."""
    if read and unread:
        raise UsageError("USAGE", "--read and --unread are mutually exclusive")
    if sum([flag, unflag, flag_complete]) > 1:
        raise UsageError("USAGE", "give at most one of --flag, --unflag or --flag-complete")
    categories = _split(category)
    if categories and clear_categories:
        raise UsageError("USAGE", "--category and --clear-categories are mutually exclusive")
    patch: dict[str, object] = {}
    if read or unread:
        patch["isRead"] = read
    for wanted, status in ((flag, "flagged"), (unflag, "notFlagged"), (flag_complete, "complete")):
        if wanted:
            patch["flag"] = {"flagStatus": status}
    if categories or clear_categories:
        patch["categories"] = categories
    if importance is not None:
        if importance not in mail.IMPORTANCE:
            raise UsageError(
                "USAGE",
                f"--importance must be one of {', '.join(mail.IMPORTANCE)} (got {importance!r})",
            )
        patch["importance"] = importance
    if not patch:
        raise UsageError(
            "USAGE",
            "nothing to change; give --read/--unread, --flag/--unflag/--flag-complete, "
            "--category/--clear-categories or --importance",
        )
    return patch


def _actions_summary(rule: dict) -> str:
    return ", ".join(name for name, value in (rule.get("actions") or {}).items() if value)


def _headers_block(message: dict) -> str:
    rows = message.get("internetMessageHeaders") or []
    lines = [f"  {row.get('name')}: {row.get('value')}" for row in rows]
    return "\n".join(["Headers", *lines])


def _tree_text(tree: list[dict]) -> str:
    """The folder tree: children indented by two spaces, ids in full (spec §8.2 `folders`)."""
    rows: list[tuple[str, str, str, str]] = []

    def walk(folders: list[dict], level: int) -> None:
        for folder in folders:
            rows.append(
                (
                    "  " * level + truncate(folder.get("displayName")),
                    str(folder.get("unreadItemCount") or 0),
                    str(folder.get("totalItemCount") or 0),
                    str(folder.get("id") or ""),
                )
            )
            walk(folder.get("children") or [], level + 1)

    walk(tree, 0)
    if not rows:
        return "No results."
    rows.insert(0, ("name", "unread", "total", "id"))
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    return "\n".join(
        f"{name:<{widths[0]}}  {unread:>{widths[1]}}  {total:>{widths[2]}}  {folder_id}"
        for name, unread, total, folder_id in rows
    )


# --------------------------------------------------------------------------- read verbs


@app.command("list")
@graph_command(scopes=["Mail.Read"])
def list_(
    client: GraphClient,
    folder: FolderOpt = "inbox",
    unread: Annotated[bool, typer.Option("--unread", help="Only unread messages.")] = False,
    from_: Annotated[
        list[str] | None, typer.Option("--from", help="Sender address (repeatable).")
    ] = None,
    to: Annotated[
        list[str] | None, typer.Option("--to", help="Recipient address (repeatable).")
    ] = None,
    search: Annotated[str | None, typer.Option("--search", help="KQL query.")] = None,
    after: Annotated[str | None, typer.Option("--after", help="Only messages after this.")] = None,
    before: Annotated[
        str | None, typer.Option("--before", help="Only messages before this.")
    ] = None,
    select: Annotated[
        str | None, typer.Option("--select", help="Comma-separated $select override.")
    ] = None,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List messages (default: Inbox, newest first)."""
    limit, all_ = page_bounds(limit, all_, default=10)
    tz = client.tz
    page = mail.list_messages(
        client,
        folder_id=mail.resolve_folder(client, folder),
        unread=unread,
        search=search,
        senders=_split(from_),
        recipients=_split(to),
        after=parse_dt(after, tz) if after else None,
        before=parse_dt(before, tz, end_of_day=True) if before else None,
        select=select,
        limit=limit,
        all_=all_,
        tz=tz,
    )
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        hit_cap=mail.CAP_LIST if all_ else None,
        columns=mail.message_columns(tz),
    )


@app.command("read")
@graph_command(scopes=["Mail.Read"])
def read(
    client: GraphClient,
    message_id: MessageIdArg,
    html: Annotated[bool, typer.Option("--html", help="Show the HTML body verbatim.")] = False,
    full: Annotated[bool, typer.Option("--full", help="Do not truncate the body.")] = False,
    headers: Annotated[
        bool, typer.Option("--headers", help="Also show the internet message headers.")
    ] = False,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write the full body to this file.")
    ] = None,
    save_attachments: Annotated[
        Path | None, typer.Option("--save-attachments", help="Save file attachments here.")
    ] = None,
    json_: JsonFlag = False,
):
    """Show one message."""
    tz = client.tz
    message = mail.get_message(client, message_id, headers=headers, html=html)
    if save_attachments is not None:
        for attachment in mail.list_attachments(client, message_id):
            if not mail.is_file_attachment(attachment):
                note(
                    f"skipped {attachment.get('name')}: "
                    f"{mail.attachment_type(attachment)} cannot be downloaded"
                )
                continue
            name = Path(str(attachment.get("name") or attachment["id"])).name
            mail.download_attachment(client, message_id, attachment["id"], save_attachments / name)
    body = mail.body_text(message, html=html)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(body)
        return FileResult(
            path=output,
            bytes=len(body.encode()),
            meta={"chars": len(body)},
            message=f"Wrote {len(body)} chars to {output}",
        )
    shown = body
    if not full and len(body) > BODY_LIMIT:
        shown = body[:BODY_LIMIT]
        note(f"(body truncated to {BODY_LIMIT} chars; use --full)")
    if headers:
        shown = _headers_block(message) + "\n\n" + shown
    return ObjectResult(obj=message, fields=_read_fields(tz), body=shown)


@app.command("attachments")
@graph_command(scopes=["Mail.Read"])
def attachments(
    client: GraphClient,
    message_id: MessageIdArg,
    download: Annotated[
        str | None, typer.Option("--download", help="Attachment id to download.")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Where to write the --download file.")
    ] = None,
    all_attachments: Annotated[
        bool, typer.Option("--all-attachments", help="Download every file attachment.")
    ] = False,
    output_dir: Annotated[
        Path | None, typer.Option("--output-dir", help="Directory for --all-attachments.")
    ] = None,
    json_: JsonFlag = False,
):
    """List a message's attachments, or download them."""
    if download is not None and all_attachments:
        raise UsageError("USAGE", "--download and --all-attachments are mutually exclusive")
    if output is not None and download is None:
        raise UsageError("USAGE", "--output names the file for --download; add --download")
    if output_dir is not None and not all_attachments:
        raise UsageError("USAGE", "--output-dir goes with --all-attachments")
    items = mail.list_attachments(client, message_id)
    if download is not None:
        return _download_one(client, message_id, items, download, output)
    if all_attachments:
        return _download_all(client, message_id, items, output_dir or Path())
    return ListResult(
        items=items,
        columns=[
            Column("id", "id"),
            Column("type", mail.attachment_kind),
            Column("name", "name"),
            Column("size", lambda a: fmt_size(a.get("size"))),
            Column("inline", lambda a: "yes" if a.get("isInline") else "no"),
        ],
    )


def _find_attachment(items: list[dict], attachment_id: str) -> dict:
    for attachment in items:
        if attachment.get("id") == attachment_id:
            return attachment
    raise NotFoundError("NOT_FOUND", f"attachment {attachment_id!r} not found on this message")


def _download_one(
    client: GraphClient,
    message_id: str,
    items: list[dict],
    attachment_id: str,
    output: Path | None,
) -> FileResult:
    attachment = _find_attachment(items, attachment_id)
    name = str(attachment.get("name") or attachment_id)
    if not mail.is_file_attachment(attachment):
        raise MsgraphError(
            "ATTACHMENT_NOT_A_FILE",
            f"{mail.attachment_type(attachment)} {name!r} cannot be downloaded",
            hint="only fileAttachment items have bytes; open the message in Outlook instead",
        )
    got = mail.download_attachment(
        client, message_id, attachment_id, output or Path(Path(name).name)
    )
    return FileResult(
        path=got.path,
        bytes=got.bytes,
        meta={"id": attachment_id, "name": name, "contentType": got.content_type},
        message=f"Downloaded {name} ({fmt_size(got.bytes)}) to {got.path}",
    )


def _download_all(
    client: GraphClient, message_id: str, items: list[dict], output_dir: Path
) -> ListResult:
    saved: list[dict] = []
    for attachment in items:
        name = str(attachment.get("name") or attachment["id"])
        if not mail.is_file_attachment(attachment):
            note(f"skipped {name}: {mail.attachment_type(attachment)} cannot be downloaded")
            continue
        got = mail.download_attachment(
            client, message_id, attachment["id"], output_dir / Path(name).name
        )
        saved.append(
            {"id": attachment["id"], "name": name, "bytes": got.bytes, "path": str(got.path)}
        )
    return ListResult(
        items=saved,
        empty_text="No file attachments.",
        columns=[
            Column("id", "id"),
            Column("name", "name"),
            Column("size", lambda a: fmt_size(a.get("bytes"))),
            Column("path", "path"),
        ],
    )


@app.command("folders")
@graph_command(scopes=["Mail.Read"])
def folders(
    client: GraphClient,
    depth: Annotated[int, typer.Option("--depth", min=1, help="How many levels to show.")] = 2,
    hidden: Annotated[bool, typer.Option("--hidden", help="Include hidden folders.")] = False,
    json_: JsonFlag = False,
):
    """Show the mail folder tree."""
    page = mail.list_folders(client, depth=depth, hidden=hidden)
    if page.truncated and not json_:
        note(f"(hit the {mail.CAP_FOLDERS}-item cap — narrow the query)")
    return TextResult(
        text=_tree_text(page.items),
        json_obj={
            "items": page.items,
            "count": len(page.items),
            "truncated": page.truncated,
        },
    )


# --------------------------------------------------------------------------- write verbs


@app.command("send")
@graph_command(scopes=["Mail.Send"])
def send(
    client: GraphClient,
    to: ToOpt = None,
    cc: CcOpt = None,
    bcc: BccOpt = None,
    subject: SubjectOpt = None,
    body: BodyOpt = None,
    body_file: BodyFileOpt = None,
    html: HtmlOpt = False,
    attach: AttachOpt = None,
    importance: ImportanceOpt = "normal",
    save_to_sent: Annotated[
        bool,
        typer.Option("--save-to-sent/--no-save-to-sent", help="Keep a copy in Sent Items."),
    ] = True,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Send a message."""
    params = _send_params(
        to=to,
        body=body,
        body_file=body_file,
        cc=cc,
        bcc=bcc,
        subject=subject,
        html=html,
        attach=attach,
        importance=importance,
        save_to_sent=save_to_sent,
    )
    if dry_run:
        return DryRunResult(mail.plan_send(client, params, for_plan=True))
    if mail.needs_draft_path(params):
        gate(["Mail.ReadWrite"])  # the draft path writes before it sends (spec §4.4)
    return WriteResult(obj=mail.run_send(client, params), message="Sent.")


@app.command("reply")
@graph_command(scopes=["Mail.Send"])
def reply(
    client: GraphClient,
    message_id: MessageIdArg,
    body: BodyOpt = None,
    body_file: BodyFileOpt = None,
    html: HtmlOpt = False,
    reply_all: Annotated[
        bool, typer.Option("--reply-all", help="Reply to everyone on the message.")
    ] = False,
    to: ToOpt = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Reply to a message."""
    plan = mail.plan_reply(
        client,
        message_id,
        body=mail.read_body(body, body_file),
        html=html,
        reply_all=reply_all,
        extra_to=_split(to),
    )
    if dry_run:
        return DryRunResult(plan)
    mail.run_plan(client, plan)
    return WriteResult(obj={"status": "sent"}, message="Sent.")


@app.command("forward")
@graph_command(scopes=["Mail.Send"])
def forward(
    client: GraphClient,
    message_id: MessageIdArg,
    to: ToOpt = None,
    body: BodyOpt = None,
    html: HtmlOpt = False,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Forward a message."""
    recipients = _split(to)
    if not recipients:
        raise UsageError("USAGE", "--to is required (one or more addresses)")
    plan = mail.plan_forward(client, message_id, to=recipients, body=body or "", html=html)
    if dry_run:
        return DryRunResult(plan)
    mail.run_plan(client, plan)
    return WriteResult(obj={"status": "sent"}, message="Sent.")


@app.command("mark")
@graph_command(scopes=["Mail.ReadWrite"])
def mark(
    client: GraphClient,
    message_ids: Annotated[list[str], typer.Argument(metavar="ID...", help="Message ids.")],
    read: Annotated[bool, typer.Option("--read", help="Mark as read.")] = False,
    unread: Annotated[bool, typer.Option("--unread", help="Mark as unread.")] = False,
    flag: Annotated[bool, typer.Option("--flag", help="Flag for follow-up.")] = False,
    unflag: Annotated[bool, typer.Option("--unflag", help="Remove the flag.")] = False,
    flag_complete: Annotated[
        bool, typer.Option("--flag-complete", help="Mark the flag complete.")
    ] = False,
    category: Annotated[
        list[str] | None, typer.Option("--category", help="Category to set (repeatable).")
    ] = None,
    clear_categories: Annotated[
        bool, typer.Option("--clear-categories", help="Remove every category.")
    ] = False,
    importance: Annotated[
        str | None, typer.Option("--importance", help="low, normal or high.")
    ] = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Change read state, flag, categories or importance on one or more messages."""
    patch = _mark_patch(
        read=read,
        unread=unread,
        flag=flag,
        unflag=unflag,
        flag_complete=flag_complete,
        category=category,
        clear_categories=clear_categories,
        importance=importance,
    )
    if dry_run:
        return DryRunResult(mail.plan_mark(client, message_ids, patch))
    return ListResult(
        items=mail.run_mark(client, message_ids, patch),
        columns=mail.message_columns(client.tz),
    )


@app.command("move")
@graph_command(scopes=["Mail.ReadWrite"])
def move(
    client: GraphClient,
    message_id: MessageIdArg,
    folder: Annotated[str, typer.Option("--folder", help="Destination folder name or id.")],
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Move a message to another folder. The message gets a new id."""
    plan = mail.plan_move(client, message_id, folder)
    if dry_run:
        return DryRunResult(plan)
    moved = mail.run_plan(client, plan)[0]
    return WriteResult(obj=moved, message=f"Moved to {folder}; new id: {moved.get('id')}")


@app.command("delete")
@graph_command(scopes=["Mail.ReadWrite"])
def delete(
    client: GraphClient,
    message_id: MessageIdArg,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Delete a message (Outlook moves it to Deleted Items)."""
    plan = mail.plan_delete(client, message_id)
    if dry_run:
        return DryRunResult(plan)
    mail.run_plan(client, plan)
    return WriteResult(
        obj={"status": "deleted", "id": message_id}, message=f"Deleted {message_id}."
    )


@rules.command("list")
@graph_command(scopes=["MailboxSettings.Read"])
def rules_list(client: GraphClient, json_: JsonFlag = False):
    """List the inbox rules."""
    return ListResult(
        items=mail.list_rules(client),
        empty_text="No inbox rules.",
        columns=[
            Column("id", "id"),
            Column("sequence", "sequence"),
            Column("enabled", lambda r: "yes" if r.get("isEnabled") else "no"),
            Column("name", "displayName"),
            Column("actions", _actions_summary),
        ],
    )


@app.command("categories")
@graph_command(scopes=["MailboxSettings.Read"])
def categories(client: GraphClient, json_: JsonFlag = False):
    """List the mailbox's categories."""
    return ListResult(
        items=mail.list_categories(client),
        empty_text="No categories.",
        columns=[
            Column("id", "id"),
            Column("name", "displayName"),
            Column("color", "color"),
        ],
    )


@drafts.command("create")
@graph_command(scopes=["Mail.ReadWrite"])
def drafts_create(
    client: GraphClient,
    to: ToOpt = None,
    cc: CcOpt = None,
    bcc: BccOpt = None,
    subject: SubjectOpt = None,
    body: BodyOpt = None,
    body_file: BodyFileOpt = None,
    html: HtmlOpt = False,
    attach: AttachOpt = None,
    importance: ImportanceOpt = "normal",
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Create a draft message without sending it."""
    params = _send_params(
        to=to,
        body=body,
        body_file=body_file,
        cc=cc,
        bcc=bcc,
        subject=subject,
        html=html,
        attach=attach,
        importance=importance,
    )
    if dry_run:
        return DryRunResult(mail.plan_create_draft(client, params, for_plan=True))
    draft = mail.run_create_draft(client, params)
    return WriteResult(obj=draft, message=f"Draft created: {draft.get('id')}")


@drafts.command("send")
@graph_command(scopes=["Mail.ReadWrite", "Mail.Send"])
def drafts_send(
    client: GraphClient,
    message_id: MessageIdArg,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Send an existing draft."""
    plan = mail.plan_send_draft(client, message_id)
    if dry_run:
        return DryRunResult(plan)
    mail.run_plan(client, plan)
    return WriteResult(obj={"status": "sent"}, message="Sent.")


@drafts.command("list")
@graph_command(scopes=["Mail.Read"])
def drafts_list(
    client: GraphClient,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List draft messages, most recently changed first."""
    limit, all_ = page_bounds(limit, all_, default=20)
    page = mail.list_drafts(client, limit=limit, all_=all_)
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        hit_cap=mail.CAP_LIST if all_ else None,
        columns=[
            Column("id", "id"),
            Column("to", lambda m: truncate(mail.recipients_text(m))),
            Column("subject", lambda m: truncate(m.get("subject"))),
        ],
    )
