"""OneDrive-only Graph operations (spec §8.11): base resolution for `--drive`, plus the two
listings that are always relative to the signed-in user's own drive (`sharedWithMe`, `recent`).

Every other onedrive verb delegates straight to `mgraphctl.graph.files` with a `base` resolved
by `base_for()` here; that module already implements every drive-item operation.
"""

from __future__ import annotations

from mgraphctl import odata
from mgraphctl.http import GraphClient, PageResult

CAP_SHARED_WITH_ME = 200
CAP_RECENT = 200


def base_for(drive_id: str | None) -> str:
    """`/me/drive`, or `/drives/{id}` when `--drive` names another drive."""
    if drive_id is None:
        return "/me/drive"
    return odata.p("drives", drive_id)


def shared_with_me(client: GraphClient, *, limit: int) -> PageResult:
    """Items other people have shared (§8.11 `shared-with-me`); always the caller's own drive."""
    return client.paginate(
        "/me/drive/sharedWithMe", limit=limit, all_=False, cap=CAP_SHARED_WITH_ME, page_size=None
    )


def recent(client: GraphClient, *, limit: int) -> PageResult:
    """Recently used files (§8.11 `recent`); always the caller's own drive."""
    return client.paginate(
        "/me/drive/recent", limit=limit, all_=False, cap=CAP_RECENT, page_size=None
    )
