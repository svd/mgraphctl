"""Graph operations for Outlook mail (spec §8.2).

Pure: client and parameters in, Graph dicts / `PageResult` / `Plan` out. Nothing here prints.
"""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from math import ceil
from mimetypes import guess_type
from pathlib import Path
from typing import Any

from mgraphctl import config, odata, resolve
from mgraphctl.errors import UsageError
from mgraphctl.html import to_markdown
from mgraphctl.http import (
    JSON_HEADERS,
    BatchRequest,
    DownloadResult,
    GraphClient,
    PageResult,
    Plan,
    PlannedRequest,
    filter_page,
)
from mgraphctl.render import (
    Column,
    fmt_dt,
    fmt_person,
    has_time_of_day,
    kql_date,
    parse_graph_dt,
    truncate,
)

LIST_SELECT = (
    "id,subject,from,toRecipients,ccRecipients,receivedDateTime,isRead,hasAttachments,"
    "importance,bodyPreview,conversationId,webLink,inferenceClassification"
)
READ_EXTRA = ",body,uniqueBody,replyTo"
HEADERS_EXTRA = ",internetMessageHeaders"
ATTACHMENT_SELECT = "id,name,contentType,size,isInline"
FOLDER_SELECT = "id,displayName,parentFolderId,childFolderCount,unreadItemCount,totalItemCount"
FOLDER_RESOLVE_SELECT = "id,displayName,childFolderCount"

PAGE_SEARCH, PAGE_FILTER, CAP_LIST = 25, 50, 500
PAGE_FOLDERS, CAP_FOLDERS, PAGE_FOLDER_RESOLVE = 100, 500, 200

FILE_ATTACHMENT = "#microsoft.graph.fileAttachment"
MAX_ATTACHMENT = 157_286_400  # 150 MB, Outlook's own ceiling
IMPORTANCE = ("low", "normal", "high")
DRAFT_ID = "{draftId}"  # the placeholder a dry run shows instead of an id it cannot know yet
INLINE_NOTE = "inline path: attachments total <= 2.5 MiB"
DRAFT_NOTE = "draft path: attachments total > 2.5 MiB"


# --------------------------------------------------------------------------- folders


def _folder_page(
    client: GraphClient, path: str, select: str, page_size: int, hidden: bool
) -> PageResult:
    params: dict[str, object] = {"$select": select}
    if hidden:
        params["includeHiddenFolders"] = True
    return client.paginate(
        path,
        params=params,
        limit=None,
        all_=True,
        cap=CAP_FOLDERS,
        page_size=page_size,
    )


def _children_path(folder_id: str) -> str:
    return odata.p("me", "mailFolders", folder_id, "childFolders")


def resolve_folder(client: GraphClient, value: str) -> str | None:
    """`--folder` → a folder id, a well-known name, or None for the whole mailbox (§6.6)."""
    bare, forced = resolve.split_id_prefix(value)
    if forced:
        return bare
    if bare.lower() == "all":
        return None
    if bare.lower() in resolve.WELL_KNOWN_FOLDERS:
        return bare.lower()
    if resolve.looks_like_id(bare, "mail_folder"):
        return bare
    folders = _folder_page(
        client, "/me/mailFolders", FOLDER_RESOLVE_SELECT, PAGE_FOLDER_RESOLVE, False
    ).items
    needle = bare.casefold()
    if not any((f.get("displayName") or "").casefold() == needle for f in folders):
        # Only descend when the top level has no match: one level, as spec §6.6 prescribes.
        children: list[dict] = []
        for folder in folders:
            if (folder.get("childFolderCount") or 0) > 0:
                children += _folder_page(
                    client,
                    _children_path(folder["id"]),
                    FOLDER_RESOLVE_SELECT,
                    PAGE_FOLDER_RESOLVE,
                    False,
                ).items
        folders = folders + children
    return resolve.pick_unique(folders, "displayName", bare, what="mail folder")["id"]


