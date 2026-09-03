"""Graph operations for manager, direct reports and the management chain (spec §8.6).

Pure: client and parameters in, Graph dicts / PageResult / list[dict] out.
"""

from __future__ import annotations

from mgraphctl import odata
from mgraphctl.cli import gate
from mgraphctl.errors import GraphError, NotFoundError
from mgraphctl.http import GraphClient, PageResult

MANAGER_SELECT = "id,displayName,userPrincipalName,mail,jobTitle,department"
CHAIN_SELECT = "id,displayName,userPrincipalName,jobTitle"
EVENTUAL = {"ConsistencyLevel": "eventual"}

PAGE = 100
CAP = 500


def _user_path(upn: str | None) -> str:
    return "/me" if upn is None else odata.p("users", upn)


def manager(client: GraphClient, upn: str | None) -> dict:
    """The user's manager (self by default). 404 becomes a clear NOT_FOUND (spec §8.6)."""
    try:
        return client.get(f"{_user_path(upn)}/manager", params={"$select": MANAGER_SELECT})
    except GraphError as exc:
        if exc.status != 404:
            raise
        raise NotFoundError("NOT_FOUND", "No manager found", request_id=exc.request_id) from exc


def reports(client: GraphClient, upn: str | None, *, limit: int, all_: bool) -> PageResult:
    """The user's direct reports (self by default)."""
    path = f"{_user_path(upn)}/directReports"
    return client.paginate(
        path, params={"$select": MANAGER_SELECT}, limit=limit, all_=all_, cap=CAP, page_size=PAGE
    )


def _walk_expanded(obj: dict) -> list[dict]:
    """Self, then each nested `manager`, flattened from the `$expand` response."""
    levels = []
    current: dict | None = obj
    while current is not None:
        levels.append({k: v for k, v in current.items() if k != "manager"})
        current = current.get("manager")
    return levels


def _iterative_chain(client: GraphClient, start: dict, max_levels: int) -> list[dict]:
    """Walk `/users/{id}/manager` one level at a time, for tenants that reject `$expand`."""
    levels = [start]
    current_id = start.get("id")
    while current_id and len(levels) <= max_levels:
        try:
            nxt = client.get(
                f"{odata.p('users', current_id)}/manager", params={"$select": CHAIN_SELECT}
            )
        except GraphError as exc:
            if exc.status == 404:
                break
            raise
        levels.append(nxt)
        current_id = nxt.get("id")
    return levels


def chain(client: GraphClient, upn: str | None, *, max_levels: int) -> list[dict]:
    """The management chain from self upward (spec §8.6 `chain`).

    `$expand=manager($levels=max)` in one call; on 400/403 (a tenant that rejects the
    expand), an iterative `/users/{id}/manager` walk, gated on `User.Read.All`.
    """
    path = _user_path(upn)
    expand = f"manager($levels=max;$select={CHAIN_SELECT})"
    try:
        obj = client.get(path, params={"$expand": expand, "$count": True}, headers=EVENTUAL)
    except GraphError as exc:
        if exc.status not in (400, 403):
            raise
        gate(["User.Read.All"])
        start = client.get(path, params={"$select": CHAIN_SELECT})
        return _iterative_chain(client, start, max_levels)
    return _walk_expanded(obj)[: max_levels + 1]
