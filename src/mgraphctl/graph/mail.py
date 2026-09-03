"""Graph operations for Outlook mail (spec §8.2).

Pure: client and parameters in, Graph dicts / `PageResult` / `Plan` out. Nothing here prints.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from mgraphctl import odata, resolve
from mgraphctl.html import to_markdown
from mgraphctl.http import DownloadResult, GraphClient, PageResult
from mgraphctl.render import Column, fmt_dt, fmt_person, kql_date, truncate

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

JSON = {"Content-Type": "application/json"}


# --------------------------------------------------------------------------- folders


def _folder_page(client: GraphClient, path: str, select: str, page_size: int, hidden: bool) -> list:
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
    ).items


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
    )
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
                )
        folders = folders + children
    return resolve.pick_unique(folders, "displayName", bare, what="mail folder")["id"]


def list_folders(client: GraphClient, *, depth: int, hidden: bool) -> list[dict]:
    """The folder tree, `depth` levels deep, each folder carrying a `children` list."""

    def level(path: str) -> list[dict]:
        return [
            {**f, "children": []}
            for f in _folder_page(client, path, FOLDER_SELECT, PAGE_FOLDERS, hidden)
        ]

    tree = level("/me/mailFolders")
    frontier = tree
    for _ in range(max(depth, 1) - 1):
        deeper: list[dict] = []
        for folder in frontier:
            if (folder.get("childFolderCount") or 0) > 0:
                folder["children"] = level(_children_path(folder["id"]))
                deeper += folder["children"]
        frontier = deeper
    return tree


# --------------------------------------------------------------------------- messages


def messages_path(folder_id: str | None) -> str:
    if folder_id is None:
        return "/me/messages"
    return odata.p("me", "mailFolders", folder_id, "messages")


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
        if unread:  # KQL has no isRead term, so drop the read ones here.
            return PageResult(
                [m for m in page.items if not m.get("isRead")], page.truncated, page.pages
            )
        return page
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