def list_folders(client: GraphClient, *, depth: int, hidden: bool) -> PageResult:
    """The folder tree, `depth` levels deep, each folder carrying a `children` list.

    `PageResult.items` are the top-level folders; `truncated` is true when any level hit the
    500-folder cap, so the caller can say the tree is incomplete.
    """
    truncated = False

    def level(path: str) -> list[dict]:
        nonlocal truncated
        page = _folder_page(client, path, FOLDER_SELECT, PAGE_FOLDERS, hidden)
        truncated = truncated or page.truncated
        return [{**f, "children": []} for f in page.items]

    tree = level("/me/mailFolders")
    frontier = tree
    for _ in range(max(depth, 1) - 1):
        deeper: list[dict] = []
        for folder in frontier:
            if (folder.get("childFolderCount") or 0) > 0:
                folder["children"] = level(_children_path(folder["id"]))
                deeper += folder["children"]
        frontier = deeper
    return PageResult(items=tree, truncated=truncated, pages=1)


# --------------------------------------------------------------------------- messages


def messages_path(folder_id: str | None) -> str:
    if folder_id is None:
        return "/me/messages"
    return odata.p("me", "mailFolders", folder_id, "messages")


def _search_post_filter(
    *, unread: bool, after: datetime | None, before: datetime | None, tz: str
) -> Callable[[dict], bool] | None:
    """The client-side pass a `$search` page needs, or None when the page can stand as fetched.

    KQL has no `isRead` term, and its date properties compare on the calendar date only — so a
    bound carrying a time of day has to be re-applied here against `receivedDateTime`. A
    date-only bound already means what the KQL date means and is not re-filtered.
    """
    lower = after if has_time_of_day(after, tz, end_of_day=False) else None
    upper = before if has_time_of_day(before, tz, end_of_day=True) else None
    if not unread and lower is None and upper is None:
        return None

    def keep(message: dict) -> bool:
        if unread and message.get("isRead"):
            return False
        if lower is None and upper is None:
            return True
        received = parse_graph_dt(message.get("receivedDateTime"))
        if received is None:  # unparseable: keep it rather than silently drop a hit
            return True
        if lower is not None and received < lower:
            return False
        return upper is None or received <= upper

    return keep


def list_messages(
    client: GraphClient,
    *,
    folder_id: str | None,
    unread: bool,
    search: str | None,
    senders: list[str],
    recipients: list[str],
    after: datetime | None,
    before: datetime | None,
    select: str | None,
    limit: int | None,
    all_: bool,
    tz: str,
) -> PageResult:
    """Messages in one folder (or the whole mailbox).

    Either a KQL `$search` or an OData `$filter`; Graph rejects the two together.
    """
    path = messages_path(folder_id)
    params: dict[str, object] = {"$select": select or LIST_SELECT}
    if search or senders or recipients:
        terms = [search] if search else []
        terms += [f"from:{a}" for a in senders] + [f"to:{a}" for a in recipients]
        if after:
            terms.append(f"received>={kql_date(after, tz)}")
        if before:
            terms.append(f"received<={kql_date(before, tz)}")
        params["$search"] = odata.kql(*terms)
        page = client.paginate(
            path,
            params=params,
            outlook_tz=True,
            limit=limit,
            all_=all_,
            cap=CAP_LIST,
            page_size=PAGE_SEARCH,
        )
        keep = _search_post_filter(unread=unread, after=after, before=before, tz=tz)
        return page if keep is None else filter_page(page, keep)
    filters = []
    if after:
        filters.append(f"receivedDateTime ge {after.isoformat()}")
    if before:
        filters.append(f"receivedDateTime le {before.isoformat()}")
    if unread:
        filters.append("isRead eq false")
    if filters:
        params["$filter"] = " and ".join(filters)
    params["$orderby"] = "receivedDateTime desc"
    return client.paginate(
        path,
        params=params,
        outlook_tz=True,
        limit=limit,
        all_=all_,
        cap=CAP_LIST,
        page_size=PAGE_FILTER,
    )


def list_drafts(client: GraphClient, *, limit: int | None, all_: bool) -> PageResult:
    return client.paginate(
        "/me/mailFolders/drafts/messages",
        params={"$select": LIST_SELECT, "$orderby": "lastModifiedDateTime desc"},
        outlook_tz=True,
        limit=limit,
        all_=all_,
        cap=CAP_LIST,
        page_size=PAGE_FILTER,
    )


def get_message(client: GraphClient, message_id: str, *, headers: bool, html: bool) -> dict:
    """One message with its body. `Prefer: outlook.body-content-type="text"` unless `html`."""
    select = LIST_SELECT + READ_EXTRA + (HEADERS_EXTRA if headers else "")
    return client.get(
        odata.p("me", "messages", message_id),
        params={"$select": select},
        outlook_tz=True,
        text_body=not html,
    )


