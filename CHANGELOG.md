# Changelog

## [Unreleased]

- Initial Python implementation of the `msgraph` skill as `mgraphctl`: a typer CLI run with `uv`
  (msal sign-in, httpx with retries and paging, offline pytest suite).
- Parity with every `msgraph` mode: mail, calendar, availability, SharePoint (sites, browse,
  download, `url`), OneDrive, Teams chats and channels, hosted content, people, contacts, org
  chart, OneNote, Planner, To Do, meetings and transcripts, AI insights.
- Extensions: mail triage (`mark`, `move`, `delete`, `folders`, drafts, rules, categories),
  mailbox settings and automatic replies, `getSchedule`/`findMeetingTimes`, chats find-or-create
  DM, presence, SharePoint lists and upload, OneDrive item writes and sharing links, unified
  `search`, raw `api`.
- Every write verb supports `--dry-run`; stable exit codes (0/1/2/3/4); data commands never open
  a browser.
