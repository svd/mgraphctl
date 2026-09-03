"""Graph operations for manager, direct reports and the management chain (spec §8.6).

Pure: client and parameters in, Graph dicts / PageResult / list[dict] out.
"""

from __future__ import annotations

from mgraphctl import odata
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


def chain_expand(client: GraphClient, upn: str | None, *, max_levels: int) -> list[dict]:
    """The management chain via one `$expand=manager($levels=max)` call (spec §8.6 `chain`).

    Self, then each nested `manager`, from the single response. Raises `GraphError` (400/403
    on a tenant that rejects the expand) for the caller to catch and fall back to
    `chain_iterative`.
    """
    path = _user_path(upn)
    expand = f"manager($levels=max;$select={CHAIN_SELECT})"
    obj = client.get(path, params={"$expand": expand, "$count": True}, headers=EVENTUAL)
    return _walk_expanded(obj)[: max_levels + 1]


def chain_iterative(client: GraphClient, upn: str | None, *, max_levels: int) -> list[dict]:
    """The management chain via a `/users/{id}/manager` walk, one level at a time.

    The fallback path for tenants that reject `$expand`; callers gate this on
    `User.Read.All` before calling it (spec §8.6, §4.4 — the branch-level gate lives in the
    command layer, not here).
    """
    start = client.get(_user_path(upn), params={"$select": CHAIN_SELECT})
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
