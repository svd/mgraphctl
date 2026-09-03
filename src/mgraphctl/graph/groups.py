"""Graph operations for Microsoft 365 groups (spec §8.16).

Pure: client and parameters in, Graph dicts / PageResult out.
"""

from __future__ import annotations

from mgraphctl import odata
from mgraphctl.graph.users import GROUPS_PATH, list_unified_groups
from mgraphctl.http import GraphClient, PageResult
from mgraphctl.resolve import looks_like_id, pick_unique

LIST_SELECT = "id,displayName,mail,groupTypes,description"
MEMBERS_SELECT = "id,displayName,userPrincipalName,mail,jobTitle"

PAGE = 100
CAP = 999


def list_groups(client: GraphClient, *, unified: bool, limit: int, all_: bool) -> PageResult:
    """Groups the signed-in user belongs to; `--unified` narrows to Microsoft 365 groups."""
    if unified:
        items = list_unified_groups(client)
        bound = CAP if all_ else min(limit, CAP)
        return PageResult(items=items[:bound], truncated=len(items) > bound, pages=1)
    return client.paginate(
        GROUPS_PATH,
        params={"$select": LIST_SELECT},
        limit=limit,
        all_=all_,
        cap=CAP,
        page_size=PAGE,
    )


def list_members(client: GraphClient, group_id: str, *, limit: int, all_: bool) -> PageResult:
    path = f"{odata.p('groups', group_id)}/members"
    return client.paginate(
        path, params={"$select": MEMBERS_SELECT}, limit=limit, all_=all_, cap=CAP, page_size=PAGE
    )


def resolve_group(client: GraphClient, value: str) -> dict:
    """Turn a group name or id into a group object (at least `id`); by-name via `memberOf`."""
    if looks_like_id(value, "group"):
        return {"id": value}
    page = client.paginate(
        GROUPS_PATH,
        params={"$select": LIST_SELECT},
        limit=None,
        all_=True,
        cap=CAP,
        page_size=PAGE,
    )
    return pick_unique(page.items, "displayName", value, what="group")
