"""Graph operations for users and the directory (spec §8.1, §8.5, §8.16).

Pure: client and parameters in, Graph dicts or a `PageResult` out.
"""

from __future__ import annotations

from mgraphctl import odata
from mgraphctl.errors import UsageError
from mgraphctl.http import GraphClient, PageResult
from mgraphctl.resolve import looks_like_id, pick_unique

ME_SELECT = (
    "id,displayName,userPrincipalName,mail,jobTitle,department,officeLocation,"
    "businessPhones,mobilePhone,preferredLanguage"
)
USER_SELECT = (
    "id,displayName,userPrincipalName,mail,jobTitle,department,officeLocation,"
    "businessPhones,mobilePhone"
)
USERS_SEARCH_SELECT = "id,displayName,userPrincipalName,mail,jobTitle,department,officeLocation"

GROUPS_PATH = "/me/memberOf/microsoft.graph.group"
UNIFIED_FILTER = "groupTypes/any(c:c eq 'Unified')"
EVENTUAL = {"ConsistencyLevel": "eventual"}

PAGE_SEARCH = 100
PAGE_GROUPS = 999
CAP = 999


def user_path(ref: str) -> str:
    """`/me` for the signed-in user, `/users/<ref>` (encoded) for anyone else."""
    return "/me" if ref == "me" else odata.p("users", ref)


def get_me(client: GraphClient, *, select: str = ME_SELECT) -> dict:
    return client.get("/me", params={"$select": select})


def get_user(client: GraphClient, ref: str, *, select: str = USER_SELECT) -> dict:
    return client.get(user_path(ref), params={"$select": select})


def search_users(client: GraphClient, q: str, *, limit: int, all_: bool) -> PageResult:
    """Directory search. `$search` is tokenised, not substring, and needs ConsistencyLevel."""
    term = f'"displayName:{q}" OR "mail:{q}"'
    params = {"$search": term, "$count": True, "$select": USERS_SEARCH_SELECT}
    return client.paginate(
        "/users",
        params=params,
        headers=EVENTUAL,
        limit=limit,
        all_=all_,
        cap=CAP,
        page_size=PAGE_SEARCH,
    )


def list_unified_groups(client: GraphClient) -> list[dict]:
    """Every Microsoft 365 group the signed-in user belongs to, id and name only."""
    params = {"$filter": UNIFIED_FILTER, "$count": True, "$select": "id,displayName"}
    return client.paginate(
        GROUPS_PATH,
        params=params,
        headers=EVENTUAL,
        limit=None,
        all_=True,
        cap=CAP,
        page_size=PAGE_GROUPS,
    ).items


def resolve_user(client: GraphClient, value: str, *, can_search: bool) -> dict:
    """Turn a UPN, id or display name into a user object (§6.6)."""
    if looks_like_id(value, "user"):
        return get_user(client, value)
    if not can_search:
        raise UsageError(
            "USAGE",
            f"{value!r} is not a UPN or id; directory search needs User.ReadBasic.All "
            "(login --scopes extended)",
        )
    page = search_users(client, value, limit=50, all_=False)
    return pick_unique(page.items, "displayName", value, what="user")
