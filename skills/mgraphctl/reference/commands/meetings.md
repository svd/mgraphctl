# `meetings`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

All `meetings` verbs except `list` select the meeting three ways: a positional online-meeting id,
`--join-url URL`, or `--event EVENT_ID`. Give exactly one.

### `meetings list`

| Option | Default | Meaning |
|---|---|---|
| `--start DT` | today − 7 days | Start of the window. |
| `--end DT` | end of today | End of the window. |
| `--subject KW` | — | Case-insensitive subject substring. |
| `--resolve` | off | Resolve each event to its online-meeting id. |
| `--with-transcripts` | off | Also list transcript ids (implies `--resolve`). |
| `--limit N` | 50 | Maximum items. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/calendarView?…&$select=id,subject,start,end,organizer,isOnlineMeeting,onlineMeeting&$top=50`
  with `Prefer: outlook.timezone`, keeping events that have a join URL; `--resolve` adds a
  `POST /$batch` of `GET /me/onlineMeetings?$filter=JoinWebUrl eq '{url}'`;
  `--with-transcripts` adds `GET /me/onlineMeetings/{id}/transcripts` per resolved meeting.
- **Scopes:** `Calendars.Read`; `--resolve` additionally checks `OnlineMeetings.Read`, and
  `--with-transcripts` `OnlineMeetingTranscript.Read.All`.
- **Notes:** columns: start, subject, event id, meeting id (when resolved), transcript ids.

### `meetings get [MEETING]`

| Option | Default | Meaning |
|---|---|---|
| `--join-url URL` | — | Select the meeting by its join URL. |
| `--event ID` | — | Select the meeting from a calendar event id. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onlineMeetings/{id}`, or
  `GET /me/onlineMeetings?$filter=JoinWebUrl eq '{url}'`.
- **Scopes:** `OnlineMeetings.Read`

### `meetings transcripts [MEETING]`

| Option | Default | Meaning |
|---|---|---|
| `--join-url URL` | — | Select the meeting by its join URL. |
| `--event ID` | — | Select the meeting from a calendar event id. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onlineMeetings/{id}/transcripts`.
- **Scopes:** `OnlineMeetingTranscript.Read.All`

### `meetings transcript [MEETING] TRANSCRIPT_ID`

| Option | Default | Meaning |
|---|---|---|
| `--join-url URL` | — | Select the meeting by its join URL. |
| `--event ID` | — | Select the meeting from a calendar event id. |
| `--format FMT` | `text` | `text` or `vtt`. |
| `--speakers` | off | Merge each speaker's consecutive cues into one turn. |
| `--output FILE` | — | Write to this file instead of stdout. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onlineMeetings/{m}/transcripts/{t}/content?$format=text/vtt` (streamed). A 403
  `SpeakerAttributionNotAllowed` is retried with
  `Accept: application/vnd.microsoft.graph.transcript+text`. With `--json`, one extra
  `GET /me/onlineMeetings/{m}/transcripts` supplies `createdDateTime`.
- **Scopes:** `OnlineMeetingTranscript.Read.All`
- **Notes:** with `--join-url` or `--event` the single positional argument is the transcript id;
  otherwise give the meeting id and then the transcript id. `text` converts the VTT locally into
  `[HH:MM:SS] Speaker: line`, one line per cue.
  JSON is `{"meetingId","transcriptId","createdDateTime","format","content"}`.
  `format` is **sniffed from the body**, not taken from `--format`: the speaker-attribution
  fallback answers in plain text even to a vtt request, and some meeting types answer in vtt to a
  text one, so the field says what the content actually is. `--output` reports the same sniffed
  value. `createdDateTime` costs one extra listing request, so only `--json` pays it, and a failed
  lookup leaves the field `null` rather than failing the command — the content is already in hand.
  `--speakers` renders `**Speaker:** text` turns, merging a speaker's consecutive cues into one
  and separating turns with a blank line, which is what makes a transcript readable; a cue with no
  `<v>` tag continues the turn it falls inside. It respects `--output`, and combined with
  `--format vtt` is a usage error rather than a silent override.

### `meetings insights [MEETING]`

| Option | Default | Meaning |
|---|---|---|
| `--join-url URL` | — | Select the meeting by its join URL. |
| `--event ID` | — | Select the meeting from a calendar event id. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /copilot/users/{oid}/onlineMeetings/{m}/aiInsights` on `/v1.0`, falling back to
  the same path on `/beta` on a 404; then `GET …/aiInsights/{id}` per item.
- **Scopes:** `OnlineMeetingAiInsight.Read.All`
- **Notes:** needs a Microsoft 365 Copilot licence. A 403 prints
  `AI insights require a Microsoft 365 Copilot license…` and **exits 0**; an empty or missing recap
  is likewise a soft message with exit 0 and a `note` in the JSON. Insights can take up to a few
  hours after a meeting ends to appear.

### `meetings recordings [MEETING]`

| Option | Default | Meaning |
|---|---|---|
| `--join-url URL` | — | Select the meeting by its join URL. |
| `--event ID` | — | Select the meeting from a calendar event id. |
| `--download RID` | — | Recording id to download. |
| `--output FILE` | — | File to write the recording to. |
| `--json` | off | Print JSON instead of text. |

- **Graph:** `GET /me/onlineMeetings/{id}/recordings`; `--download`:
  `GET …/recordings/{rid}/content` (streamed).
- **Scopes:** `OnlineMeetingRecording.Read.All` (*on-demand*)
- **Beyond `default`:** always.
- **Notes:** the missing-scope hint names `login --scope OnlineMeetingRecording.Read.All`.