def body_text(message: dict, *, html: bool) -> str:
    """The message body as it should be shown: raw with `--html`, else text or Markdown."""
    body = message.get("body") or {}
    content = body.get("content") or ""
    if html or (body.get("contentType") or "").lower() != "html":
        return content
    return to_markdown(content, "mail")


def flags(message: dict) -> str:
    """The `*` unread / `A` attachment / `!` high-importance markers of spec §8.2."""
    return (
        ("*" if not message.get("isRead") else "")
        + ("A" if message.get("hasAttachments") else "")
        + ("!" if message.get("importance") == "high" else "")
    )


def recipients_text(message: dict, key: str = "toRecipients") -> str:
    return ", ".join(fmt_person(r) for r in message.get(key) or [])


def message_columns(tz: str) -> list[Column]:
    return [
        Column("id", "id"),
        Column("received", lambda m: fmt_dt(m.get("receivedDateTime"), tz)),
        Column("flags", flags),
        Column("from", lambda m: fmt_person(m.get("from"))),
        Column("subject", lambda m: truncate(m.get("subject"))),
    ]


# --------------------------------------------------------------------------- attachments


def attachment_type(attachment: dict) -> str:
    """`fileAttachment`, `itemAttachment`, `referenceAttachment`, or "" when Graph said nothing."""
    return str(attachment.get("@odata.type") or "").rsplit(".", 1)[-1]


def attachment_kind(attachment: dict) -> str:
    """The short form for the `type` column: `file`, `item`, `reference`, or `?`."""
    return attachment_type(attachment).removesuffix("Attachment") or "?"


def is_file_attachment(attachment: dict) -> bool:
    return attachment_type(attachment) == "fileAttachment"


def list_attachments(client: GraphClient, message_id: str) -> list[dict]:
    payload = client.get(
        odata.p("me", "messages", message_id, "attachments"),
        params={"$select": ATTACHMENT_SELECT},
    )
    return (payload or {}).get("value") or []


def download_attachment(
    client: GraphClient, message_id: str, attachment_id: str, dest: Path
) -> DownloadResult:
    path = odata.p("me", "messages", message_id, "attachments", attachment_id) + "/$value"
    return client.download(path, dest)


# --------------------------------------------------------------------------- composing


@dataclass(frozen=True)
class SendParams:
    """Everything `mail send` and `mail drafts create` need to build a message."""

    to: list[str]
    body: str
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    subject: str | None = None
    html: bool = False
    attachments: list[Path] = field(default_factory=list)
    importance: str = "normal"
    save_to_sent: bool = True

    @cached_property
    def sizes(self) -> list[int]:
        """Each attachment's size on disk, statted once, rejecting what Outlook will not take."""
        measured = []
        for file in self.attachments:
            size = file.stat().st_size
            if size > MAX_ATTACHMENT:
                raise UsageError(
                    "USAGE",
                    f"{file.name} is {size} bytes; Outlook attachments stop at 150 MB",
                )
            measured.append(size)
        return measured


def _recipients(addresses: list[str]) -> list[dict]:
    return [{"emailAddress": {"address": a}} for a in addresses]


def attachment_sizes(params: SendParams) -> list[int]:
    """Each attachment's size on disk (cached on `params`)."""
    return params.sizes


def needs_draft_path(params: SendParams) -> bool:
    """Whether the attachments are too big for one `/me/sendMail` request (spec §8.2)."""
    return sum(params.sizes) > config.MAIL_INLINE_TOTAL


def _send_needs_draft_path(params: SendParams) -> bool:
    """`needs_draft_path` for `mail send`, where the draft path cannot honour every option.

    Graph always files the draft in Sent Items when `POST /me/messages/{id}/send` sends it;
    only `/me/sendMail` takes `saveToSentItems`. Refusing beats silently ignoring the flag.
    """
    draft = needs_draft_path(params)
    if draft and not params.save_to_sent:
        raise UsageError(
            "USAGE",
            "--no-save-to-sent is not supported with attachments over the inline limit "
            "(Graph keeps a Sent Items copy on the draft path)",
        )
    return draft


