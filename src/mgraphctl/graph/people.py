"""Graph operations for people, contacts, directory users and photos (spec §8.5).

Pure: client and parameters in, Graph dicts / PageResult / DownloadResult out.
"""

from __future__ import annotations

from pathlib import Path

from mgraphctl import odata
from mgraphctl.errors import GraphError
from mgraphctl.http import DownloadResult, GraphClient, PageResult

PEOPLE_SELECT = (
    "id,displayName,scoredEmailAddresses,jobTitle,department,companyName,personType,"
    "userPrincipalName"
)
CONTACTS_SELECT = "id,displayName,emailAddresses,mobilePhone,businessPhones,jobTitle,companyName"

PAGE = 50
CAP = 250  # spec §5.3: people search, contacts — page_size 50, default limit 20, --all cap 250


def search_people(client: GraphClient, q: str, *, limit: int, all_: bool) -> PageResult:
    """`/me/people` relevance search (spec §8.5 `search`); the endpoint is in maintenance mode."""
    params = {"$search": odata.kql(q), "$select": PEOPLE_SELECT}
    return client.paginate(
        "/me/people", params=params, limit=limit, all_=all_, cap=CAP, page_size=PAGE
    )


def _contact_matches(contact: dict, term: str) -> bool:
    if term in (contact.get("displayName") or "").casefold():
        return True
    return any(
        term in (addr.get("address") or "").casefold()
        for addr in contact.get("emailAddresses") or []
    )


def list_contacts(client: GraphClient, *, search: str | None, limit: int, all_: bool) -> PageResult:
    """Contacts, optionally `$search`-filtered; a 400 on `$search` falls back to a client-side
    substring match over displayName/email of up to 250 contacts (spec §8.5 `contacts`).
    """
    if not search:
        return client.paginate(
            "/me/contacts",
            params={"$select": CONTACTS_SELECT},
            limit=limit,
            all_=all_,
            cap=CAP,
            page_size=PAGE,
        )
    params = {"$select": CONTACTS_SELECT, "$search": odata.kql(search)}
    try:
        return client.paginate(
            "/me/contacts", params=params, limit=limit, all_=all_, cap=CAP, page_size=PAGE
        )
    except GraphError as exc:
        if exc.status != 400:
            raise
        page = client.paginate(
            "/me/contacts",
            params={"$select": CONTACTS_SELECT},
            limit=None,
            all_=True,
            cap=CAP,
            page_size=CAP,
        )
        term = search.casefold()
        filtered = [c for c in page.items if _contact_matches(c, term)]
        bound = CAP if all_ else min(limit, CAP)
        return PageResult(items=filtered[:bound], truncated=len(filtered) > bound, pages=page.pages)


def get_contact(client: GraphClient, contact_id: str) -> dict:
    return client.get(odata.p("me", "contacts", contact_id))


def download_photo(client: GraphClient, upn: str | None, size: str, dest: Path) -> DownloadResult:
    """`/me/photo/$value` for the signed-in user; `/users/{upn}/photos/{size}/$value` otherwise."""
    path = "/me/photo/$value" if upn is None else f"{odata.p('users', upn)}/photos/{size}/$value"
    return client.download(path, dest)
