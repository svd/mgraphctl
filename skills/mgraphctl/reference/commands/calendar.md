# `calendar`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

### `calendar list`

| Option | Default | Meaning |
|---|---|---|
| `--start DT` (alias `--after`) | now | Window start. |
| `--end DT` (alias `--before`) | `--days` out | Window end. |
| `--days N` | 7 | Days from `--start`, when `--end` is not given. |
| `--calendar NAME\|ID` | the default calendar | Which calendar to read. |
| `--search KW` | — | Client-side match on subject, organizer and attendees. |
| `--limit N` | 50 | Maximum items. |
| `--all` | off | Fetch every page, cap 200. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/calendarView` (or `/me/calendars/{id}/calendarView`) with
  `startDateTime`, `endDateTime`,
  `$select=id,subject,start,end,location,organizer,attendees,isOnlineMeeting,onlineMeeting,isCancelled,isAllDay,showAs,responseStatus,seriesMasterId,bodyPreview,webLink`,
  `$orderby=start/dateTime`, `$top=50`, and `Prefer: outlook.timezone`.
- **Scopes:** `Calendars.Read`
- **Notes:** `calendarView` expands recurring series into occurrences. Columns: start, end, markers
  (`T` Teams meeting, `X` cancelled), subject, organizer, location, id.

### `calendar calendars`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/calendars?$select=id,name,isDefaultCalendar,canEdit,owner,color`.
- **Scopes:** `Calendars.Read`

### `calendar get ID`

| Option | Default | Meaning |
|---|---|---|
| `--html` | off | Show the HTML body verbatim. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/events/{id}` with `Prefer: outlook.timezone`, and
  `Prefer: outlook.body-content-type="text"` unless `--html`.
- **Scopes:** `Calendars.Read`
- **Notes:** shows every attendee with their response status, and the Teams join URL when there is
  one.

### `calendar create`

| Option | Default | Meaning |
|---|---|---|
| `--subject TEXT` | — | Event title. Required. |
| `--start DT` | — | Start. Required. |
| `--end DT` | `--start` + `--duration` | End. |
| `--duration D` | `30m` | Length, when `--end` is not given. |
| `--all-day` / `--no-all-day` | off | All-day event. |
| `--attendees ADDR` | — | Required attendee. Repeatable. |
| `--optional ADDR` | — | Optional attendee. Repeatable. |
| `--body TEXT` | — | Event body. |
| `--html` | off | The body is HTML. |
| `--location TEXT` | — | Location display name. |
| `--teams` / `--no-teams` | off | Add a Teams online meeting. |
| `--reminder MIN` | — | Minutes before start. |
| `--show-as STATE` | — | `free`, `tentative`, `busy`, `oof`, `workingElsewhere`. |
| `--category X` | — | Category. Repeatable. |
| `--calendar NAME\|ID` | the default calendar | Which calendar to create in. |
| `--transaction-id ID` | a generated uuid4 | Idempotency key. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/events` (or `/me/calendars/{id}/events`) with
  `{subject, start, end, isAllDay, attendees, body, location, isOnlineMeeting,
  onlineMeetingProvider:"teamsForBusiness", reminderMinutesBeforeStart, showAs, categories,
  transactionId}` and `Prefer: outlook.timezone`.
- **Scopes:** `Calendars.ReadWrite`
- **Notes:** write. Returns the event, including `onlineMeeting.joinUrl` with `--teams`. An all-day
  event with no `--end` ends at midnight the next day. Graph sends the invitations.

### `calendar update ID`

Every `calendar create` option except `--calendar` and `--transaction-id`; all optional.

| Option | Default | Meaning |
|---|---|---|
| `--subject` / `--start` / `--end` / `--duration` | — | Change these fields. |
| `--all-day` / `--no-all-day` | — | Change the all-day flag. |
| `--attendees` / `--optional ADDR` | — | Replace the attendee list. Repeatable. |
| `--body TEXT` / `--html` | — | Replace the body. |
| `--teams` / `--no-teams` | — | Add or remove the Teams online meeting. |
| `--location` / `--reminder` / `--show-as` / `--category` | — | Change these fields. |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `PATCH /me/events/{id}` with only the fields given, and `Prefer: outlook.timezone`.
- **Scopes:** `Calendars.ReadWrite`
- **Notes:** write. Graph cannot move an event between calendars, so there is no `--calendar`.
  Updating a series master updates the whole series.

### `calendar delete ID`

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `DELETE /me/events/{id}`.
- **Scopes:** `Calendars.ReadWrite`
- **Notes:** write. When the signed-in user is the organizer, Graph sends cancellations to every
  attendee.

### `calendar respond ID accept|decline|tentative`

| Option | Default | Meaning |
|---|---|---|
| `--comment TEXT` | — | Comment to send with the response. |
| `--send` / `--no-send` | on | Send the response to the organizer. |
| `--propose-start DT` | — | Propose a new start (decline or tentative only). |
| `--propose-end DT` | — | Propose a new end (decline or tentative only). |
| `--dry-run` | off | Show the request(s); send nothing. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/events/{id}/accept` | `/decline` | `/tentativelyAccept` with
  `{comment, sendResponse, proposedNewTime}`.
- **Scopes:** `Calendars.ReadWrite`
- **Notes:** write. JSON `{"status":"accepted"|"declined"|"tentativelyAccepted"}`.

### `calendar availability`

| Option | Default | Meaning |
|---|---|---|
| `--users ADDR` | the signed-in user | Mailbox to check. Repeatable. |
| `--start DT` | now, floored to the interval | Window start. |
| `--end DT` | end of today | Window end. |
| `--interval MIN` | 30 | Minutes per slot (5–1440). |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/calendar/getSchedule {schedules, startTime, endTime,
  availabilityViewInterval}` with `Prefer: outlook.timezone`; with no `--users`, one
  `GET /me?$select=mail,userPrincipalName` first.
- **Scopes:** `Calendars.Read`
- **Notes:** text lists each user's busy, tentative, out-of-office and working-elsewhere blocks,
  and the free windows computed from `availabilityView`.

### `calendar find-times`

| Option | Default | Meaning |
|---|---|---|
| `--attendees ADDR` | — | Attendee. Repeatable. At least one required. |
| `--duration D` | `30m` | Meeting length. |
| `--start DT` | now | Earliest start. |
| `--end DT` | +7d | Latest end. |
| `--max N` | 5 | Maximum candidates. |
| `--domain DOMAIN` | `work` | `work`, `personal` or `unrestricted`. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `POST /me/findMeetingTimes {attendees, timeConstraint:{activityDomain, timeSlots},
  meetingDuration, maxCandidates, returnSuggestionReasons:true}` with `Prefer: outlook.timezone`.
- **Scopes:** `Calendars.Read.Shared`
- **Beyond `default`:** always.
- **Notes:** text shows each suggestion with its confidence and per-attendee availability. When
  Graph returns nothing it surfaces `emptySuggestionsReason`.