def _content_type(file: Path) -> str:
    return guess_type(file.name)[0] or "application/octet-stream"


def _file_attachment(file: Path, *, for_plan: bool) -> dict:
    """A `fileAttachment`; a dry run shows the `$file` stand-in instead of the base64 bytes."""
    content_type = _content_type(file)
    if for_plan:
        content: Any = {
            "$file": str(file),
            "bytes": file.stat().st_size,
            "contentType": content_type,
        }
    else:
        content = b64encode(file.read_bytes()).decode("ascii")
    return {
        "@odata.type": FILE_ATTACHMENT,
        "name": file.name,
        "contentType": content_type,
        "contentBytes": content,
    }


def build_message(params: SendParams, *, for_plan: bool) -> dict:
    """The Graph `message` body. Attachments ride along only on the inline path."""
    message: dict[str, Any] = {
        "subject": params.subject or "(no subject)",
        "body": {
            "contentType": "HTML" if params.html else "Text",
            "content": params.body,
        },
        "toRecipients": _recipients(params.to),
        "importance": params.importance,
    }
    if params.cc:
        message["ccRecipients"] = _recipients(params.cc)
    if params.bcc:
        message["bccRecipients"] = _recipients(params.bcc)
    if params.attachments and not needs_draft_path(params):
        message["attachments"] = [
            _file_attachment(f, for_plan=for_plan) for f in params.attachments
        ]
    return message


def _message_base(message_id: str) -> str:
    """`/me/messages/<id>`, leaving the dry run's `{draftId}` placeholder unencoded."""
    if message_id == DRAFT_ID:
        return "/me/messages/" + DRAFT_ID
    return odata.p("me", "messages", message_id)


def _attachment_steps(client: GraphClient, base: str, files: list[Path], *, for_plan: bool) -> Plan:
    """One step per attachment: a POST for small files, an upload session for big ones."""
    steps: Plan = []
    for file in files:
        size = file.stat().st_size
        if size < config.MAIL_SMALL_ATTACHMENT:
            steps.append(
                PlannedRequest(
                    "POST",
                    client.url(base + "/attachments"),
                    dict(JSON_HEADERS),
                    _file_attachment(file, for_plan=for_plan),
                )
            )
            continue
        item = {"AttachmentItem": {"attachmentType": "file", "name": file.name, "size": size}}
        steps.append(
            PlannedRequest(
                "POST",
                client.url(base + "/attachments/createUploadSession"),
                dict(JSON_HEADERS),
                item,
                file=file,
                chunk_size=config.CHUNK_OUTLOOK,
                note=f"upload {size} bytes in {ceil(size / config.CHUNK_OUTLOOK)} chunks",
            )
        )
    return steps


def _send_step(client: GraphClient, base: str) -> PlannedRequest:
    return PlannedRequest("POST", client.url(base + "/send"), {}, None, expect="none")


def plan_send(client: GraphClient, params: SendParams, *, for_plan: bool = False) -> Plan:
    """`mail send`: one `/me/sendMail`, or draft → attachments → send (spec §8.2)."""
    if not _send_needs_draft_path(params):
        payload = {
            "message": build_message(params, for_plan=for_plan),
            "saveToSentItems": params.save_to_sent,
        }
        return [
            PlannedRequest(
                "POST",
                client.url("/me/sendMail"),
                dict(JSON_HEADERS),
                payload,
                note=INLINE_NOTE,
                expect="none",
            )
        ]
    base = _message_base(DRAFT_ID)
    steps = [
        PlannedRequest(
            "POST",
            client.url("/me/messages"),
            dict(JSON_HEADERS),
            build_message(params, for_plan=for_plan),
            note=DRAFT_NOTE,
        )
    ]
    steps += _attachment_steps(client, base, params.attachments, for_plan=for_plan)
    steps.append(_send_step(client, base))
    return steps


def run_send(client: GraphClient, params: SendParams) -> dict:
    """Send for real, threading the new draft's id through the later steps."""
    if not _send_needs_draft_path(params):
        client.execute(plan_send(client, params)[0])
        return {"status": "sent"}
    draft = run_create_draft(client, params)
    base = _message_base(draft["id"])
    client.execute(_send_step(client, base))
    return {"status": "sent", "draftId": draft["id"]}


