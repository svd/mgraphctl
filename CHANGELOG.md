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

### Fixed

- `chats messages --after` never actually filtered. It sent `$filter=createdDateTime gt …`
  alongside `$orderby=createdDateTime desc`, but Graph supports `gt` on chat messages only for
  `lastModifiedDateTime` and ignores a `$filter` whose property `$orderby` does not name. Both now
  use `lastModifiedDateTime`, so the bounds mean when a message was last touched.
