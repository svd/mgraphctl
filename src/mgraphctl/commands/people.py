"""People, contacts and directory users (spec §8.5)."""

from pathlib import Path
from typing import Annotated

import typer

from mgraphctl import auth
from mgraphctl.cli import (
    AllFlag,
    JsonFlag,
    LimitOpt,
    gate,
    graph_command,
    make_noun_app,
    page_bounds,
)
from mgraphctl.errors import AuthError
from mgraphctl.graph import people
from mgraphctl.graph import users as graph_users
from mgraphctl.http import GraphClient
from mgraphctl.render import Column, FileResult, ListResult, ObjectResult, fmt_size

app = make_noun_app("People, contacts and directory users.")

CONTACT_FIELDS = [
    ("Name", "displayName"),
    ("Email", lambda c: _first_email(c)),
    ("Mobile", "mobilePhone"),
    ("Business phones", lambda c: ", ".join(c.get("businessPhones") or [])),
    ("Title", "jobTitle"),
    ("Company", "companyName"),
    ("Contact id", "id"),
]

USER_FIELDS = [
    ("Name", "displayName"),
    ("UPN", "userPrincipalName"),
    ("Mail", "mail"),
    ("Title", "jobTitle"),
    ("Dept", "department"),
    ("Office", "officeLocation"),
    ("Phones", lambda u: ", ".join(u.get("businessPhones") or [])),
    ("Mobile", "mobilePhone"),
    ("User id", "id"),
]


def _first_scored_email(p: dict) -> str:
    emails = p.get("scoredEmailAddresses") or []
    return emails[0].get("address", "") if emails else ""


def _first_email(c: dict) -> str:
    emails = c.get("emailAddresses") or []
    return emails[0].get("address", "") if emails else ""


def _first_phone(c: dict) -> str:
    phones = c.get("businessPhones") or []
    return c.get("mobilePhone") or (phones[0] if phones else "")


def _has_scope(scopes: list[str]) -> bool:
    """Whether the current token already carries `scopes`, without failing the command."""
    try:
        gate(scopes)
    except AuthError:
        return False
    return True


@app.command("search")
@graph_command(scopes=["People.Read"])
def search(
    client: GraphClient,
    q: Annotated[str, typer.Argument(metavar="Q")],
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """Search people relevant to the signed-in user (`/me/people`)."""
    limit, all_ = page_bounds(limit, all_, default=20)
    page = people.search_people(client, q, limit=limit, all_=all_)
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        hit_cap=people.CAP if all_ else None,
        columns=[
            Column("id", "id"),
            Column("name", "displayName"),
            Column("email", _first_scored_email),
            Column("title", "jobTitle"),
            Column("department", "department"),
            Column("type", lambda p: (p.get("personType") or {}).get("class", "")),
        ],
    )


@app.command("contacts")
@graph_command(scopes=["Contacts.Read"])
def contacts(
    client: GraphClient,
    search: Annotated[str | None, typer.Option("--search", help="Filter by name or email.")] = None,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List the signed-in user's contacts."""
    limit, all_ = page_bounds(limit, all_, default=20)
    page = people.list_contacts(client, search=search, limit=limit, all_=all_)
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        hit_cap=people.CAP if all_ else None,
        columns=[
            Column("id", "id"),
            Column("name", "displayName"),
            Column("email", _first_email),
            Column("phone", _first_phone),
            Column("title", "jobTitle"),
            Column("company", "companyName"),
        ],
    )


@app.command("contact")
@graph_command(scopes=["Contacts.Read"])
def contact(
    client: GraphClient,
    contact_id: Annotated[str, typer.Argument(metavar="ID")],
    json_: JsonFlag = False,
):
    """Show one contact."""
    return ObjectResult(obj=people.get_contact(client, contact_id), fields=list(CONTACT_FIELDS))


@app.command("users")
@graph_command(scopes=["User.ReadBasic.All"])
def users(
    client: GraphClient,
    q: Annotated[str, typer.Argument(metavar="Q")],
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """Search the directory for users (`/users`, tokenised `$search`)."""
    limit, all_ = page_bounds(limit, all_, default=20)
    page = graph_users.search_users(client, q, limit=limit, all_=all_)
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        hit_cap=graph_users.CAP if all_ else None,
        columns=[
            Column("id", "id"),
            Column("name", "displayName"),
            Column("upn", "userPrincipalName"),
            Column("mail", "mail"),
            Column("title", "jobTitle"),
            Column("department", "department"),
        ],
    )


@app.command("user")
@graph_command(scopes=["User.Read"])
def user(
    client: GraphClient,
    ref: Annotated[str, typer.Argument(metavar="UPN|ID")],
    json_: JsonFlag = False,
):
    """Look up one org user, by UPN, id, `me`, or (with User.ReadBasic.All) display name."""
    can_search = _has_scope(["User.ReadBasic.All"])
    obj = graph_users.resolve_user(client, ref, can_search=can_search)
    return ObjectResult(obj=obj, fields=list(USER_FIELDS))


@app.command("photo")
@graph_command(scopes=["User.Read"])
def photo(
    client: GraphClient,
    upn: Annotated[str | None, typer.Argument(metavar="UPN")] = None,
    output: Annotated[Path | None, typer.Option("--output", help="Destination file.")] = None,
    size: Annotated[str, typer.Option("--size", help="Photo size (others only).")] = "96x96",
    json_: JsonFlag = False,
):
    """Download a profile photo (self by default)."""
    if upn is not None:
        gate(["User.ReadBasic.All"])
        stem = upn
    else:
        claims = auth.decode_jwt(auth.get_access_token(False))
        stem = claims.get("upn") or "me"
    dest = output or Path(f"{stem}.jpg")
    got = people.download_photo(client, upn, size, dest)
    return FileResult(
        path=got.path,
        bytes=got.bytes,
        meta=dict(contentType=got.content_type),
        message=f"Downloaded photo ({fmt_size(got.bytes)}) to {got.path}",
    )