def plan_create_draft(client: GraphClient, params: SendParams, *, for_plan: bool = False) -> Plan:
    steps = [
        PlannedRequest(
            "POST",
            client.url("/me/messages"),
            dict(JSON_HEADERS),
            build_message(params, for_plan=for_plan),
        )
    ]
    if needs_draft_path(params):
        steps += _attachment_steps(
            client, _message_base(DRAFT_ID), params.attachments, for_plan=for_plan
        )
    return steps


def run_create_draft(client: GraphClient, params: SendParams) -> dict:
    draft = client.execute(plan_create_draft(client, params)[0])
    if needs_draft_path(params):
        base = _message_base(draft["id"])
        for step in _attachment_steps(client, base, params.attachments, for_plan=False):
            client.execute(step)
    return draft


def plan_send_draft(client: GraphClient, message_id: str) -> Plan:
    return [_send_step(client, _message_base(message_id))]


def plan_reply(
    client: GraphClient,
    message_id: str,
    *,
    body: str,
    html: bool,
    reply_all: bool,
    extra_to: list[str],
) -> Plan:
    verb = "replyAll" if reply_all else "reply"
    payload: dict[str, Any] = (
        {"message": {"body": {"contentType": "HTML", "content": body}}}
        if html
        else {"comment": body}
    )
    if extra_to:
        payload.setdefault("message", {})["toRecipients"] = _recipients(extra_to)
    return [
        PlannedRequest(
            "POST",
            client.url(_message_base(message_id) + f"/{verb}"),
            dict(JSON_HEADERS),
            payload,
            expect="none",
        )
    ]


def plan_forward(
    client: GraphClient, message_id: str, *, to: list[str], body: str, html: bool
) -> Plan:
    payload: dict[str, Any] = {"toRecipients": _recipients(to)}
    if html:
        payload["message"] = {"body": {"contentType": "HTML", "content": body}}
    else:
        payload["comment"] = body
    return [
        PlannedRequest(
            "POST",
            client.url(_message_base(message_id) + "/forward"),
            dict(JSON_HEADERS),
            payload,
            expect="none",
        )
    ]


def run_plan(client: GraphClient, plan: Plan) -> list:
    """Execute a plan whose steps are independent (no ids threaded between them)."""
    return [client.execute(step) for step in plan]


# --------------------------------------------------------------------------- organising


def plan_mark(client: GraphClient, message_ids: list[str], patch: dict) -> Plan:
    """One PATCH per message; more than one goes out as a single `$batch` (spec §5.4)."""
    batched = len(message_ids) > 1
    steps: Plan = []
    for position, message_id in enumerate(message_ids):
        note = None
        if batched and position == 0:
            note = f"sent as one $batch with {len(message_ids)} PATCH sub-requests"
        steps.append(
            PlannedRequest(
                "PATCH",
                client.url(_message_base(message_id)),
                dict(JSON_HEADERS),
                dict(patch),
                note=note,
            )
        )
    return steps


def run_mark(client: GraphClient, message_ids: list[str], patch: dict) -> list[dict]:
    if len(message_ids) == 1:
        return [client.execute(plan_mark(client, message_ids, patch)[0])]
    requests = [
        BatchRequest(str(n), "PATCH", _message_base(message_id), body=dict(patch))
        for n, message_id in enumerate(message_ids, 1)
    ]
    updated = []
    for response in client.batch(requests):
        if response.error is not None:
            raise response.error
        updated.append(response.body)
    return updated


def plan_move(client: GraphClient, message_id: str, folder: str) -> Plan:
    destination = resolve_folder(client, folder)
    if destination is None:
        raise UsageError("USAGE", "--folder all is not a destination; name one folder")
    return [
        PlannedRequest(
            "POST",
            client.url(_message_base(message_id) + "/move"),
            dict(JSON_HEADERS),
            {"destinationId": destination},
        )
    ]


def plan_delete(client: GraphClient, message_id: str) -> Plan:
    return [
        PlannedRequest("DELETE", client.url(_message_base(message_id)), {}, None, expect="none")
    ]


def list_rules(client: GraphClient) -> list[dict]:
    return (client.get("/me/mailFolders/inbox/messageRules") or {}).get("value") or []


def list_categories(client: GraphClient) -> list[dict]:
    return (client.get("/me/outlook/masterCategories") or {}).get("value") or []
