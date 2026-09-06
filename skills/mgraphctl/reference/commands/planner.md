# `planner`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

Planner endpoints accept no OData parameters, so `--limit` slices client-side after the whole
collection has been fetched.

### `planner plans`

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | 50 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/planner/plans`, unioned with the plans of every Microsoft 365 group you belong
  to — `GET /me/memberOf/microsoft.graph.group?$filter=groupTypes/any(c:c eq 'Unified')&$count=true`
  with `ConsistencyLevel: eventual`, then a `POST /$batch` of `GET /groups/{id}/planner/plans` —
  deduplicated by id.
- **Scopes:** `Tasks.ReadWrite`, `Group.Read.All`
- **Notes:** text shows the owning group's name next to each plan.

### `planner plan PLAN`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /planner/plans/{id}` plus `GET /planner/plans/{id}/details`.
- **Scopes:** `Tasks.ReadWrite`
- **Notes:** JSON is the plan with a `details` member.

### `planner buckets PLAN`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /planner/plans/{id}/buckets`.
- **Scopes:** `Tasks.ReadWrite`

### `planner tasks [PLAN]`

| Option | Default | Meaning |
|---|---|---|
| `--my` | off | Your tasks across every plan, instead of one plan's tasks. |
| `--bucket NAME\|ID` | — | Only tasks in this bucket. |
| `--include-completed` | off | Also show tasks at 100 %. |
| `--limit N` | 50 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /planner/plans/{id}/tasks`, or `GET /me/planner/tasks` with `--my`; `--my` adds a
  `POST /$batch` of `GET /planner/plans/{planId}` (up to 20 distinct plans) for plan titles, and
  bucket names are fetched for the plans involved.
- **Scopes:** `Tasks.ReadWrite`
- **Notes:** completed tasks are hidden unless `--include-completed`. Columns: id, percent,
  priority, due, bucket, plan (with `--my`), title.

### `planner task ID`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /planner/tasks/{id}` plus `GET /planner/tasks/{id}/details`.
- **Scopes:** `Tasks.ReadWrite`
- **Notes:** an error fetching the details is swallowed; the task still prints.

### `planner create`

| Option | Default | Meaning |
|---|---|---|
| `--plan PLAN` | — | Plan name or id. Required. |
| `--title TEXT` | — | Task title. Required. |
| `--bucket NAME\|ID` | — | Bucket to file it under. |
| `--due DATE` | — | Due date. |
| `--assign UPN` | — | Assignee. Repeatable. |
| `--priority 0-10` | — | Planner priority. |
| `--description TEXT` | — | Task description. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /users/{upn}?$select=id` per assignee, then
  `POST /planner/tasks {planId, bucketId, title, dueDateTime, priority, assignments}`;
  `--description` adds `GET …/details` for the etag and `PATCH …/details` with `If-Match`.
- **Scopes:** `Tasks.ReadWrite`
- **Notes:** write. Assignees are given as UPNs, not object ids.

### `planner update ID`

| Option | Default | Meaning |
|---|---|---|
| `--title TEXT` | — | New title. |
| `--due DATE` | — | New due date. |
| `--percent N` | — | Completion: 0, 50 or 100. |
| `--bucket NAME\|ID` | — | Move to another bucket. |
| `--priority 0-10` | — | New priority. |
| `--assign UPN` | — | Add an assignee. Repeatable. |
| `--unassign UPN` | — | Remove an assignee. Repeatable. |
| `--description TEXT` | — | New description. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /planner/tasks/{id}` for the etag, then `PATCH /planner/tasks/{id}` with
  `If-Match` and `Prefer: return=representation`; a 412 re-reads the etag once and retries.
- **Scopes:** `Tasks.ReadWrite`
- **Notes:** write. Planner tracks completion as a percentage; Planner's own UI only ever sets
  0, 50 or 100.

### `planner complete ID`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** the `planner update` request with `percentComplete: 100`.
- **Scopes:** `Tasks.ReadWrite`
- **Notes:** write.

### `planner delete ID`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /planner/tasks/{id}` for the etag, then `DELETE /planner/tasks/{id}` with
  `If-Match`.
- **Scopes:** `Tasks.ReadWrite`
- **Notes:** write. Planner has no recycle bin — a deleted task is gone.
