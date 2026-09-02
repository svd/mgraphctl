# Microsoft Graph Python CLI: API surface and implementation-stack research

Date: 2026-09-02. Companion document: `2026-09-02-msgraph-node-feature-inventory.md`
(what the current Node.js CLI does). This document answers two questions:

- **Part A**: what can a *delegated* (signed-in user) Graph v1.0 client do, per area, with
  which scopes, and where are the traps?
- **Part B**: which Python stack should the CLI use, how should it authenticate, and how
  should it be packaged so `uv` on a fresh machine is the only prerequisite?

Every claim carries a source URL; Microsoft Learn pages were read on 2026-09-02. Package
versions are PyPI "latest" on that date.

---

## Part A: Graph v1.0 delegated capability surface

### A.0 Conventions used below

- Base URL `https://graph.microsoft.com/v1.0`; `beta` only where flagged.
- "Least" = least-privileged delegated scope Microsoft lists for the call. "Admin" = the
  permissions reference marks the delegated permission as *admin consent required by default*.
  Separately, section A.15 lists scopes that the **Microsoft-managed default consent policy**
  now blocks end users from consenting to (a 2025 change that matters more in practice).
- Paging: every collection returns `@odata.nextLink`; replay it verbatim, never parse `$skip`
  (Outlook's `$skip` is an internal cursor, not an offset).
  [user-list-messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0)

### A.1 Mail

| Operation | Method + path | Least scope | Notes |
|---|---|---|---|
| List messages | `GET /me/messages`, `GET /me/mailFolders/{id\|wellKnown}/messages` | `Mail.ReadBasic` (no body/attachments), `Mail.Read` | Default page 10, `$top` 1..1000; large `$top` without `$select` risks HTTP 504. Body always HTML unless `Prefer` header (below). |
| Get message | `GET /me/messages/{id}` | `Mail.ReadBasic` / `Mail.Read` | `?$select=internetMessageHeaders` for headers; `GET .../{id}/$value` returns MIME. |
| Text body | header `Prefer: outlook.body-content-type="text"` | – | Applies to `body` and `uniqueBody`; server echoes `Preference-Applied`. Cheapest HTML→text path; no client-side library needed for mail. |
| Search | `GET /me/messages?$search="<KQL>"` | `Mail.Read` | KQL properties: `from`, `to`, `cc`, `bcc`, `participants`, `recipients`, `subject`, `body`, `attachment`, `hasAttachments`, `importance`, `kind`, `received`, `sent`, `size`. Without a property, searches `from`/`subject`/`body`. Max 1,000 results, sorted by sent date. |
| Filter | `GET /me/messages?$filter=...&$orderby=...` | `Mail.Read` | Rule: every `$orderby` property must appear first, in the same order, in `$filter`, else `InefficientFilter`. Typical: `receivedDateTime ge 2026-08-01T00:00:00Z and isRead eq false`, `from/emailAddress/address eq '...'`, `hasAttachments eq true`, `inferenceClassification eq 'focused'`. |
| Folders | `GET /me/mailFolders`, `.../{id}/childFolders`, `?includeHiddenFolders=true` | `Mail.ReadBasic` | Only root-level children returned; traverse `childFolders` for depth. Well-known names usable in paths and `destinationId`: `inbox`, `drafts`, `sentitems`, `deleteditems`, `junkemail`, `archive`, `outbox`, `clutter`, `conversationhistory`, `searchfolders`, `msgfolderroot`. Returns `unreadItemCount`/`totalItemCount`; page size 10 by default. |
| Attachments list | `GET /me/messages/{id}/attachments?$select=id,name,contentType,size,isInline` | `Mail.Read` | Omit `contentBytes` from `$select` or every attachment is base64-inlined. |
| Attachment download | `GET /me/messages/{id}/attachments/{aid}` (`contentBytes` base64) or `.../attachments/{aid}/$value` (raw bytes) | `Mail.Read` | `$value` works for `fileAttachment`; `itemAttachment` (embedded mail) needs `$expand=microsoft.graph.itemattachment/item`. |
| Attachment upload (<3 MB) | `POST /me/messages/{id}/attachments` `{ "@odata.type":"#microsoft.graph.fileAttachment", name, contentType, contentBytes }` | `Mail.ReadWrite` | Draft first, attach, then send. |
| Attachment upload (3–150 MB) | `POST /me/messages/{id}/attachments/createUploadSession` `{AttachmentItem:{attachmentType:"file", name, size}}` then `PUT {uploadUrl}` with `Content-Range: bytes s-e/total`, chunks ≤4 MB, **no Authorization header** (URL is pre-authenticated, host `outlook.office.com`) | `Mail.ReadWrite` | Final PUT returns 201 + `Location` with attachment id. Session below 3 MB errors `ErrorAttachmentSizeShouldNotBeLessThanMinimumSize`. |
| Send (one shot) | `POST /me/sendMail` `{message:{subject, body:{contentType:"Text"\|"HTML", content}, toRecipients:[{emailAddress:{address}}], ccRecipients, bccRecipients, attachments:[fileAttachment...], internetMessageHeaders:[{name:"x-…",value}], flag, importance}, saveToSentItems}` | `Mail.Send` | 202 Accepted, no body. MIME alternative: `Content-Type: text/plain` + base64 MIME. Whole request must stay under Graph's ~4 MB payload cap, so large attachments go through the draft + upload-session route. |
| Drafts | `POST /me/messages` (create), `PATCH /me/messages/{id}` (edit), `POST /me/messages/{id}/send` | `Mail.ReadWrite` + `Mail.Send` | Draft flow is the only way to attach >3 MB files or to inspect before sending. |
| Reply / reply-all / forward | `POST /me/messages/{id}/reply` \| `/replyAll` \| `/forward` with `{comment}` **or** `{message:{...}}` (both → 400); `forward` needs `toRecipients` | `Mail.Send` | Reply honours `replyTo`. `Prefer: outlook.timezone` sets the "Sent" line timezone in the quoted header. `createReply` / `createReplyAll` / `createForward` return editable drafts (`Mail.ReadWrite`). |
| Move / copy | `POST /me/messages/{id}/move` \| `/copy` `{destinationId}` | `Mail.ReadWrite` | 201 with the **new** message (id changes after move unless immutable ids are on). |
| Delete | `DELETE /me/messages/{id}` | `Mail.ReadWrite` | Soft-delete to Deleted Items (unless already there). |
| Read / flag / categories / importance | `PATCH /me/messages/{id}` `{isRead, flag:{flagStatus:"flagged"\|"complete"\|"notFlagged", dueDateTime}, categories:[..], importance, inferenceClassification}` | `Mail.ReadWrite` | Categories must match master category display names. |
| Master categories | `GET/POST /me/outlook/masterCategories` `{displayName, color:"preset0".."preset24"}` | `MailboxSettings.Read` / `.ReadWrite` | – |
| Mail rules | `GET/POST /me/mailFolders/inbox/messageRules`, `PATCH/DELETE .../messageRules/{id}` | `MailboxSettings.ReadWrite` | Fields: `displayName`, `sequence`, `isEnabled`, `conditions`/`exceptions` (messageRulePredicates), `actions` (moveToFolder, markAsRead, forwardTo, delete, assignCategories, stopProcessingRules...). `isReadOnly` rules can't be edited via API. |
| Mailbox settings / OOF | `GET/PATCH /me/mailboxSettings` and sub-paths `/automaticRepliesSetting`, `/timeZone`, `/workingHours`, `/language`, `/dateFormat`, `/timeFormat`, `/userPurpose` | `MailboxSettings.Read` / `.ReadWrite` | `automaticRepliesSetting: {status:"disabled"\|"alwaysEnabled"\|"scheduled", externalAudience:"none"\|"contactsOnly"\|"all", scheduledStartDateTime/EndDateTime:{dateTime,timeZone}, internalReplyMessage, externalReplyMessage}` (HTML). `timeZone` comes back in Windows or IANA form depending on what was last written; write it in IANA form once to normalise. |
| Focused inbox | `inferenceClassification` property on message; overrides at `GET/POST/PATCH/DELETE /me/inferenceClassification/overrides` `{classifyAs:"focused"\|"other", senderEmailAddress:{address}}` | `Mail.ReadWrite` | Overrides affect future mail only. |
| Immutable ids | header `Prefer: IdType="ImmutableId"` on every request | – | Message ids otherwise change on move; needed if the CLI caches ids across calls. [outlook-immutable-id](https://learn.microsoft.com/en-us/graph/outlook-immutable-id) |
| Delta | `GET /me/mailFolders/{id}/messages/delta` (+`Prefer: odata.maxpagesize=N`, optional `?changeType=created`, `$select`, `$filter=receivedDateTime ge …` (≤5,000 results), `$orderby=receivedDateTime desc` only) | `Mail.Read` | Per-folder only. `@removed` entries for deletions. Token lifetime not fixed (cache-bound); on `syncStateNotFound`/410 restart. |
| Beta only | `GET /me/messages?$filter=mentionsPreview/isMentioned eq true`, `$expand=mentions` | – | @-mention support is beta. |

Sources: [user-list-messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0), [message-get](https://learn.microsoft.com/en-us/graph/api/message-get?view=graph-rest-1.0), [$search](https://learn.microsoft.com/en-us/graph/search-query-parameter), [outlook-large-attachments](https://learn.microsoft.com/en-us/graph/outlook-large-attachments), [user-sendmail](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0), [message-reply](https://learn.microsoft.com/en-us/graph/api/message-reply?view=graph-rest-1.0), [message-move](https://learn.microsoft.com/en-us/graph/api/message-move?view=graph-rest-1.0), [user-list-mailfolders](https://learn.microsoft.com/en-us/graph/api/user-list-mailfolders?view=graph-rest-1.0), [masterCategories](https://learn.microsoft.com/en-us/graph/api/outlookuser-list-mastercategories?view=graph-rest-1.0), [messageRule](https://learn.microsoft.com/en-us/graph/api/resources/messagerule?view=graph-rest-1.0), [mailboxSettings](https://learn.microsoft.com/en-us/graph/api/user-get-mailboxsettings?view=graph-rest-1.0), [focused inbox](https://learn.microsoft.com/en-us/graph/api/resources/manage-focused-inbox?view=graph-rest-1.0), [delta-query-messages](https://learn.microsoft.com/en-us/graph/delta-query-messages), [beta list messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-beta).

### A.2 Calendar

| Operation | Method + path | Least scope | Notes |
|---|---|---|---|
| List calendars | `GET /me/calendars`, `GET /me/calendarGroups/{id}/calendars` | `Calendars.ReadBasic` | Properties: `name`, `isDefaultCalendar`, `canEdit`, `canShare`, `owner`, `color`/`hexColor`, `isRemovable`, `allowedOnlineMeetingProviders`, `defaultOnlineMeetingProvider`. |
| Calendar view (expanded occurrences) | `GET /me/calendar/calendarView?startDateTime=…&endDateTime=…` (also `/me/calendars/{id}/calendarView`) | `Calendars.ReadBasic` (`Calendars.Read` for body/attendees) | Both params required, ISO 8601; offset in the value wins, no offset = UTC; **not** affected by `Prefer: outlook.timezone`. `$top` 1..1000. `createdDateTime`/`lastModifiedDateTime` cannot be `$select`ed here. Recurring series are expanded into occurrences (`seriesMasterId` links back). |
| List events (masters + singles, no occurrences) | `GET /me/events`, `GET /me/events/{id}/instances?startDateTime&endDateTime` | `Calendars.ReadBasic` | Cannot `$filter` on `recurrence`. Body HTML unless `Prefer: outlook.body-content-type="text"`. |
| Timezone of output | header `Prefer: outlook.timezone="Europe/Warsaw"` (Windows names also accepted) | – | Default UTC. `originalStartTimeZone` tells you the creation zone. |
| Create event | `POST /me/events` (or `/me/calendars/{id}/events`) `{subject, body:{contentType,content}, start:{dateTime,timeZone}, end:{…}, location:{displayName}, attendees:[{emailAddress:{address,name}, type:"required"\|"optional"\|"resource"}], isOnlineMeeting:true, onlineMeetingProvider:"teamsForBusiness", allowNewTimeProposals, hideAttendees, responseRequested, reminderMinutesBeforeStart, showAs, sensitivity, categories, transactionId, recurrence:{pattern:{type:"daily"\|"weekly"\|"absoluteMonthly"\|"relativeMonthly"\|"absoluteYearly"\|"relativeYearly", interval, daysOfWeek, firstDayOfWeek, dayOfMonth, index, month}, range:{type:"endDate"\|"noEnd"\|"numbered", startDate, endDate, numberOfOccurrences, recurrenceTimeZone}}}` | `Calendars.ReadWrite` | `transactionId` (client GUID) makes retries idempotent. Response contains `onlineMeeting.joinUrl` and `webLink`. Attendees receive invitations on create. |
| Update / delete / cancel | `PATCH /me/events/{id}`, `DELETE /me/events/{id}`, `POST /me/events/{id}/cancel {comment}` (organizer), `POST /me/events/{id}/forward {toRecipients, comment}` | `Calendars.ReadWrite` | Updating a master updates the series; use instance id from calendarView/instances for one occurrence. |
| Respond | `POST /me/events/{id}/accept` \| `/decline` \| `/tentativelyAccept` `{comment, sendResponse:true, proposedNewTime:{start,end}}` (proposedNewTime only for decline/tentative) | `Calendars.ReadWrite` | Attendee-only; 202. |
| Find meeting times | `POST /me/findMeetingTimes {attendees:[{type:"required", emailAddress}], timeConstraint:{activityDomain:"work"\|"personal"\|"unrestricted", timeSlots:[{start:{dateTime,timeZone}, end}]}, meetingDuration:"PT1H", maxCandidates, minimumAttendeePercentage, isOrganizerOptional, locationConstraint, returnSuggestionReasons}` | **`Calendars.Read.Shared`** (not plain `Calendars.Read`) | Work/school only; response `meetingTimeSuggestions[]` with `confidence`, `attendeeAvailability`, `emptySuggestionsReason`. Use `Prefer: outlook.timezone`. |
| Free/busy | `POST /me/calendar/getSchedule {schedules:["a@x.com", "room@x.com"], startTime:{dateTime,timeZone}, endTime, availabilityViewInterval:30}` | `Calendars.ReadBasic` | `availabilityView` string per schedule: `0` free, `1` tentative, `2` busy, `3` OOF, `4` working elsewhere; `scheduleItems` and `workingHours` included. Interval 5..1440 min. Error 5006 if a slot has >1000 entries. Not for personal accounts. |
| Rooms | `GET /places/microsoft.graph.room`, `GET /places/microsoft.graph.roomList`, `GET /places/{roomlist-email}/microsoft.graph.roomlist/rooms` (also `building`, `floor`, `desk`, `workspace`) | `Place.Read.All` (**admin**) | Places must be configured by the tenant; many tenants have none. |
| Online meeting (standalone) | `POST /me/onlineMeetings {startDateTime, endDateTime, subject, participants}`; `POST /me/onlineMeetings/createOrGet {externalId, …}` | `OnlineMeetings.ReadWrite` | Not shown on the calendar and **transcripts are not retrievable** for such meetings; for productivity use, create an event with `isOnlineMeeting:true` instead. `GET /me/onlineMeetings?$filter=JoinWebUrl eq '{joinUrl}'` resolves an event's Teams link to the meeting id (`OnlineMeetings.Read`). |
| Delta | `GET /me/calendarView/delta?startDateTime&endDateTime` | `Calendars.Read` | Range-scoped; tokens tied to the range. |

Sources: [user-list-calendars](https://learn.microsoft.com/en-us/graph/api/user-list-calendars?view=graph-rest-1.0), [calendar-list-calendarview](https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview?view=graph-rest-1.0), [user-list-events](https://learn.microsoft.com/en-us/graph/api/user-list-events?view=graph-rest-1.0), [user-post-events](https://learn.microsoft.com/en-us/graph/api/user-post-events?view=graph-rest-1.0), [event-accept](https://learn.microsoft.com/en-us/graph/api/event-accept?view=graph-rest-1.0), [user-findmeetingtimes](https://learn.microsoft.com/en-us/graph/api/user-findmeetingtimes?view=graph-rest-1.0), [calendar-getschedule](https://learn.microsoft.com/en-us/graph/api/calendar-getschedule?view=graph-rest-1.0), [place-list](https://learn.microsoft.com/en-us/graph/api/place-list?view=graph-rest-1.0), [application-post-onlinemeetings](https://learn.microsoft.com/en-us/graph/api/application-post-onlinemeetings?view=graph-rest-1.0).

### A.3 Contacts, People, Users, org chart, photos

| Operation | Method + path | Least scope | Notes |
|---|---|---|---|
| Personal contacts | `GET/POST /me/contacts`, `GET/PATCH/DELETE /me/contacts/{id}`, `GET /me/contactFolders/{id}/contacts` | `Contacts.Read` / `Contacts.ReadWrite` | `$filter` only supports `emailAddresses/any(a:a/address eq 'x')`; no `$search`. Contact photo `GET /me/contacts/{id}/photo/$value`. Delta supported. |
| Relevant people (fuzzy) | `GET /me/people?$search="jo"` (also `$search="topic:budget"`), `$filter=personType/class eq 'Person'` | `People.Read` | Ranked by relevance; up to 250; **maintenance mode**, Microsoft now recommends Search API `person` entity. |
| People via Search API | `POST /search/query {requests:[{entityTypes:["person"], query:{queryString:"jo"}, from:0, size:25, fields:[…], filter:{…PeopleType/PeopleSubtype…}}]}` | `People.Read` | Returns org users, contacts, groups, rooms, guests from mailbox + directory; `size` default 25. |
| Directory user search | `GET /users?$filter=startswith(displayName,'Jo')&$select=id,displayName,mail,userPrincipalName,jobTitle,department,officeLocation,mobilePhone,businessPhones` | `User.ReadBasic.All` (**no** admin consent) | Default page 100, max 999, `$skip` unsupported. `$search="displayName:jo"`, `endsWith`, `ne`/`not`, `$orderby`+`$filter`, `$count` need `ConsistencyLevel: eventual` + `$count=true` (advanced queries; index lag possible). |
| Get user | `GET /users/{id\|upn}?$select=…` | `User.ReadBasic.All` | Non-default properties (`aboutMe`, `skills`, `birthday`…) need explicit `$select`. |
| Manager / reports | `GET /me/manager`, `GET /me/directReports`, `GET /me?$expand=manager($levels=max;$select=id,displayName)` (needs `ConsistencyLevel: eventual`) | `User.Read.All` (**admin**) | 404 when no manager assigned. |
| Photo | `GET /me/photo/$value`, `GET /me/photos/{48x48\|64x64\|96x96\|120x120\|240x240\|360x360\|432x432\|504x504\|648x648}/$value`, `GET /users/{id}/photo/$value`, `PUT /me/photo/$value` (image/jpeg) | own: `User.Read`; others: `ProfilePhoto.Read.All` or `User.ReadBasic.All` | 404 when no photo; metadata `GET /me/photo` returns `1x1` placeholder when none. |

Sources: [user-list-contacts](https://learn.microsoft.com/en-us/graph/api/user-list-contacts?view=graph-rest-1.0), [user-list-people](https://learn.microsoft.com/en-us/graph/api/user-list-people?view=graph-rest-1.0), [search-concept-person](https://learn.microsoft.com/en-us/graph/search-concept-person), [user-list](https://learn.microsoft.com/en-us/graph/api/user-list?view=graph-rest-1.0), [user-list-manager](https://learn.microsoft.com/en-us/graph/api/user-list-manager?view=graph-rest-1.0), [profilephoto-get](https://learn.microsoft.com/en-us/graph/api/profilephoto-get?view=graph-rest-1.0), [aad-advanced-queries](https://learn.microsoft.com/en-us/graph/aad-advanced-queries).

### A.4 Teams

| Operation | Method + path | Least scope | Notes |
|---|---|---|---|
| My teams | `GET /me/joinedTeams` | `Team.ReadBasic.All` | No OData params; only `id`, `displayName`, `description`, `isArchived`, `tenantId` populated. Shared-channel host teams need `GET /me/teamwork/associatedTeams`. |
| Channels | `GET /teams/{id}/channels`, `GET /teams/{id}/channels/{id}` | `Channel.ReadBasic.All` | – |
| Team members | `GET /teams/{id}/members` | `TeamMember.Read.All` | – |
| Channel messages | `GET /teams/{id}/channels/{id}/messages?$top=50&$expand=replies` | `ChannelMessage.Read.All` (**admin**) | Default 20, max 50 per page; only `$top`/`$expand` supported (no `$filter`/`$orderby`); ordered by last-modified of the reply chain; replies also at `.../messages/{id}/replies`. `Prefer: include-unknown-enum-members` exposes `systemEventMessage` types. Delta: `.../messages/delta`. |
| Post to channel / reply | `POST /teams/{id}/channels/{id}/messages`, `POST .../messages/{id}/replies` `{subject?, importance?, body:{contentType:"html", content:"Hi <at id=\"0\">Jane</at>"}, mentions:[{id:0, mentionText:"Jane", mentioned:{user:{id, displayName, userIdentityType:"aadUser"}}}], attachments:[{id, contentType:"reference", contentUrl, name}], hostedContents:[{"@microsoft.graph.temporaryId":"1", contentBytes, contentType:"image/png"}]}` | `ChannelMessage.Send` | 201 with the message. Teams renders a restricted HTML subset. |
| My chats | `GET /me/chats?$expand=lastMessagePreview&$orderby=lastMessagePreview/createdDateTime desc&$top=50` | `Chat.ReadBasic` (list) / `Chat.Read` | `$top` max 50; `$expand=members` caps at 25 members; `chatType` `oneOnOne`/`group`/`meeting`; unread detection = compare `lastMessagePreview.createdDateTime` with `viewpoint.lastMessageReadDateTime`. |
| Chat messages | `GET /chats/{id}/messages?$top=50&$orderby=createdDateTime desc` | `Chat.Read` | `$top` max 50; `$orderby` desc only (`lastModifiedDateTime` default or `createdDateTime`); `$filter` on the same date property as `$orderby` only. Inline images are `hostedContents/{id}/$value` URLs that need the token to fetch. |
| Send chat message | `POST /chats/{id}/messages {body:{content}}` | `ChatMessage.Send` | Cannot create a chat. |
| Start 1:1 / group chat | `POST /chats {chatType:"oneOnOne", members:[{"@odata.type":"#microsoft.graph.aadUserConversationMember", roles:["owner"], "user@odata.bind":"https://graph.microsoft.com/v1.0/users('{id}')"}, …]}` | `Chat.Create` | Returns the existing chat if a 1:1 already exists. |
| Presence (mine / others) | `GET /me/presence`, `GET /users/{id}/presence`, `POST /communications/getPresencesByUserId {ids:[…]}` | `Presence.Read` (self) / `Presence.Read.All` (**admin**) | Fields `availability`, `activity`, `statusMessage`, `outOfOfficeSettings`. Rate limit 1,500 req/30 s per app per tenant. |
| Set my presence | `POST /users/{my-id}/presence/setUserPreferredPresence {availability, activity, expirationDuration:"PT8H"}` (pairs: Available/Available, Busy/Busy, DoNotDisturb/DoNotDisturb, BeRightBack/BeRightBack, Away/Away, Offline/OffWork); `POST .../presence/setStatusMessage` | `Presence.ReadWrite` | Takes effect only while a Teams client session exists; default expiry 1 day (Busy/DND) or 7 days. |
| Meeting transcripts | `GET /me/onlineMeetings/{id}/transcripts`, `GET .../transcripts/{tid}/content?$format=text/vtt` (default, speaker-attributed) or `Accept: application/vnd.microsoft.graph.transcript+text` (unattributed fallback) | `OnlineMeetingTranscript.Read.All` (**admin**) | Only for calendar-backed meetings that haven't expired; 403 `GraphAccessToTranscriptsDisabled` if the tenant turned Graph transcript access off; 403 `SpeakerAttributionNotAllowed` → retry unattributed. Resolve the meeting id from the event's `onlineMeeting.joinUrl` via `GET /me/onlineMeetings?$filter=JoinWebUrl eq '…'`. Ad-hoc calls: `/me/adhocCalls/{id}/transcripts` (`CallTranscripts.Read.All`). |
| Recordings | `GET /me/onlineMeetings/{id}/recordings`, `.../recordings/{id}/content` | `OnlineMeetingRecording.Read.All` (**admin**) | Same tenant gating. |
| AI meeting insights | `GET /me/onlineMeetings/{id}/aiInsights` (**beta**) | `OnlineMeetingAiInsight.Read.All` | Beta only (the current Node CLI uses it). Requires Copilot licensing. |

Sources: [user-list-joinedteams](https://learn.microsoft.com/en-us/graph/api/user-list-joinedteams?view=graph-rest-1.0), [channel-list-messages](https://learn.microsoft.com/en-us/graph/api/channel-list-messages?view=graph-rest-1.0), [chatmessage-post](https://learn.microsoft.com/en-us/graph/api/chatmessage-post?view=graph-rest-1.0), [chat-list](https://learn.microsoft.com/en-us/graph/api/chat-list?view=graph-rest-1.0), [chat-list-messages](https://learn.microsoft.com/en-us/graph/api/chat-list-messages?view=graph-rest-1.0), [chat-post-messages](https://learn.microsoft.com/en-us/graph/api/chat-post-messages?view=graph-rest-1.0), [chat-post](https://learn.microsoft.com/en-us/graph/api/chat-post?view=graph-rest-1.0), [presence-get](https://learn.microsoft.com/en-us/graph/api/presence-get?view=graph-rest-1.0), [presence-setuserpreferredpresence](https://learn.microsoft.com/en-us/graph/api/presence-setuserpreferredpresence?view=graph-rest-1.0), [onlinemeeting-list-transcripts](https://learn.microsoft.com/en-us/graph/api/onlinemeeting-list-transcripts?view=graph-rest-1.0), [calltranscript-get](https://learn.microsoft.com/en-us/graph/api/calltranscript-get?view=graph-rest-1.0).

### A.5 Files: OneDrive and SharePoint

| Operation | Method + path | Least scope | Notes |
|---|---|---|---|
| My drive / browse | `GET /me/drive`, `GET /me/drive/root/children`, `GET /me/drive/root:/{path}:/children`, `GET /me/drive/items/{id}/children` | `Files.Read` | `$select`, `$top`, `$orderby=name`, `$expand=thumbnails`. |
| Search | `GET /me/drive/root/search(q='x')` (my drive) vs `GET /me/drive/search(q='x')` (adds items shared with me; those carry a `remoteItem` facet) | `Files.Read` | Matches name, metadata and content; `$top`/`$skipToken`. |
| Download | `GET /me/drive/items/{id}/content` → 302 to a pre-authenticated URL (do **not** send the bearer to it); or read `@microsoft.graph.downloadUrl` from item metadata (short-lived). Path form `GET /me/drive/root:/{path}:/content`. `?format=pdf` converts Office docs. | `Files.Read` | Stream to disk. |
| Simple upload (≤250 MB per docs; use session above ~4 MB in practice) | `PUT /me/drive/root:/{path}:/content` or `PUT /me/drive/items/{parent}:/{name}:/content` (+`?@microsoft.graph.conflictBehavior=rename\|replace\|fail`) | `Files.ReadWrite` | 201/200 with driveItem. |
| Resumable upload | `POST /me/drive/items/{parent}:/{name}:/createUploadSession {item:{"@microsoft.graph.conflictBehavior":"rename", name}, deferCommit?}` → `PUT {uploadUrl}` chunks: multiples of **320 KiB**, each < 60 MiB, sequential, `Content-Range: bytes s-e/total`, **no Authorization header**; 202 + `nextExpectedRanges` until final 201/200 driveItem; `GET {uploadUrl}` to resume, `DELETE` to cancel | `Files.ReadWrite` | Recommended 5–10 MiB chunks; retry 5xx with backoff; 404 = session gone, restart. |
| Create folder | `POST /me/drive/items/{parent}/children {name, folder:{}, "@microsoft.graph.conflictBehavior":"rename"}` | `Files.ReadWrite` | – |
| Rename / move / copy / delete | `PATCH /me/drive/items/{id} {name, parentReference:{id}}`; `POST .../copy {parentReference, name}` (202 + monitor URL); `DELETE .../items/{id}` (recycle bin) | `Files.ReadWrite` | – |
| Share link | `POST /me/drive/items/{id}/createLink {type:"view"\|"edit"\|"embed", scope:"anonymous"\|"organization"\|"users", expirationDateTime, retainInheritedPermissions}` → `link.webUrl` | `Files.ReadWrite` | 201 new / 200 existing; anonymous links are often disabled by policy; `embed` is consumer-only. Invite people: `POST .../invite {recipients:[{email}], roles:["read"\|"write"], requireSignIn, sendInvitation, message}`. List `GET .../permissions`. |
| Resolve a sharing URL | `GET /shares/u!{base64url(url)}/driveItem` | `Files.Read` (+ access) | The clean way to turn a pasted SharePoint/OneDrive link into an item. [shares-get](https://learn.microsoft.com/en-us/graph/api/shares-get?view=graph-rest-1.0) |
| Shared with me | `GET /me/drive/sharedWithMe` (`?allowexternal=true`) | `Files.Read.All` (**admin**) | **Deprecated: degraded until Nov 2026, then returns nothing.** Items are `remoteItem`s addressable at `/drives/{remoteItem.parentReference.driveId}/items/{remoteItem.id}`. Prefer Search API `driveItem` or `/me/drive/search`. |
| Recent / followed | `GET /me/drive/recent`, `GET /me/drive/following` | `Files.Read` | Recent items across drives the user touched. |
| SharePoint sites | `GET /sites?search=x`, `GET /sites/{hostname}:/sites/{name}`, `GET /sites/root`, `GET /me/followedSites`, `GET /sites/{id}/drives`, `GET /sites/{id}/drive/root/children` | `Sites.Read.All` (**admin**) | Site id is composite `hostname,siteCollectionId,siteId`. Document library names are localised; match on drive `webUrl`. |
| Lists | `GET /sites/{id}/lists` (system lists hidden unless `$select=system,…`), `GET /sites/{id}/lists/{id}/items?expand=fields(select=Title,Status)`, `$filter=fields/Status eq 'Open'` (indexed columns; otherwise header `Prefer: HonorNonIndexedQueriesWarningMayFailRandomly`), `POST .../items {fields:{…}}`, `PATCH .../items/{id}/fields` | `Sites.Read.All` / `Sites.ReadWrite.All` (**admin**) | One indexed field per filter. |
| Delta | `GET /me/drive/root/delta` (`?token=latest` to start from now) | `Files.Read` | – |

Sources: [driveitem-search](https://learn.microsoft.com/en-us/graph/api/driveitem-search?view=graph-rest-1.0), [driveitem-put-content](https://learn.microsoft.com/en-us/graph/api/driveitem-put-content?view=graph-rest-1.0), [driveitem-createuploadsession](https://learn.microsoft.com/en-us/graph/api/driveitem-createuploadsession?view=graph-rest-1.0), [driveitem-createlink](https://learn.microsoft.com/en-us/graph/api/driveitem-createlink?view=graph-rest-1.0), [drive-sharedwithme](https://learn.microsoft.com/en-us/graph/api/drive-sharedwithme?view=graph-rest-1.0), [site-search](https://learn.microsoft.com/en-us/graph/api/site-search?view=graph-rest-1.0), [listitem-list](https://learn.microsoft.com/en-us/graph/api/listitem-list?view=graph-rest-1.0).

### A.6 To Do

| Operation | Method + path | Least scope | Notes |
|---|---|---|---|
| Lists | `GET/POST /me/todo/lists {displayName}`, `PATCH/DELETE /me/todo/lists/{id}` | `Tasks.Read` / `Tasks.ReadWrite` | `wellknownListName`: `defaultList`, `flaggedEmails` (mirror of flagged mail), `none`. Delta supported. |
| Tasks | `GET /me/todo/lists/{id}/tasks` (`$filter=status ne 'completed'`, `$orderby`, `$top`), `POST`, `PATCH /tasks/{id}`, `DELETE` | `Tasks.ReadWrite` | Fields: `title`, `body:{content,contentType}`, `importance:low\|normal\|high`, `status:notStarted\|inProgress\|completed\|waitingOnOthers\|deferred`, `dueDateTime:{dateTime,timeZone}`, `startDateTime`, `reminderDateTime` + `isReminderOn`, `recurrence` (patternedRecurrence), `categories`, `completedDateTime`, `linkedResources:[{webUrl, applicationName, displayName, externalId}]`. Personal accounts supported. Delta supported. |
| Checklist items | `GET/POST /me/todo/lists/{l}/tasks/{t}/checklistItems {displayName, isChecked}`, `PATCH/DELETE .../checklistItems/{id}` | `Tasks.ReadWrite` | – |
| Linked resources | `GET/POST .../tasks/{t}/linkedResources` | `Tasks.ReadWrite` | Use to link a task back to a mail `webLink`. |
| Attachments | `GET/POST .../tasks/{t}/attachments` (+ `createUploadSession` for >3 MB) | `Tasks.ReadWrite` | – |

Sources: [todo-overview](https://learn.microsoft.com/en-us/graph/api/resources/todo-overview?view=graph-rest-1.0), [todotasklist-post-tasks](https://learn.microsoft.com/en-us/graph/api/todotasklist-post-tasks?view=graph-rest-1.0).

### A.7 Planner

| Operation | Method + path | Least scope | Notes |
|---|---|---|---|
| My tasks | `GET /me/planner/tasks` | `Tasks.Read` | Tasks assigned to me across plans; returns `planId`, `bucketId`, `percentComplete` (0/50/100), `priority` (0-10), `dueDateTime`, `assignments{userId:{orderHint}}`, `@odata.etag`. Work/school only. |
| Plans | `GET /groups/{id}/planner/plans`, `GET /planner/plans/{id}`, `GET /planner/plans/{id}/details`, `GET /me/planner/plans` (plans shared with me; verify availability in your tenant) | `Tasks.Read` or `Group.Read.All` | Plans live in Microsoft 365 groups; enumerate via `/me/memberOf/microsoft.graph.group?$filter=groupTypes/any(c:c eq 'Unified')`. **Premium plans are not exposed.** |
| Buckets | `GET /planner/plans/{id}/buckets`, `GET /planner/buckets/{id}/tasks`, `POST /planner/buckets {name, planId, orderHint:" !"}` | `Tasks.ReadWrite` | – |
| Task CRUD | `POST /planner/tasks {planId, bucketId, title, assignments:{"{userId}":{"@odata.type":"#microsoft.graph.plannerAssignment", orderHint:" !"}}, dueDateTime, startDateTime, priority, percentComplete}`; `PATCH /planner/tasks/{id}` and `DELETE` require header **`If-Match: {@odata.etag}`**; `GET/PATCH /planner/tasks/{id}/details` (description, checklist, references) also etag-guarded | `Tasks.ReadWrite` | 412 on stale etag → re-read and retry; 409 on conflicting change; 400 if `@odata.type` missing on assignments or orderHint malformed (`" !"` appends). Add `Prefer: return=representation` to get the updated object from PATCH. **Planner ignores most OData params** (`$top`/`$select`/`$filter` → 400); slice client-side. |
| Delta | `GET /me/planner/all/delta` (plannerUser delta) | `Tasks.Read` | Bucket delta is beta only. |

Sources: [planner-overview](https://learn.microsoft.com/en-us/graph/api/resources/planner-overview?view=graph-rest-1.0), [planneruser-list-tasks](https://learn.microsoft.com/en-us/graph/api/planneruser-list-tasks?view=graph-rest-1.0).

### A.8 OneNote

| Operation | Method + path | Least scope | Notes |
|---|---|---|---|
| Notebooks / sections / pages | `GET /me/onenote/notebooks`, `GET /me/onenote/notebooks/{id}/sections`, `GET /me/onenote/sections`, `GET /me/onenote/sectionGroups`, `GET /me/onenote/pages` and `GET /me/onenote/sections/{id}/pages` (`$top` max 100, `$select=title,lastModifiedDateTime,links`, `$orderby=lastModifiedDateTime desc`) | `Notes.Read` | Also `/groups/{id}/onenote/…` and `/sites/{id}/onenote/…`. **No app-only auth at all** for OneNote. |
| Page content | `GET /me/onenote/pages/{id}/content?includeIDs=true` → HTML | `Notes.Read` | `includeIDs` yields element ids for PATCH targets. |
| Create page | `POST /me/onenote/sections/{id}/pages` with `Content-Type: text/html` (`<html><head><title>…</title><meta name="created" content="…"/></head><body>…</body></html>`) or `multipart/form-data` with a `Presentation` part plus binary parts referenced as `<img src="name:part1">` / `<object data-attachment="f.pdf" data="name:part2" type="application/pdf"/>` | `Notes.Create` (least) / `Notes.ReadWrite` | 201 with `links.oneNoteWebUrl`, `contentUrl`. |
| Update page | `PATCH /me/onenote/pages/{id}/content` body `[{target:"body"\|"title"\|"#{id}", action:"append"\|"prepend"\|"insert"\|"replace", position:"after"\|"before", content:"<p>…</p>"}]` | `Notes.ReadWrite` | – |
| Create notebook / section | `POST /me/onenote/notebooks {displayName}`, `POST /me/onenote/notebooks/{id}/sections {displayName}` | `Notes.Create` / `Notes.ReadWrite` | – |
| Delete page | `DELETE /me/onenote/pages/{id}` | `Notes.ReadWrite` | – |
| Search | `GET /me/onenote/pages?$search=…` | `Notes.Read` | Documented as consumer-OneDrive only; for work accounts use Search API `driveItem` over the notebook files instead. |

Sources: [onenote-api-overview](https://learn.microsoft.com/en-us/graph/api/resources/onenote-api-overview?view=graph-rest-1.0), [section-post-pages](https://learn.microsoft.com/en-us/graph/api/section-post-pages?view=graph-rest-1.0).

### A.9 Microsoft Search API

`POST /search/query` with one `searchRequest` (the array form is accepted but only one request is processed):

```json
{"requests":[{"entityTypes":["message"],"query":{"queryString":"from:adele subject:budget"},
  "from":0,"size":25,"enableTopResults":true,"fields":["subject","from","receivedDateTime","webLink"]}]}
```

| Entity type(s) | Scope needed | Limits |
|---|---|---|
| `message` | `Mail.Read` | `size` max **25**, `from` must be 0 on first page; sorted by date; `enableTopResults` returns 3 relevance-ranked first. |
| `event` | `Calendars.Read` | `size` max 25. |
| `chatMessage` | `Chat.Read` (chats) / `ChannelMessage.Read.All` (channels) | Cannot combine with other types. |
| `person` | `People.Read` | Default 25; filters on `PeopleType`/`PeopleSubtype`. |
| `driveItem`, `drive`, `list`, `listItem`, `site` (combinable with each other and `externalItem`) | `Files.Read.All` / `Sites.Read.All` (**admin**) | `size` up to 1000 (200 reasonable); `sortProperties`, `aggregations`, `collapseProperties` only here. |
| `acronym`, `bookmark`, `qna` | `Acronym.Read.All` etc. | Admin-curated answers. |

Rules: delegated tokens only (runs as the user, ACL-trimmed); KQL in `queryString`; `fields` acts like `$select`; no `$filter`; guests can't search mail/chat/people. Response: `value[].hitsContainers[].hits[].resource` plus `total` and `moreResultsAvailable`.
Sources: [search-api-overview](https://learn.microsoft.com/en-us/graph/api/resources/search-api-overview?view=graph-rest-1.0), [search-concept-overview](https://learn.microsoft.com/en-us/graph/search-concept-overview).

### A.10 Users/me

`GET /me?$select=id,displayName,mail,userPrincipalName,jobTitle,department,officeLocation,preferredLanguage,mobilePhone` (`User.Read`); `/me/mailboxSettings` (A.1); `/me/presence` (A.4); `/me/photo/$value` (A.3); `/me/memberOf` and `/me/transitiveMemberOf` need only `User.Read` for the signed-in user (other users: `User.Read.All`). Always request `offline_access` so MSAL receives a refresh token. Source: [user-list-memberof](https://learn.microsoft.com/en-us/graph/api/user-list-memberof?view=graph-rest-1.0).

### A.11 Groups

| Operation | Method + path | Least scope | Notes |
|---|---|---|---|
| My groups | `GET /me/memberOf/microsoft.graph.group?$select=id,displayName,mail,groupTypes` (add `$search`/`$filter` with `ConsistencyLevel: eventual` + `$count=true`; `$top` ≤999) | `User.Read` | `$filter=groupTypes/any(c:c eq 'Unified')` isolates Microsoft 365 groups (the ones with mailbox, files, Planner, Teams). |
| All groups | `GET /groups` | `GroupMember.Read.All` / `Group.Read.All` (**admin**) | – |
| Group conversations | `GET /groups/{id}/conversations`, `GET /groups/{id}/threads`, `GET .../threads/{id}/posts`, `POST /groups/{id}/threads/{id}/reply {post:{body}}` | `Group-Conversation.Read.All` / `Group.Read.All` (**admin**) | Microsoft 365 groups only. |
| Group resources | `GET /groups/{id}/drive/root/children`, `GET /groups/{id}/calendar/calendarView`, `GET /groups/{id}/planner/plans`, `GET /groups/{id}/onenote/notebooks` | `Group.Read.All` / `Files.Read.All` / `Tasks.Read` | – |

Source: [group-list-conversations](https://learn.microsoft.com/en-us/graph/api/group-list-conversations?view=graph-rest-1.0).

### A.12 Insights

`GET /me/insights/used` (`$orderby=LastUsed/LastAccessedDateTime desc`, `$filter=ResourceVisualization/Type eq 'PowerPoint'`), `/me/insights/shared`, `/me/insights/trending`; scope `Sites.Read.All` (**admin**); work accounts only; item-insights can be disabled by admin. **`used` and `shared` are deprecated and stop returning data after November 2026.** Substitute `GET /me/drive/recent` plus Search API `driveItem` queries sorted by `lastModifiedDateTime`.
Sources: [insights-list-used](https://learn.microsoft.com/en-us/graph/api/insights-list-used?view=graph-rest-1.0), [insights-trending](https://learn.microsoft.com/en-us/graph/api/resources/insights-trending?view=graph-rest-1.0).

### A.13 Cross-cutting mechanics

**JSON batching** `POST /$batch {requests:[{id, method, url:"/me/messages?$top=5", headers:{"Content-Type":"application/json", "ConsistencyLevel":"eventual"}, body, dependsOn:["1"]}]}`. Max 20 per batch; ids unique; responses may arrive out of order (`id` correlates); each response carries its own `status`; batch HTTP 200 does not mean sub-requests succeeded; per-request throttling still applies (429 inside the envelope); a failed dependency yields 424; `Content-Type` header is mandatory whenever a body is present. Good uses: "inbox + today's calendar + unread chats" in one round trip; resolving 20 plan titles for `/me/planner/tasks`. Outlook's 4-concurrent-request-per-mailbox limit still applies inside a batch, so keep Outlook sub-requests small or mark them `dependsOn` to serialise.
[json-batching](https://learn.microsoft.com/en-us/graph/json-batching)

**Delta queries** exist for: mail folders and messages (per folder), calendarView (range-scoped), contacts, contactFolders, driveItems (`token=latest` supported), listItems, todoTask/todoTaskList, chatMessages (chats and channels), users/groups (7-day token life), plannerUser (`/me/planner/all/delta`). Flow: follow `@odata.nextLink` until `@odata.deltaLink`; store the deltaLink; removed items come as `{"id":…, "@removed":{"reason":"deleted"}}`; `410 Gone` with a fresh URL in `Location` means "full resync"; expect replays. Query options must be on the first request only (they're encoded in the tokens). `Prefer: odata.maxpagesize=N` controls page size.
[delta-query-overview](https://learn.microsoft.com/en-us/graph/delta-query-overview)

**Change notifications (subscriptions)** need a public HTTPS `notificationUrl` that answers the validation handshake, expire quickly (mail ≈3 days, chat messages ≈1 hour, drive ≈30 days) and require encryption certificates for rich payloads. Out of scope for a local CLI; delta + polling is the substitute.
[subscription-post-subscriptions](https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions?view=graph-rest-1.0)

**Throttling**: global 130,000 requests/10 s per app; Outlook 10,000 requests per 10 min **per app per mailbox**, **4 concurrent**, 150 MB upload per 5 min; Teams message GETs 30 rps per app per tenant; Planner/To Do 350 per 10 s and 10,000 per hour per app per tenant; identity (users/groups) uses resource units (3,500–8,000 per 10 s per tenant). On 429 honour `Retry-After` (seconds); also watch `x-ms-throttle-limit-percentage`, `x-ms-throttle-scope`, `x-ms-throttle-information`; 503/504 → exponential backoff; presence 1,500 per 30 s.
[throttling-limits](https://learn.microsoft.com/en-us/graph/throttling-limits)

**Advanced directory queries**: `$search`, `$count`, `endsWith`, `ne`, `not`, `in` on some props, `$orderby` combined with `$filter`, and `$expand=manager($levels=…)` require `ConsistencyLevel: eventual` **and** `$count=true`; `$skip` unsupported there; `$expand` cannot mix with advanced params; the index can lag writes. Plain `startswith(displayName,'x')` and `eq` work without the header. Directory `$search` is tokenised (`"displayName:jo"`), not substring.
[aad-advanced-queries](https://learn.microsoft.com/en-us/graph/aad-advanced-queries)

**Time zones**: Outlook returns UTC unless `Prefer: outlook.timezone="…"`; `dateTimeTimeZone` values carry their own `timeZone` (Windows or IANA); `calendarView` start/end offsets are parsed from the parameter itself; `mailboxSettings.timeZone` is the user's preference and the right default for a CLI. KQL `received:`/`sent:` compare by calendar day only.

**Beta-only features worth flagging (not for the default code path)**: message `mentions`/`mentionsPreview`; `onlineMeetings/{id}/aiInsights`; Teams admin/policy APIs; Planner bucket delta; Search API `person` examples still show `/beta` but the entity is GA in v1.0. Evolvable enums (`systemEventMessage` etc.) need `Prefer: include-unknown-enum-members` even on v1.0.

### A.14 Suggested scope bundles for the CLI (least privilege per command group)

| Command group | Scopes | Admin consent by default? |
|---|---|---|
| core | `User.Read`, `offline_access`, `openid`, `profile` | No |
| mail read | `Mail.Read` (or `Mail.ReadBasic` for lists without bodies) | No |
| mail write/send | `Mail.ReadWrite`, `Mail.Send` | No |
| mailbox settings/rules/OOF/categories | `MailboxSettings.ReadWrite` | No |
| calendar | `Calendars.ReadWrite`, `Calendars.Read.Shared` (findMeetingTimes) | No |
| contacts/people | `Contacts.ReadWrite`, `People.Read`, `User.ReadBasic.All` | No |
| org chart | `User.Read.All` | **Yes** |
| files (own) | `Files.ReadWrite` | No |
| files (shared/sharepoint/lists/search) | `Files.ReadWrite.All` or `Sites.Read.All`/`Sites.ReadWrite.All` | **Yes** |
| teams chats | `Chat.ReadWrite` (or `Chat.Read` + `ChatMessage.Send`), `Chat.Create`, `Team.ReadBasic.All`, `Channel.ReadBasic.All` | No |
| teams channels | `ChannelMessage.Read.All`, `ChannelMessage.Send`, `TeamMember.Read.All` | Read.All **Yes** |
| presence | `Presence.Read`, `Presence.ReadWrite`; others `Presence.Read.All` | Read.All **Yes** |
| meetings/transcripts | `OnlineMeetings.ReadWrite`, `OnlineMeetingTranscript.Read.All` (+ `OnlineMeetingRecording.Read.All`) | Transcript/Recording **Yes** |
| to do / planner | `Tasks.ReadWrite` (+ `Group.Read.All` for plan discovery) | Group.Read.All **Yes** |
| onenote | `Notes.ReadWrite` | No |
| rooms | `Place.Read.All` | **Yes** |

Admin-consent column from the [permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference).

### A.15 The consent trap (2025 change every third-party Graph app now hits)

Since Aug–Nov 2025 the **Microsoft-managed default user consent policy** (the default for new tenants and for tenants that left "Let Microsoft manage your consent settings" on) blocks end users from consenting to, among others: `Mail.Read`, `Mail.ReadWrite`, `Mail.ReadBasic`, `Mail.*.Shared`, `MailboxSettings.Read/ReadWrite`, `MailboxFolder.*`, `Calendars.Read`, `Calendars.ReadBasic`, `Calendars.ReadWrite`, `Calendars.*.Shared`, `Contacts.ReadWrite`, `Contacts.*.Shared`, `Chat.Read`, `Chat.ReadWrite`, `OnlineMeetings.Read/ReadWrite`, `Tasks.Read/ReadWrite`, `People.Read`, `Files.Read.All`, `Files.ReadWrite.All`, `Sites.Read.All`, `Sites.ReadWrite.All`, plus EWS/IMAP/POP/EAS. Consequence: a multi-tenant public client that asks for `Mail.Read` shows "Need admin approval" to ordinary users in such tenants; an admin must grant tenant-wide consent once (admin-consent URL `https://login.microsoftonline.com/{tenant}/adminconsent?client_id={id}`) or the tenant must run a custom consent policy. `Mail.Send`, `Files.ReadWrite`, `Notes.*`, `ChatMessage.Send`, `ChannelMessage.Send`, `Presence.*`, `User.ReadBasic.All`, `Team.ReadBasic.All` are not on the blocked list.
Sources: [manage-app-consent-policies](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/manage-app-consent-policies), [topedia summary of the Nov 2025 expansion](https://blog-en.topedia.com/2025/11/microsoft-managed-default-app-consent-policy-now-blocks-20-additional-permissions/).

---

## Part B: Python implementation stack

### B.1 Authentication library: `msal` (+ `msal-extensions`) vs `azure-identity`

| | `msal` 1.38.0 (2026-08-24) + `msal-extensions` 1.3.1 (2025-03-14) | `azure-identity` 1.25.3 (2026-03-13) |
|---|---|---|
| Python | ≥3.9 | ≥3.9 |
| Transitive deps | msal → `requests`, `PyJWT[crypto]`, `cryptography`; extensions → `portalocker` (+ optional `msal[broker]`) | `azure-core`, `msal`, `msal-extensions`, `cryptography`, `typing-extensions` |
| Interactive auth-code | `PublicClientApplication.acquire_token_interactive(scopes, port=None, prompt, login_hint, timeout, parent_window_handle)` — spins a loopback listener on `http://localhost:<random port>`; only `http://localhost` (no port) needs registering as a *Mobile and desktop* redirect URI | `InteractiveBrowserCredential(client_id, tenant_id, redirect_uri, cache_persistence_options, authentication_record)` |
| Device code | `initiate_device_flow(scopes)` → print `message` → `acquire_token_by_device_flow(flow)` | `DeviceCodeCredential(prompt_callback=…)` |
| Silent refresh | `get_accounts()` → `acquire_token_silent(scopes, account, force_refresh)`; returns `None` when interaction is needed | `get_token(*scopes)` refreshes automatically, raises `AuthenticationRequiredError` when `disable_automatic_authentication=True` |
| Persistent cache | `PersistedTokenCache(build_encrypted_persistence(path))` → Keychain (macOS), DPAPI (Windows), libsecret (Linux); `FilePersistence` plaintext fallback; auto-reload + file locking | `TokenCachePersistenceOptions(name, allow_unencrypted_storage)` wrapping the same msal-extensions machinery; `AuthenticationRecord.serialize()` to remember the account |
| Claims / CAE / MFA challenges | Result dict exposes `error`, `error_description`, `claims`; pass `claims_challenge` back; `client_capabilities=["CP1"]` for CAE | Surfaced as exceptions; claims handled internally for `get_token(claims=…)` |
| Brokers (WAM / macOS Company Portal) | `enable_broker_on_windows=True`, `enable_broker_on_mac=True` with `msal[broker]>=1.31`; macOS needs an Intune-managed device with Company Portal and a `msauth.com.msauth.unsignedapp://auth` redirect URI registered; falls back to browser otherwise | Same switches via `enable_support_for_broker` / `InteractiveBrowserBrokerCredential` (`azure-identity-broker`) |
| Fit for a CLI | Explicit control over prompts, scopes-per-command, device-code fallback and error text | Adds `azure-core` pipeline weight and hides the consent/claims details a CLI wants to print |

**Recommendation: `msal` + `msal-extensions` directly.** Fewer packages, explicit flow control (silent → interactive → device-code fallback with `--device-code`), the result dict maps cleanly onto CLI error messages ("Need admin approval", `AADSTS65001`, claims challenges), and the encrypted OS cache is the same code `azure-identity` uses. Keep `azure-identity` only if the team later wants `msgraph-sdk` (which requires it). Note `msal` pulls `requests`; that is fine alongside `httpx` (or pass an httpx-based `http_client` adapter to MSAL if a single HTTP stack becomes a goal).
Sources: [PyPI msal](https://pypi.org/project/msal/), [MSAL Python docs](https://msal-python.readthedocs.io/en/latest/), [MSAL Python overview](https://learn.microsoft.com/en-us/entra/msal/python/), [macOS broker](https://learn.microsoft.com/en-us/entra/msal/python/advanced/macos-broker), [PyPI msal-extensions](https://pypi.org/project/msal-extensions/), [PyPI azure-identity](https://pypi.org/project/azure-identity/), [redirect/port guidance](https://github.com/AzureAD/microsoft-authentication-library-for-python/discussions/494).

Implementation notes:

- Register the app as *Mobile and desktop applications* with redirect `http://localhost`, and set **Allow public client flows = Yes** (required for device code). [desktop app configuration](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-configuration)
- Ask for scopes incrementally per command group (A.14) with `acquire_token_silent(scopes)`; MSAL merges consented scopes in the cache, so a user who first ran `mail` and later runs `teams` gets one extra consent prompt, not a re-login.
- Cache location: `~/.config/msgraph-cli/token_cache.bin` via `build_encrypted_persistence`; on Linux without a secret service, fall back to `FilePersistence` and warn.
- Print `result.get("error_description")` and the `correlation_id` on failures; detect `AADSTS65001`/`AADSTS650052` (consent) and print the admin-consent URL.
- Conditional Access may block device-code flow tenant-wide (Microsoft shipped a managed CA policy for this in 2025); keep auth-code + localhost as the default and device code as an explicit fallback. [Blocking device code flow](https://securityboulevard.com/2025/04/blocking-device-code-flow-in-microsoft-entra-id/)

### B.2 Client-ID strategy: custom registration vs well-known first-party IDs

| Option | What works | What does not | Verdict |
|---|---|---|---|
| **Own multi-tenant public client** (the Node CLI already ships `00000000-0000-0000-0000-000000000000`, tenant `common`) | Any delegated scope; auth-code + localhost and device code; per-command scope sets; branding in the consent screen | Needs one-time admin consent in tenants under the Microsoft-managed consent policy for Mail/Calendar/Chat/Tasks/Files.All (A.15); MSA (personal) accounts require `AzureADandPersonalMicrosoftAccount` audience | **Default.** Make client id and tenant overridable via `MSGRAPH_CLIENT_ID` / `MSGRAPH_TENANT_ID` so a tenant admin can register a tenant-local app. |
| Azure CLI `04b07795-8ddb-461a-bbee-02f9e1bf7b46` | Works in any tenant without registration for its pre-authorised Graph scopes (`Directory.AccessAsUser.All`, `User.ReadWrite.All`, `Group.ReadWrite.All`, `AuditLog.Read.All`, …) | Mail, calendar, OneDrive scopes are **not** pre-authorised and cannot be user-consented; Microsoft365R documents it as "not Outlook, not OneDrive"; heavily associated with device-code phishing (Storm-2372), so SOCs alert on it; Microsoft forbids reusing first-party app ids to impersonate its apps | Not viable for a mail CLI. |
| Microsoft Graph PowerShell / "Microsoft Graph Command Line Tools" `14d82eec-204b-4c2f-b7e8-296a70dab67e` | Incremental consent to arbitrary delegated scopes if the tenant allows it; often already admin-consented because admins use the SDK; token cache format identical to MSAL | Many tenants block it with Conditional Access; since SDK 2.34 (Dec 2025) Microsoft made WAM the default and announced **service-side enforcement** that pre-2.36.1 clients can no longer use delegated auth with this app except via WAM, which signals that plain browser/device-code reuse of the id is being shut down; reuse violates the first-party app terms | Offer only as an opt-in `--client-id` escape hatch; do not depend on it. |
| Azure PowerShell `1950a258-227b-4e31-a9cf-717495945fc2`, Office `d3590ed6-52b3-4102-aeff-aad2292ab01c` | Same story as Azure CLI | Same limits; Office id is scrutinised even more | No. |

Sources: [Microsoft365R auth vignette](https://cran.r-project.org/web/packages/Microsoft365R/vignettes/auth.html), [Quest for a Graph access token](https://smsagent.blog/2024/03/19/the-quest-for-a-microsoft-graph-access-token/), [az account get-access-token scope limits](https://github.com/Azure/azure-cli/issues/12986), [Graph PowerShell WAM enforcement (Aug 2026)](https://office365itpros.com/2026/08/28/interactive-graph-sessions-wam/), [device-code phishing detection](https://www.silverfort.com/blog/device-code-attacks-in-azure-from-exploitation-to-detection/), [Practical365 on the Graph SDK enterprise app](https://practical365.com/connect-microsoft-graph-powershell-sdk/).

### B.3 HTTP layer: `httpx` vs `requests` vs `msgraph-sdk`

| | `httpx` 0.28.1 (2024-12-06; 1.0.dev6 pre-release 2026-08-31) | `requests` 2.x | `msgraph-sdk` 1.61.0 (2026-08-05) |
|---|---|---|---|
| Deps | `httpcore`, `h11`, `certifi`, `idna`, `anyio`; extras `http2`, `zstd` | `urllib3`, `charset_normalizer`, `certifi`, `idna` | `msgraph-core`, kiota abstractions/serialization/http, `azure-identity`; **28 MB wheel**, Python ≥3.10, async-first |
| Timeouts | Per-request defaults (5 s) — good for a CLI | No default timeout | Configurable via kiota |
| Streaming up/down | `client.stream(...)`, `content=` iterables for chunked PUT | Yes | Yes (large-file upload helper) |
| Mocking | `respx` 0.23.1 or `pytest-httpx` 0.36.2 | `responses` | Hard |
| Graph specifics (paging, batch, Retry-After, Prefer headers) | Write a ~150-line wrapper | Same | Built-in, but the fluent request-builder tree costs import time and hides raw JSON |

**Recommendation: raw REST over `httpx` (sync `httpx.Client`, HTTP/1.1 default; pin `httpx<1` until 1.0 ships).** Wrapper responsibilities: base URL + version switch (`v1.0`/`beta`), bearer injection from MSAL, default `Prefer` headers (`outlook.timezone`, `outlook.body-content-type="text"`, `IdType="ImmutableId"`), `@odata.nextLink` paging generator with `--limit`, `$batch` helper (chunks of 20, `dependsOn` for Outlook), 429/503/504 retry honouring `Retry-After` with jittered backoff (max ~5 tries), redirect handling for `/content` downloads (drop `Authorization` on the 302 target), error mapping (`error.code`, `error.message`, `request-id`) to a typed exception, and a `--debug` request log. `msgraph-sdk` is rejected: cold-start import cost, 28 MB install on every fresh machine, azure-identity coupling, and the CLI needs raw JSON anyway. `msgraph-core` alone is lighter but still drags kiota.
Sources: [PyPI httpx](https://pypi.org/project/httpx/), [httpx 1.0.dev6](https://pypi.org/project/httpx/1.0.dev6/), [PyPI msgraph-sdk](https://pypi.org/project/msgraph-sdk/), [PyPI respx](https://pypi.org/project/respx/), [PyPI pytest-httpx](https://pypi.org/project/pytest-httpx/).

### B.4 CLI framework and output

- `typer` 0.27.2 (2026-08-28, Python ≥3.10): now **vendors Click** (since 0.26) and bundles `rich`, `shellingham`, `annotated-doc`; `typer-slim` is an alias; `TYPER_USE_RICH=0` disables rich help/tracebacks. Typed options, subcommand groups (`mail`, `calendar`, `teams`…), auto help, `typer.testing.CliRunner`.
- `click` 8.5.0 (2026-08-26) if a smaller surface is preferred; `argparse` is zero-dependency but the Node CLI already showed how much hand-rolled parsing that costs.
- `rich` 15.0.0 (2026-04-12) for tables/markdown; import lazily inside `table` rendering to keep `--json` fast.
- Output modes: `--output json|table|plain` (default `json` when stdout is not a TTY, `table` when it is); `--json` alias; stable exit codes (0 ok, 1 Graph error, 2 usage, 3 auth needed, 4 throttled/timeout) so Claude can branch; write human noise to stderr only.
- Startup budget: `typer`+`rich` ≈150–250 ms, `msal` ≈150 ms, `httpx` ≈80 ms — acceptable for an agent-driven CLI; lazy-import `rich`, `markdownify`, and `msal` broker bits.

**Recommendation: typer** (vendored Click removes the version-skew risk) with rich tables. Sources: [PyPI typer](https://pypi.org/project/typer/), [PyPI click](https://pypi.org/project/click/), [PyPI rich](https://pypi.org/project/rich/).

### B.5 HTML → text

- Mail and calendar bodies: use the server (`Prefer: outlook.body-content-type="text"`) and skip client conversion entirely; keep `bodyPreview` for lists.
- Teams messages (`body.contentType: html` with `<at>`, `<attachment>`, `<img src=".../hostedContents/...">`), OneNote page HTML, SharePoint page content: convert client-side.
- `markdownify` 1.2.3 (2026-06-30, MIT, depends on `beautifulsoup4` + `six`): produces Markdown, configurable `strip`/`convert`/`heading_style`/`bullets`; best fit for Claude consumption.
- `html2text` 2025.4.15 is **GPL-3.0-or-later** — avoid as a dependency of an MIT-licensed plugin.
- `beautifulsoup4` (+ `html.parser`, no `lxml`) is enough for `<at>`→`@Name`, `<attachment>` placeholders and stripping `<systemEventMessage/>`.

Sources: [PyPI markdownify](https://pypi.org/project/markdownify/), [PyPI html2text](https://pypi.org/project/html2text/).

### B.6 Packaging with `uv` for a Claude Code skill

Facts that shape the choice:

- Claude Code substitutes `${CLAUDE_SKILL_DIR}` (the skill folder) and, for plugins, `${CLAUDE_PLUGIN_ROOT}` (install dir) and **`${CLAUDE_PLUGIN_DATA}`** (persistent per-plugin data dir that survives updates). Marketplace plugins are copied to `~/.claude/plugins/cache/{marketplace}/{plugin}/{version}/`; the docs say **do not write `.venv` or state into the plugin root**, use `${CLAUDE_PLUGIN_DATA}`. Skills with `allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/... *)` run bundled scripts without prompts. Claude Code auto-installs *Node* deps from a lockfile; nothing equivalent for Python. [skills](https://code.claude.com/docs/en/skills), [plugins-reference](https://code.claude.com/docs/en/plugins-reference)
- `uv run script.py` with PEP 723 metadata builds an isolated, cached environment (in `UV_CACHE_DIR`, not next to the script) and **ignores any surrounding project**; `--script` forces script mode; `uv lock --script x.py` writes `x.py.lock`, which `uv run` then honours; `[tool.uv] exclude-newer = "…"` caps resolution by date; `requires-python` + automatic managed-Python downloads mean a machine with only `uv` gets an interpreter. [uv scripts](https://docs.astral.sh/uv/guides/scripts/), [uv python versions](https://docs.astral.sh/uv/concepts/python-versions/), [locking PEP 723 scripts (May 2026)](https://pydevtools.com/blog/locking-dependencies-for-pep-723-scripts/)
- `uv run --project <dir>` runs inside a project found at `<dir>`; `--frozen` uses `uv.lock` as-is (error if missing) without re-resolving; `--locked` asserts the lock is current; `--no-sync` skips env updates; `--no-project` ignores project discovery; `UV_PROJECT_ENVIRONMENT` relocates the `.venv`; `UV_NO_PROGRESS=1` silences spinners. [uv run](https://docs.astral.sh/uv/concepts/projects/run/), [uv env vars](https://docs.astral.sh/uv/reference/environment/), [uv CLI](https://docs.astral.sh/uv/reference/cli/)
- `uv tool install` puts a persistent tool on PATH — right for end users who want `msgraph` globally, wrong as the skill's execution model (the skill cannot assume it ran). [uv tools](https://docs.astral.sh/uv/concepts/tools/)

| Layout | Invocation from SKILL.md | Reproducibility | Writes into plugin dir? | Tests | Verdict |
|---|---|---|---|---|---|
| **A. PEP 723 entry script** `scripts/msgraph.py` (+ sibling package `scripts/msgraph_cli/` imported via the script's own directory on `sys.path`) with `scripts/msgraph.py.lock` and `exclude-newer` | `uv run --script ${CLAUDE_SKILL_DIR}/scripts/msgraph.py mail list` | Exact via sidecar lock (uv-only) | **No** (env lives in uv cache) | Needs `uv run --with pytest --with respx --script …` or a separate dev pyproject | Simplest for a "just works" skill; env per script hash |
| **B. Small uv project** in `scripts/` (`pyproject.toml`, `uv.lock`, `src/msgraph_cli/`, `[project.scripts] msgraph = …`, `[dependency-groups] dev`) | `UV_PROJECT_ENVIRONMENT="${CLAUDE_PLUGIN_DATA:-$HOME/.cache/msgraph-cli}/venv" uv run --project ${CLAUDE_SKILL_DIR}/scripts --frozen --no-dev msgraph mail list` (wrap in `scripts/msgraph` shell shim) | Exact via `uv.lock` | Only if `UV_PROJECT_ENVIRONMENT` is unset → **must** set it | `uv run --project scripts pytest` with dev group | Best for a multi-module CLI with a real test suite |
| C. `uv tool install` / `uvx --from git+…` | `uvx --from ${CLAUDE_SKILL_DIR}/scripts msgraph …` | Lock via `uv.lock` in the source | No (tool cache) | Same as B | Good extra for humans; `uvx` re-resolves on every call unless cached |

**Recommendation: B with a shell shim.** The CLI will have a dozen modules, fixtures and tests; a project gives one lockfile, editable installs during development, `pytest` in a dev group, and `uv run --frozen` startup of ~30–50 ms once synced (first run on a fresh machine: Python download + resolve/install ≈ 10–40 s, so print a one-line "installing" notice to stderr). Pin `requires-python = ">=3.11,<3.14"`, commit `uv.lock`, set `exclude-newer` in `[tool.uv]` as belt-and-braces, and have the shim export `UV_PROJECT_ENVIRONMENT` under `${CLAUDE_PLUGIN_DATA}` (fallback `~/.cache/msgraph-cli`) plus `UV_NO_PROGRESS=1`. Keep A as the documented fallback for tiny helper scripts. Add `allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/msgraph *)` to the skill frontmatter so invocations don't prompt.

### B.7 Testing

- `pytest` + **`respx`** (httpx transport mock; `respx.mock` fixture, `respx.get(url).mock(return_value=httpx.Response(200, json=…))`, `route.called`) for Graph calls; `pytest-httpx` (`httpx_mock.add_response`) is the alternative — pick one, `respx` is the more expressive router.
- Fixture corpus: recorded Graph JSON per endpoint (`tests/fixtures/graph/*.json`), including 429 with `Retry-After`, 504, `InefficientFilter`, batch envelopes, upload-session sequences, `@odata.nextLink` chains, and delta `@removed` pages.
- Auth: inject a `TokenProvider` protocol; tests use a fake returning a static token; one integration-style test drives MSAL with a `SerializableTokenCache` seeded from a fixture to cover the silent path.
- CLI: `typer.testing.CliRunner().invoke(app, ["mail", "list", "--json"])`; assert JSON shape and exit codes; snapshot `table` output with `TYPER_USE_RICH=0` / `NO_COLOR=1`.
- Keep the Node CLI's `evals/evals.json` prompts as behavioural acceptance tests for the skill.

---

## Ranked "beyond mail + calendar basics" feature candidates

Ranked by value for a Claude-driven personal productivity CLI, weighted by how cheaply the API delivers it and how often scopes are consentable.

1. **Unified search** (`POST /search/query` over `message`, `event`, `driveItem`, `chatMessage`, `person`) with KQL passthrough — one command answers "find anything about X".
2. **Free/busy + meeting-time suggestions + booking** (`getSchedule`, `findMeetingTimes`, `POST /me/events` with Teams link, `transactionId`) — the scheduling loop end-to-end.
3. **Teams chats: list unread, read thread, reply, start 1:1** (`viewpoint.lastMessageReadDateTime`, `POST /chats`, `ChatMessage.Send`) — no admin consent needed, high daily value.
4. **Mail triage actions**: mark read/flag/categorise/move/archive, focused/other, reply-all/forward with `comment`, draft-then-send with large attachments (upload session).
5. **Meeting transcripts → text** (`transcripts/{id}/content` VTT with attributed-speaker fallback; resolve meeting from event `joinUrl`) — feeds summarisation; admin-consent scope, so degrade gracefully.
6. **To Do integration**: create tasks from mail (`linkedResources` with the message `webLink`), list due/overdue, tick checklist items; plus `flaggedEmails` list.
7. **Out-of-office and mailbox settings** (`automaticRepliesSetting`, `timeZone`, `workingHours`) — trivial API, frequent ask.
8. **Files quick actions**: download by pasted link (`/shares/u!…`), upload with resumable session, create share link (`organization` scope), recent files (`/me/drive/recent`).
9. **Presence**: show own/colleagues' status (`getPresencesByUserId`) and set DND for N hours (`setUserPreferredPresence` + `expirationDuration`).
10. **Delta-based "what changed since last run"** for inbox, calendar window and drive — local state file with deltaLinks, enabling cheap polling loops and digests.

Honourable mentions: Planner "my tasks" with plan titles via `$batch`; OneNote page append (`PATCH .../content`); people lookup with org chart (`manager($levels=max)`); mail rules CRUD; `$batch` "morning briefing" (inbox unread + today + chats) in one call.

## Top gotchas (design constraints)

1. **Consent policy (A.15)**: in tenants on the Microsoft-managed default, `Mail.Read`, `Calendars.*`, `Chat.Read`, `Tasks.*`, `People.Read`, `Files/Sites.*.All` need admin consent for a third-party app; the CLI must detect `AADSTS65001` and print the admin-consent URL instead of looping through login.
2. **First-party client ids are not a shortcut**: Azure CLI's app has no mail/calendar scopes; the Graph PowerShell app is moving to WAM-only server-side enforcement and is commonly CA-blocked.
3. **Outlook query rules**: `$search` (KQL, ≤1,000 results, no `$orderby`/`$count`, don't mix with `$filter`) vs `$filter` (`$orderby` properties must lead the filter or `InefficientFilter`); `received:` is day-granular; page bodies are HTML unless the `Prefer` header is sent; ids change on move unless `IdType="ImmutableId"`.
4. **Upload sessions**: Outlook chunks ≤4 MB, OneDrive chunks in 320 KiB multiples <60 MiB, sequential, **no Authorization header** on the pre-authenticated `uploadUrl`; `/content` downloads 302 to a URL that must not receive the bearer.
5. **Teams paging is small and rigid**: `$top` ≤50 for chats/messages, channel messages only `$top`/`$expand`, `$filter` must pair with the same `$orderby`, `expand=members` caps at 25; message HTML needs client-side conversion and hosted images need authenticated fetches.
6. **Planner etags**: every PATCH/DELETE needs `If-Match` from `@odata.etag`; OData params are rejected (slice client-side); premium plans invisible; `orderHint` must be `" !"`-style.
7. **Throttling shape**: Outlook 4 concurrent requests per mailbox (batching doesn't bypass it), 10k/10 min; honour `Retry-After`; Presence 1,500/30 s; Search API `size` ≤25 for mail/events.
8. **Deprecations with dates**: `/me/drive/sharedWithMe` and `/me/insights/used|shared` stop returning data after November 2026; `/me/people` is in maintenance mode (use Search `person`); Microsoft Graph CLI (`mgc`) retired 2026-08-28 (irrelevant to us but explains why no first-party CLI exists to wrap).
9. **Plugin dir is ephemeral**: never create `.venv` under `${CLAUDE_PLUGIN_ROOT}`; use `${CLAUDE_PLUGIN_DATA}` (`UV_PROJECT_ENVIRONMENT`) or PEP 723 script envs in the uv cache; first run downloads Python and packages, so emit a stderr notice and keep `UV_NO_PROGRESS=1`.
10. **Device code can be blocked by Conditional Access** (Microsoft-managed policy, 2025) and MSA/consumer accounts lack Teams, Planner, findMeetingTimes, getSchedule, Search API — default to auth-code + `http://localhost` and detect account type from the token's `tid`.

---

## Sources

Microsoft Graph (all read 2026-09-02):
- https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-beta
- https://learn.microsoft.com/en-us/graph/api/message-get?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/search-query-parameter
- https://learn.microsoft.com/en-us/graph/outlook-large-attachments
- https://learn.microsoft.com/en-us/graph/outlook-immutable-id
- https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/message-reply?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/message-move?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/user-list-mailfolders?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/outlookuser-list-mastercategories?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/resources/messagerule?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/user-get-mailboxsettings?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/resources/manage-focused-inbox?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/delta-query-messages
- https://learn.microsoft.com/en-us/graph/api/user-list-calendars?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/user-list-events?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/user-post-events?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/event-accept?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/user-findmeetingtimes?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/calendar-getschedule?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/place-list?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/application-post-onlinemeetings?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/user-list-contacts?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/user-list-people?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/search-concept-person
- https://learn.microsoft.com/en-us/graph/api/user-list?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/user-list-manager?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/user-list-memberof?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/profilephoto-get?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/aad-advanced-queries
- https://learn.microsoft.com/en-us/graph/api/user-list-joinedteams?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/channel-list-messages?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/chatmessage-post?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/chat-list?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/chat-list-messages?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/chat-post-messages?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/chat-post?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/presence-get?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/presence-setuserpreferredpresence?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/onlinemeeting-list-transcripts?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/calltranscript-get?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/driveitem-search?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/driveitem-put-content?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/driveitem-createuploadsession?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/driveitem-createlink?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/drive-sharedwithme?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/shares-get?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/site-search?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/listitem-list?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/resources/todo-overview?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/todotasklist-post-tasks?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/resources/planner-overview?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/planneruser-list-tasks?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/resources/onenote-api-overview?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/section-post-pages?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/search-concept-overview
- https://learn.microsoft.com/en-us/graph/api/resources/search-api-overview?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/group-list-conversations?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/insights-list-used?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/resources/insights-trending?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/json-batching
- https://learn.microsoft.com/en-us/graph/delta-query-overview
- https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/throttling-limits
- https://learn.microsoft.com/en-us/graph/permissions-reference

Identity and consent:
- https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/manage-app-consent-policies
- https://blog-en.topedia.com/2025/11/microsoft-managed-default-app-consent-policy-now-blocks-20-additional-permissions/
- https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-configuration
- https://securityboulevard.com/2025/04/blocking-device-code-flow-in-microsoft-entra-id/
- https://www.silverfort.com/blog/device-code-attacks-in-azure-from-exploitation-to-detection/
- https://cran.r-project.org/web/packages/Microsoft365R/vignettes/auth.html
- https://smsagent.blog/2024/03/19/the-quest-for-a-microsoft-graph-access-token/
- https://github.com/Azure/azure-cli/issues/12986
- https://practical365.com/connect-microsoft-graph-powershell-sdk/
- https://office365itpros.com/2026/08/28/interactive-graph-sessions-wam/
- https://devblogs.microsoft.com/microsoft365dev/microsoft-graph-cli-retirement/

Python stack:
- https://pypi.org/project/msal/
- https://msal-python.readthedocs.io/en/latest/
- https://learn.microsoft.com/en-us/entra/msal/python/
- https://learn.microsoft.com/en-us/entra/msal/python/advanced/macos-broker
- https://github.com/AzureAD/microsoft-authentication-library-for-python/discussions/494
- https://pypi.org/project/msal-extensions/
- https://pypi.org/project/azure-identity/
- https://pypi.org/project/httpx/
- https://pypi.org/project/httpx/1.0.dev6/
- https://pypi.org/project/msgraph-sdk/
- https://pypi.org/project/typer/
- https://pypi.org/project/click/
- https://pypi.org/project/rich/
- https://pypi.org/project/markdownify/
- https://pypi.org/project/html2text/
- https://pypi.org/project/respx/
- https://pypi.org/project/pytest-httpx/

uv and Claude Code packaging:
- https://docs.astral.sh/uv/guides/scripts/
- https://docs.astral.sh/uv/concepts/projects/run/
- https://docs.astral.sh/uv/concepts/tools/
- https://docs.astral.sh/uv/concepts/python-versions/
- https://docs.astral.sh/uv/reference/environment/
- https://docs.astral.sh/uv/reference/cli/
- https://pydevtools.com/blog/locking-dependencies-for-pep-723-scripts/
- https://code.claude.com/docs/en/skills
- https://code.claude.com/docs/en/plugins-reference
