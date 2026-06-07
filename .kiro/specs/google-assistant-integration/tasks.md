# Implementation Plan: Google Assistant Integration

## Overview

This plan connects Michael's Google account (Gmail, Calendar, Tasks, Contacts) to the 595BowersHub AI platform. n8n workflows expose Google data via HTTP webhook endpoints, and a dedicated "Google Assistant" AnythingLLM workspace instructs the AI to call those webhooks for live data. All n8n workflows are created/updated via the n8n REST API (PUT/POST to http://100.106.180.101:5678/api/v1/). Tasks are ordered: Google Cloud setup (manual) → n8n credential (manual) → Gmail webhooks → Calendar webhooks → Tasks webhooks → Contacts webhooks → AnythingLLM workspace → testing.

## Tasks

- [ ] 1. Google Cloud Console project setup (manual — Michael)
  - [ ] 1.1 Create Google Cloud project and enable APIs
    - Go to https://console.cloud.google.com → Create project named "595BowersHub"
    - Enable APIs: Gmail API, Google Calendar API, Google Tasks API, Google People API
    - Configure OAuth consent screen (External with test user = Michael's Gmail address)
    - Create OAuth2 Client ID (Web application type)
    - Set Authorized redirect URI: `http://100.106.180.101:5678/rest/oauth2-credential/callback`
    - Save the Client ID and Client Secret for the next step
    - _Requirements: 1.1, 1.2, 10.1_

- [ ] 2. Checkpoint — Verify Google Cloud project
  - Confirm all 4 APIs are enabled, OAuth consent screen is configured, and Client ID/Secret are saved. Ask the user if questions arise.

- [ ] 3. n8n Google OAuth2 credential setup (manual — Michael)
  - [ ] 3.1 Create the Google OAuth2 credential in n8n and authorize
    - In n8n UI: Settings → Credentials → Add Credential → Google OAuth2 API
    - Enter Client ID and Client Secret from Google Cloud Console
    - Set scopes: `https://www.googleapis.com/auth/gmail.modify`, `https://www.googleapis.com/auth/calendar`, `https://www.googleapis.com/auth/tasks`, `https://www.googleapis.com/auth/contacts.readonly`
    - Click "Sign in with Google" — authorize in browser with Michael's Google account
    - Verify the credential shows "Connected" status
    - Note the credential name (use "Google OAuth2" or similar) — all workflows will reference it by name
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 10.4_

- [ ] 4. Checkpoint — Verify OAuth2 credential
  - Confirm the credential shows "Connected" in n8n. Test it by creating a quick test workflow with a Gmail node to verify token works. Delete the test workflow after. Ask the user if questions arise.

- [ ] 5. Implement Gmail read webhooks
  - [ ] 5.1 Create the Gmail Inbox webhook workflow via n8n API
    - POST to `http://100.106.180.101:5678/api/v1/workflows` to create a new workflow
    - Workflow name: "Google - Gmail Inbox"
    - Nodes: Webhook (GET, path: `gmail/inbox`, response mode: "Using 'Respond to Webhook' Node") → Code (extract `maxResults` from query, default 20, cap at 50) → Gmail node (Get Many, credential: Google OAuth2, label: INBOX, limit from param) → Code (format response: map to `{id, from, to, subject, date, snippet, labels}`) → Respond to Webhook (200, JSON array)
    - Error branch: Gmail node error output → Code (error handler: 401/429/502 logic) → Respond to Webhook (error status + JSON error body)
    - Activate the workflow after creation
    - _Requirements: 2.1, 2.6, 11.1, 11.2, 11.4_

  - [ ] 5.2 Create the Gmail Search webhook workflow via n8n API
    - Workflow name: "Google - Gmail Search"
    - Nodes: Webhook (GET, path: `gmail/search`) → Code (validate `query` param exists, extract `maxResults` default 20 cap 50; return 400 if query missing) → IF (validation passed?) → Gmail node (Get Many, credential: Google OAuth2, search query from param) → Code (format response) → Respond to Webhook (200)
    - Error branches: validation fail → Respond to Webhook (400, `{"error": "Missing required field(s): query"}`); Gmail error → error handler → Respond to Webhook (502)
    - Activate the workflow
    - _Requirements: 2.2, 2.5, 2.6, 11.1, 11.4_

  - [ ] 5.3 Create the Gmail Message Detail webhook workflow via n8n API
    - Workflow name: "Google - Gmail Message"
    - Nodes: Webhook (GET, path: `gmail/message/{{messageId}}`) → Gmail node (Get, credential: Google OAuth2, message ID from path param) → Code (format full email: `{id, from, to, cc, bcc, subject, date, body, labels, attachments}`, prefer plain text body, HTML fallback) → Respond to Webhook (200)
    - Error branch: Gmail 404 → Respond to Webhook (404, `{"error": "Message not found: {id}"}`); other errors → 502
    - Activate the workflow
    - _Requirements: 2.3, 2.6, 11.1, 11.4_

  - [ ] 5.4 Create the Gmail Labels webhook workflow via n8n API
    - Workflow name: "Google - Gmail Labels"
    - Nodes: Webhook (GET, path: `gmail/labels`) → Gmail node (Get Labels, credential: Google OAuth2) → Code (format: `{id, name, type}`) → Respond to Webhook (200)
    - Error branch: standard error handler
    - Activate the workflow
    - _Requirements: 2.4, 2.6, 11.1, 11.4_

- [ ] 6. Implement Gmail write webhooks
  - [ ] 6.1 Create the Gmail Draft webhook workflow via n8n API
    - Workflow name: "Google - Gmail Draft"
    - Nodes: Webhook (POST, path: `gmail/draft`) → Code (validate required fields: `to`, `subject`, `body`; validate email format for `to`; return 400 with missing fields or invalid email error) → IF (valid?) → Gmail node (Create Draft, credential: Google OAuth2) → Code (format: `{draftId, to, subject, preview}` where preview = first 200 chars of body) → Respond to Webhook (200)
    - Error branches: validation fail → 400; Gmail error → 502
    - Activate the workflow
    - _Requirements: 3.1, 3.5, 3.6, 11.1, 11.4_

  - [ ] 6.2 Create the Gmail Send webhook workflow via n8n API
    - Workflow name: "Google - Gmail Send"
    - Nodes: Webhook (POST, path: `gmail/send`) → Code (check if body has `draftId` OR all of `to`, `subject`, `body`; validate accordingly) → IF (has draftId?) → Gmail node (Send Draft, credential: Google OAuth2) / Gmail node (Send Email, credential: Google OAuth2) → Code (format: `{messageId, threadId}`) → Respond to Webhook (200)
    - Error branches: validation fail → 400; Gmail error → 502
    - Activate the workflow
    - _Requirements: 3.2, 3.3, 3.5, 3.6, 11.1, 11.4_

- [ ] 7. Checkpoint — Verify Gmail webhooks
  - Test all Gmail endpoints with curl from Tailscale network: GET /webhook/gmail/inbox, GET /webhook/gmail/search?query=is:unread, GET /webhook/gmail/labels, POST /webhook/gmail/draft (with test payload). Verify error cases: missing query param returns 400, invalid email returns 400. Ask the user if questions arise.

- [ ] 8. Implement Calendar read webhooks
  - [ ] 8.1 Create the Calendar Today webhook workflow via n8n API
    - Workflow name: "Google - Calendar Today"
    - Nodes: Webhook (GET, path: `calendar/today`) → Code (compute today's start/end in America/New_York timezone) → Google Calendar node (Get Many, credential: Google OAuth2, timeMin/timeMax from code, calendar: primary) → Code (format: `{id, summary, start, end, location, description, attendees}`) → Respond to Webhook (200)
    - Error branch: standard error handler → 502
    - Activate the workflow
    - _Requirements: 4.2, 4.6, 11.1, 11.4_

  - [ ] 8.2 Create the Calendar Upcoming webhook workflow via n8n API
    - Workflow name: "Google - Calendar Upcoming"
    - Nodes: Webhook (GET, path: `calendar/upcoming`) → Code (extract `days` param, default 7, cap at 30; compute timeMin=now, timeMax=now+days) → Google Calendar node (Get Many, credential: Google OAuth2) → Code (format events) → Respond to Webhook (200)
    - Error branch: standard error handler
    - Activate the workflow
    - _Requirements: 4.3, 4.6, 11.1, 11.4_

  - [ ] 8.3 Create the Calendar Events (date range) webhook workflow via n8n API
    - Workflow name: "Google - Calendar Events"
    - Nodes: Webhook (GET, path: `calendar/events`) → Code (validate `start` and `end` params exist and start < end; return 400 if missing or invalid range) → IF (valid?) → Google Calendar node (Get Many, credential: Google OAuth2, timeMin/timeMax) → Code (format events) → Respond to Webhook (200)
    - Error branches: missing params → 400; invalid range → 400; Google error → 502
    - Activate the workflow
    - _Requirements: 4.1, 4.4, 4.5, 4.6, 11.1, 11.4_

- [ ] 9. Implement Calendar write webhooks
  - [ ] 9.1 Create the Calendar Create webhook workflow via n8n API
    - Workflow name: "Google - Calendar Create"
    - Nodes: Webhook (POST, path: `calendar/create`) → Code (validate required: `summary`, `start`, `end`; return 400 if missing) → IF (valid?) → Google Calendar node (Create Event, credential: Google OAuth2, calendar: primary, with optional location/description) → Code (format: `{id, summary, start, end, location, htmlLink}`) → Respond to Webhook (200)
    - Error branches: validation → 400; Google error → 502
    - Activate the workflow
    - _Requirements: 5.1, 5.5, 11.1, 11.4_

  - [ ] 9.2 Create the Calendar Update webhook workflow via n8n API
    - Workflow name: "Google - Calendar Update"
    - Nodes: Webhook (PATCH, path: `calendar/update/{{eventId}}`) → Google Calendar node (Update Event, credential: Google OAuth2, event ID from path, only update provided fields) → Code (format updated event) → Respond to Webhook (200)
    - Error branches: Google 404 → Respond to Webhook (404, `{"error": "Event not found: {id}"}`); other → 502
    - Activate the workflow
    - _Requirements: 5.2, 5.6, 11.1, 11.4_

  - [ ] 9.3 Create the Calendar Delete webhook workflow via n8n API
    - Workflow name: "Google - Calendar Delete"
    - Nodes: Webhook (DELETE, path: `calendar/delete/{{eventId}}`) → Google Calendar node (Delete Event, credential: Google OAuth2, event ID from path) → Code (format: `{id, summary}` confirmation) → Respond to Webhook (200)
    - Error branches: Google 404 → 404 response; other → 502
    - Activate the workflow
    - _Requirements: 5.3, 5.6, 11.1, 11.4_

- [ ] 10. Checkpoint — Verify Calendar webhooks
  - Test all Calendar endpoints with curl: GET /webhook/calendar/today, GET /webhook/calendar/upcoming?days=3, GET /webhook/calendar/events?start=2025-07-01&end=2025-07-31. Test create with a test event, then update it, then delete it. Verify error cases: missing start/end returns 400, invalid range returns 400, non-existent event returns 404. Ask the user if questions arise.

- [ ] 11. Implement Tasks webhooks
  - [ ] 11.1 Create the Tasks Lists webhook workflow via n8n API
    - Workflow name: "Google - Tasks Lists"
    - Nodes: Webhook (GET, path: `tasks/lists`) → Google Tasks node (Get All Task Lists, credential: Google OAuth2) → Code (format: `{id, title, updated}`) → Respond to Webhook (200)
    - Error branch: standard error handler
    - Activate the workflow
    - _Requirements: 6.1, 6.7, 11.1, 11.4_

  - [ ] 11.2 Create the Tasks List (get tasks) webhook workflow via n8n API
    - Workflow name: "Google - Tasks Get"
    - Nodes: Webhook (GET, path: `tasks/list/{{listId}}`) → Code (extract `showCompleted` param, default false) → Google Tasks node (Get All Tasks, credential: Google OAuth2, task list ID from path, show completed based on param) → Code (format: `{id, title, notes, due, status, completed}`) → Respond to Webhook (200)
    - Error branches: Google 404 (invalid listId) → 404; other → 502
    - Activate the workflow
    - _Requirements: 6.2, 6.7, 11.1, 11.4_

  - [ ] 11.3 Create the Tasks Create webhook workflow via n8n API
    - Workflow name: "Google - Tasks Create"
    - Nodes: Webhook (POST, path: `tasks/create`) → Code (validate `title` required; extract optional `listId`, `notes`, `due`; default listId to primary) → IF (valid?) → Google Tasks node (Create Task, credential: Google OAuth2) → Code (format: `{id, title, due, status}`) → Respond to Webhook (200)
    - Error branches: missing title → 400; Google 404 (bad listId) → 404; other → 502
    - Activate the workflow
    - _Requirements: 6.3, 6.6, 6.7, 11.1, 11.4_

  - [ ] 11.4 Create the Tasks Complete webhook workflow via n8n API
    - Workflow name: "Google - Tasks Complete"
    - Nodes: Webhook (PATCH, path: `tasks/complete/{{taskId}}`) → Code (validate `listId` query param required) → IF (valid?) → Google Tasks node (Update Task, credential: Google OAuth2, set status=completed) → Code (format updated task) → Respond to Webhook (200)
    - Error branches: missing listId → 400; Google 404 → 404; other → 502
    - Activate the workflow
    - _Requirements: 6.4, 6.7, 11.1, 11.4_

  - [ ] 11.5 Create the Tasks Delete webhook workflow via n8n API
    - Workflow name: "Google - Tasks Delete"
    - Nodes: Webhook (DELETE, path: `tasks/delete/{{taskId}}`) → Code (validate `listId` query param required) → IF (valid?) → Google Tasks node (Delete Task, credential: Google OAuth2) → Code (format: `{id, title}` confirmation) → Respond to Webhook (200)
    - Error branches: missing listId → 400; Google 404 → 404; other → 502
    - Activate the workflow
    - _Requirements: 6.5, 6.7, 11.1, 11.4_

- [ ] 12. Checkpoint — Verify Tasks webhooks
  - Test all Tasks endpoints with curl: GET /webhook/tasks/lists, GET /webhook/tasks/list/{listId}, POST /webhook/tasks/create (create a test task), PATCH /webhook/tasks/complete/{taskId}?listId=..., DELETE /webhook/tasks/delete/{taskId}?listId=.... Verify error cases: missing title returns 400, non-existent listId returns 404. Ask the user if questions arise.

- [ ] 13. Implement Contacts webhooks (optional)
  - [ ] 13.1 Create the Contacts Search webhook workflow via n8n API
    - Workflow name: "Google - Contacts Search"
    - Nodes: Webhook (GET, path: `contacts/search`) → Code (validate `query` param required; return 400 if missing) → IF (valid?) → Google People API node (Search, credential: Google OAuth2, query from param, max 20 results, fields: names, emailAddresses, phoneNumbers, organizations) → Code (format: `{name, email, phone, organization}`) → Respond to Webhook (200)
    - Error branches: missing query → 400; Google error → 502
    - Activate the workflow
    - _Requirements: 7.1, 7.3, 7.4, 7.5, 11.1, 11.4_

  - [ ] 13.2 Create the Contacts List webhook workflow via n8n API
    - Workflow name: "Google - Contacts List"
    - Nodes: Webhook (GET, path: `contacts/list`) → Code (extract `maxResults` param, default 50, cap at 200) → Google People API node (Get All, credential: Google OAuth2, sorted alphabetically, fields: names, emailAddresses, phoneNumbers, organizations) → Code (format contacts array) → Respond to Webhook (200)
    - Error branch: Google error → 502
    - Activate the workflow
    - _Requirements: 7.2, 7.4, 7.5, 11.1, 11.4_

- [ ] 14. Checkpoint — Verify Contacts webhooks
  - Test Contacts endpoints with curl: GET /webhook/contacts/search?query=John, GET /webhook/contacts/list?maxResults=5. Verify missing query returns 400. Ask the user if questions arise.

- [ ] 15. Create AnythingLLM Google Assistant workspace and system prompt
  - [ ] 15.1 Write the Google Assistant system prompt file to disk
    - Write the full system prompt to `/home/michael/finance/GOOGLE_ASSISTANT_SYSTEM_PROMPT.md`
    - Include all webhook URLs, parameters, usage instructions
    - Include write operation safety rules (confirmation pattern)
    - Include cross-reference suggestions
    - Include error handling instructions for the AI
    - Include timezone (America/New_York) and privacy notes
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.6, 8.7, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 11.5_

  - [ ] 15.2 Create the Google Assistant workspace in AnythingLLM
    - Use AnythingLLM API or UI to create workspace named "Google Assistant"
    - Set model to claude-sonnet-4-5 (Anthropic API)
    - Set temperature to 0.7
    - Paste the system prompt from the file written in 15.1
    - Configure access: Michael only (exclude Manon)
    - No document embedding needed (all data is transient via webhooks)
    - _Requirements: 8.1, 8.4, 8.5, 10.3, 10.5_

- [ ] 16. Checkpoint — Verify AnythingLLM workspace
  - Open the Google Assistant workspace in AnythingLLM. Test conversational queries: "Check my inbox", "What's on my calendar today?", "Add a task: test task". Verify the AI calls webhooks and follows confirmation patterns for write operations. Ask the user if questions arise.

- [ ] 17. End-to-end smoke testing
  - [ ] 17.1 Run the full smoke test suite via curl
    - Test each endpoint from the Tailscale network using the curl commands from the design document's testing section
    - Verify all 18 endpoints return expected HTTP status codes
    - Verify error responses follow the standard `{"error": "..."}` format
    - Verify no OAuth tokens or credentials leak in any response
    - _Requirements: 10.1, 10.2, 10.4, 11.1, 11.2, 11.3, 11.4_

  - [ ] 17.2 Verify network security
    - Confirm webhooks are NOT accessible from public internet (only Docker network and Tailscale 100.x.x.x)
    - Verify no persistent storage of Google data (n8n workflows are pass-through only)
    - _Requirements: 10.1, 10.2_

- [ ] 18. Final checkpoint — Full system validation
  - Verify all 18 webhook endpoints respond correctly. Confirm the Google Assistant workspace answers questions using live webhook data. Verify write operations follow the confirmation pattern. Confirm Manon cannot access the workspace. Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with manual steps (1.1, 3.1) require Michael to interact with Google Cloud Console and n8n UI in a browser — these cannot be automated
- All n8n workflow creation is done via the n8n REST API at `http://100.106.180.101:5678/api/v1/workflows`
- n8n API uses POST to create workflows, PUT to update (requires `name`, `nodes`, `connections`, `settings` with `executionOrder: 'v1'`)
- The Google OAuth2 credential will get a new ID once created — reference it by name in workflow nodes
- No Postgres is used in this feature — all data is transient (Google API → n8n → webhook response)
- Property-based testing does not apply (no pure functions or algorithms — this is infrastructure config and system prompt text)
- Testing is manual integration testing via curl from the Tailscale network
- Lessons from finance implementation: always apply all fixes atomically in one PUT, escape single quotes in SQL (not applicable here), use typeVersion 1 for Execute Workflow nodes
- The system prompt file is written to `/home/michael/finance/GOOGLE_ASSISTANT_SYSTEM_PROMPT.md` alongside other workspace docs
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation — especially important for the manual OAuth steps

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["3.1"] },
    { "id": 2, "tasks": ["5.1", "5.2", "5.3", "5.4"] },
    { "id": 3, "tasks": ["6.1", "6.2"] },
    { "id": 4, "tasks": ["8.1", "8.2", "8.3"] },
    { "id": 5, "tasks": ["9.1", "9.2", "9.3"] },
    { "id": 6, "tasks": ["11.1", "11.2", "11.3", "11.4", "11.5"] },
    { "id": 7, "tasks": ["13.1", "13.2"] },
    { "id": 8, "tasks": ["15.1"] },
    { "id": 9, "tasks": ["15.2"] },
    { "id": 10, "tasks": ["17.1", "17.2"] }
  ]
}
```
