# Changelog

## [Unreleased]

- Initial Python implementation of the `msgraph` skill as `mgraphctl`: a typer CLI run with `uv`
  (msal sign-in, httpx with retries and paging, offline pytest suite).
- Parity with every `msgraph` mode: mail, calendar, availability, SharePoint (sites, browse,
  download, `url`), OneDrive, Teams chats and channels, hosted content, people, contacts, org
  chart, OneNote, Planner, To Do, meetings and transcripts, AI insights.
- Extensions: mail triage (`mark`, `move`, `delete`, `folders`, drafts, rules, categories),
  mailbox settings and automatic replies, `getSchedule`/`findMeetingTimes`, chats find-or-create
  DM, presence, SharePoint lists and upload, OneDrive item writes and sharing links, Microsoft 365
  groups (`groups list`, `groups members`), unified `search`, raw `api`.
- Every write verb supports `--dry-run`; stable exit codes (0/1/2/3/4); data commands never open
  a browser.
- `mail list` search mode now re-filters the page on `receivedDateTime` when `--after`/`--before`
  carry a time of day, so a bound like `--after 2026-09-02T14:00` no longer returns the whole of
  2026-09-02. Date-only bounds are unaffected.
- `teams channel messages` takes `--after`/`--before`, so a channel hit from `search` or
  `chats search` can be followed up over a time window. The window is applied client-side on the
  reply chain's last-modified time, and paging stops at the first message older than `--after`;
  Graph documents no `$filter` support on that endpoint, and an unsupported one is either rejected
  or silently ignored.
- `chats messages` takes `--before`, symmetric to `--after`.
- `chats list` takes `--since`, stopping the fetch at the first chat whose last message predates
  it. Text mode then shows a `lastMessage` column with the timestamp the bound is measured against.
- Every `--json` listing now carries `fetched` (items Graph returned before any client-side pass),
  `cap` (the bound the fetch ran under) and `query` (the server-side query actually sent), and the
  commands that accept a time window carry `window: {after, before}` — present even when both
  bounds are unset, absent on commands with no date options. `cap`, `fetched` and `truncated`
  describe the fetch, never the filtered list. Text output is unchanged.
- `meetings transcript --speakers` renders the transcript as speaker turns, merging each
  speaker's consecutive cues into one `**Speaker:** …` paragraph.
- `meetings transcript --json` now reports `createdDateTime`, looked up best-effort and left
  `null` when the lookup fails.
- Chat messages carry `chatId`, and channel messages and replies carry `teamId`/`channelId`,
  which Graph omits when they are fetched through their own collection — so a message in JSON can
  be routed back to the thread it came from.
- `chats search` hits carry structured `kind`/`chatId`/`teamId`/`channelId` beside the `where`
  text column, so a hit can be followed into `teams channel messages --after …` without parsing
  `where` apart. A hit with no routing reports `kind: "unknown"`.
- `MGRAPHCTL_RETRIES`, `MGRAPHCTL_TIMEOUT_MS` and `MGRAPHCTL_RETRY_BASE_MS` tune retrying and
  timeouts; `MGRAPHCTL_RETRIES=0` disables retrying outright. An unusable value takes the
  default rather than failing the command. The long timeout for uploads and downloads keeps its
  multiplier off whatever base is configured.

### Fixed

- `fmt_dtz` printed a literal `(None)` beside an unformatted Graph timestamp when the
  `dateTimeTimeZone` object carried no `timeZone`. An absent or empty zone now reads as UTC,
  which is Graph's documented default when no `Prefer: outlook.timezone` was sent — reachable
  through `calendar availability`, search event hits and the mailbox out-of-office block. A
  Windows zone name still renders verbatim.
- `meetings transcript` reported the format that was asked for rather than the one it got. The
  speaker-attribution fallback answers in plain text even to a vtt request, so `--format vtt`
  could label plain text as `vtt`; the format is now sniffed from the body, on the `--output` path
  too. The JSON field `text` is renamed `content`, matching the Node skill.

- `chats messages --after` never actually filtered. It sent `$filter=createdDateTime gt …`
  alongside `$orderby=createdDateTime desc`, but Graph supports `gt` on chat messages only for
  `lastModifiedDateTime` and ignores a `$filter` whose property `$orderby` does not name. Both now
  use `lastModifiedDateTime`, so the bounds mean when a message was last touched.
