# Requirements Document

## Introduction

The Google Assistant Integration connects Michael's Google account (Gmail, Calendar, Tasks, and optionally Contacts) to the 595BowersHub AI platform. Following the same webhook-first architecture proven in the Finance Workspace, n8n workflows expose Google data via HTTP endpoints, and a dedicated AnythingLLM workspace instructs the AI to call those webhooks for live data.

This feature enables the AI to read and search Gmail, manage Google Calendar events, manage Google Tasks, and optionally look up Google Contacts — all while keeping data on-prem (Google API calls go directly from n8n to Google, responses stay on the local server). Write operations (sending emails, creating events, adding tasks) require explicit user confirmation before execution to prevent accidental actions.

Access is restricted to Michael only — Manon does not have access to this workspace.

---

## Glossary

- **Google_Workspace**: The AnythingLLM workspace dedicated to Google account interactions (Gmail, Calendar, Tasks, Contacts)
- **n8n**: The workflow automation engine running at http://100.106.180.101:5678
- **AnythingLLM**: The AI chat platform running at http://100.106.180.101:3001
- **Google_OAuth2_Credential**: The n8n credential storing Google OAuth2 tokens for Michael's account, configured via the n8n UI with the appropriate redirect URI
- **Gmail_Webhook**: An n8n HTTP endpoint that retrieves or sends Gmail data
- **Calendar_Webhook**: An n8n HTTP endpoint that retrieves or modifies Google Calendar data
- **Tasks_Webhook**: An n8n HTTP endpoint that retrieves or modifies Google Tasks data
- **Contacts_Webhook**: An n8n HTTP endpoint that retrieves Google Contacts data
- **Confirmation_Pattern**: A two-step interaction where the AI presents a preview of a write action and waits for Michael's explicit approval before executing
- **Pushover**: The notification service used for alerts and confirmations on Michael's Android device
- **Tailscale**: The VPN providing secure remote access to 595BowersHub services

---

## Requirements

### Requirement 1: Google OAuth2 Credential Setup in n8n

**User Story:** As Michael, I want n8n to authenticate with my Google account using OAuth2, so that all Google API workflows can securely access my Gmail, Calendar, Tasks, and Contacts.

#### Acceptance Criteria

1. THE n8n instance SHALL support a Google_OAuth2_Credential configured via the n8n UI using the standard Google OAuth2 flow with a redirect URI pointing to the n8n instance.
2. THE Google_OAuth2_Credential SHALL request the following OAuth2 scopes: Gmail read and send, Google Calendar read and write, Google Tasks read and write, and Google Contacts read-only.
3. WHEN the Google_OAuth2_Credential token expires, THE n8n instance SHALL automatically refresh the token using the stored refresh token without manual intervention.
4. IF the token refresh fails, THEN THE n8n instance SHALL log the failure and THE affected webhook SHALL return an HTTP 401 response with a JSON body containing an `error` field indicating the Google authentication has expired.
5. THE Google_OAuth2_Credential SHALL be stored exclusively within n8n's encrypted credential storage and SHALL NOT be exposed in webhook responses or logs.

---

### Requirement 2: Gmail Read and Search Webhooks

**User Story:** As Michael, I want the AI to read and search my Gmail, so that I can ask questions about emails without opening Gmail directly.

#### Acceptance Criteria

1. WHEN the Gmail_Webhook receives a GET request at `/webhook/gmail/inbox` with an optional `maxResults` parameter (default 20, maximum 50), THE Gmail_Webhook SHALL return the most recent emails from Michael's inbox including: `id`, `from`, `to`, `subject`, `date`, `snippet`, and `labels`.
2. WHEN the Gmail_Webhook receives a GET request at `/webhook/gmail/search` with a required `query` parameter, THE Gmail_Webhook SHALL return emails matching the Gmail search query syntax (same syntax as the Gmail search bar) with a default limit of 20 results and a maximum of 50.
3. WHEN the Gmail_Webhook receives a GET request at `/webhook/gmail/message/{id}`, THE Gmail_Webhook SHALL return the full email body (plain text preferred, HTML as fallback), all headers, and attachment metadata (filename, mimeType, size) for the specified message ID.
4. WHEN the Gmail_Webhook receives a GET request at `/webhook/gmail/labels`, THE Gmail_Webhook SHALL return a list of all Gmail labels including label `id`, `name`, and `type` (system or user).
5. IF the `query` parameter is missing from a `/webhook/gmail/search` request, THEN THE Gmail_Webhook SHALL return an HTTP 400 response with a JSON body containing an `error` field indicating the query parameter is required.
6. IF the Gmail API returns an error or is unreachable, THEN THE Gmail_Webhook SHALL return an HTTP 502 response with a JSON body containing an `error` field describing the upstream failure.

---

### Requirement 3: Gmail Send Webhook with Confirmation

**User Story:** As Michael, I want the AI to draft and send emails on my behalf after I confirm, so that I can compose emails conversationally without the risk of accidental sends.

#### Acceptance Criteria

1. WHEN the Gmail_Webhook receives a POST request at `/webhook/gmail/draft` with `to`, `subject`, and `body` fields, THE Gmail_Webhook SHALL create a draft in Michael's Gmail account and return the draft `id`, `to`, `subject`, and a preview of the first 200 characters of the body.
2. WHEN the Gmail_Webhook receives a POST request at `/webhook/gmail/send` with a `draftId` field, THE Gmail_Webhook SHALL send the specified draft and return a confirmation containing the sent message `id` and `threadId`.
3. WHEN the Gmail_Webhook receives a POST request at `/webhook/gmail/send` with `to`, `subject`, and `body` fields (direct send without draft), THE Gmail_Webhook SHALL send the email and return a confirmation containing the sent message `id` and `threadId`.
4. THE Google_Workspace system prompt SHALL instruct the AI to always use the two-step Confirmation_Pattern for sending emails: first call `/webhook/gmail/draft` to create a draft, present the preview to Michael, and only call `/webhook/gmail/send` with the `draftId` after Michael explicitly confirms.
5. IF any required field (`to`, `subject`, `body`) is missing from a draft or direct send request, THEN THE Gmail_Webhook SHALL return an HTTP 400 response with a JSON body containing an `error` field listing the missing fields.
6. IF the `to` field contains an invalid email address format, THEN THE Gmail_Webhook SHALL return an HTTP 400 response with a JSON body containing an `error` field indicating the invalid address.

---

### Requirement 4: Google Calendar Read Webhooks

**User Story:** As Michael, I want the AI to read my Google Calendar, so that I can ask about upcoming events, check availability, and review my schedule conversationally.

#### Acceptance Criteria

1. WHEN the Calendar_Webhook receives a GET request at `/webhook/calendar/events` with required `start` and `end` parameters in ISO 8601 format (YYYY-MM-DDTHH:mm:ssZ or YYYY-MM-DD), THE Calendar_Webhook SHALL return all events in that time range including: `id`, `summary`, `start`, `end`, `location`, `description`, and `attendees`.
2. WHEN the Calendar_Webhook receives a GET request at `/webhook/calendar/today`, THE Calendar_Webhook SHALL return all events for the current calendar day (midnight to midnight in America/New_York timezone).
3. WHEN the Calendar_Webhook receives a GET request at `/webhook/calendar/upcoming` with an optional `days` parameter (default 7, maximum 30), THE Calendar_Webhook SHALL return all events from now through the specified number of days.
4. IF the `start` or `end` parameter is missing from a `/webhook/calendar/events` request, THEN THE Calendar_Webhook SHALL return an HTTP 400 response with a JSON body containing an `error` field indicating the missing parameter.
5. IF the `start` parameter represents a time after the `end` parameter, THEN THE Calendar_Webhook SHALL return an HTTP 400 response with a JSON body containing an `error` field indicating the invalid date range.
6. IF the Google Calendar API returns an error or is unreachable, THEN THE Calendar_Webhook SHALL return an HTTP 502 response with a JSON body containing an `error` field describing the upstream failure.

---

### Requirement 5: Google Calendar Create and Modify Webhooks with Confirmation

**User Story:** As Michael, I want the AI to create and modify calendar events after I confirm, so that I can manage my schedule conversationally without accidental changes.

#### Acceptance Criteria

1. WHEN the Calendar_Webhook receives a POST request at `/webhook/calendar/create` with required `summary`, `start`, and `end` fields and optional `location` and `description` fields, THE Calendar_Webhook SHALL create the event on Michael's primary Google Calendar and return the created event `id`, `summary`, `start`, `end`, `location`, and a `htmlLink` to the event.
2. WHEN the Calendar_Webhook receives a PATCH request at `/webhook/calendar/update/{id}` with one or more fields (`summary`, `start`, `end`, `location`, `description`), THE Calendar_Webhook SHALL update only the provided fields on the specified event and return the updated event details.
3. WHEN the Calendar_Webhook receives a DELETE request at `/webhook/calendar/delete/{id}`, THE Calendar_Webhook SHALL delete the specified event and return a confirmation with the deleted event `id` and `summary`.
4. THE Google_Workspace system prompt SHALL instruct the AI to always present a summary of the event details (summary, date, time, location) and ask Michael for explicit confirmation before calling the create, update, or delete endpoints.
5. IF any required field (`summary`, `start`, `end`) is missing from a create request, THEN THE Calendar_Webhook SHALL return an HTTP 400 response with a JSON body containing an `error` field listing the missing fields.
6. IF the specified event `id` does not exist for an update or delete request, THEN THE Calendar_Webhook SHALL return an HTTP 404 response with a JSON body containing an `error` field indicating the event was not found.

---

### Requirement 6: Google Tasks Read and Manage Webhooks

**User Story:** As Michael, I want the AI to read and manage my Google Tasks, so that I can add, complete, and review tasks conversationally.

#### Acceptance Criteria

1. WHEN the Tasks_Webhook receives a GET request at `/webhook/tasks/lists`, THE Tasks_Webhook SHALL return all of Michael's Google Task lists including `id`, `title`, and `updated` timestamp.
2. WHEN the Tasks_Webhook receives a GET request at `/webhook/tasks/list/{listId}` with an optional `showCompleted` parameter (default false), THE Tasks_Webhook SHALL return all tasks in the specified list including: `id`, `title`, `notes`, `due`, `status`, and `completed` timestamp.
3. WHEN the Tasks_Webhook receives a POST request at `/webhook/tasks/create` with required `title` field and optional `listId` (defaults to primary list), `notes`, and `due` fields, THE Tasks_Webhook SHALL create the task and return the created task `id`, `title`, `due`, and `status`.
4. WHEN the Tasks_Webhook receives a PATCH request at `/webhook/tasks/complete/{taskId}` with a required `listId` parameter, THE Tasks_Webhook SHALL mark the specified task as completed and return the updated task details.
5. WHEN the Tasks_Webhook receives a DELETE request at `/webhook/tasks/delete/{taskId}` with a required `listId` parameter, THE Tasks_Webhook SHALL delete the specified task and return a confirmation with the deleted task `id` and `title`.
6. IF the `title` field is missing from a create request, THEN THE Tasks_Webhook SHALL return an HTTP 400 response with a JSON body containing an `error` field indicating the title is required.
7. IF the specified `listId` or `taskId` does not exist, THEN THE Tasks_Webhook SHALL return an HTTP 404 response with a JSON body containing an `error` field indicating the resource was not found.
8. THE Google_Workspace system prompt SHALL instruct the AI to confirm with Michael before deleting tasks, but allow creating and completing tasks without confirmation since these are low-risk actions.

---

### Requirement 7: Google Contacts Read Webhook (Optional)

**User Story:** As Michael, I want the AI to look up contacts from my Google account, so that it can auto-fill email addresses and provide context about people mentioned in emails or calendar events.

#### Acceptance Criteria

1. WHEN the Contacts_Webhook receives a GET request at `/webhook/contacts/search` with a required `query` parameter, THE Contacts_Webhook SHALL return matching contacts including: `name`, `email`, `phone`, and `organization` fields, with a maximum of 20 results.
2. WHEN the Contacts_Webhook receives a GET request at `/webhook/contacts/list` with an optional `maxResults` parameter (default 50, maximum 200), THE Contacts_Webhook SHALL return contacts sorted alphabetically by name.
3. IF the `query` parameter is missing from a search request, THEN THE Contacts_Webhook SHALL return an HTTP 400 response with a JSON body containing an `error` field indicating the query parameter is required.
4. THE Contacts_Webhook SHALL only support read operations — no contact creation, modification, or deletion is permitted through the webhook.
5. IF the Google People API returns an error or is unreachable, THEN THE Contacts_Webhook SHALL return an HTTP 502 response with a JSON body containing an `error` field describing the upstream failure.

---

### Requirement 8: Google Workspace AnythingLLM Configuration

**User Story:** As Michael, I want a dedicated AnythingLLM workspace for Google account interactions, so that the AI knows which webhooks to call and follows safety rules for write operations.

#### Acceptance Criteria

1. THE Google_Workspace SHALL be created as a new workspace in AnythingLLM named "Google Assistant" with a system prompt that lists all available Google webhooks, their parameters, and usage instructions.
2. THE Google_Workspace system prompt SHALL instruct the AI to always call the appropriate webhook before answering questions about emails, calendar, tasks, or contacts — the AI SHALL NOT guess or fabricate data.
3. THE Google_Workspace system prompt SHALL instruct the AI to use the Confirmation_Pattern (preview then confirm) for all write operations: sending emails, creating/updating/deleting calendar events, and deleting tasks.
4. THE Google_Workspace system prompt SHALL instruct the AI to use Sonnet as the default model for conversational responses and multi-step operations.
5. THE Google_Workspace SHALL be configured with access restricted to Michael's user account only — Manon SHALL NOT have access to this workspace.
6. THE Google_Workspace system prompt SHALL include instructions for the AI to suggest relevant cross-references (e.g., when discussing a calendar event, offer to look up the attendee's contact info or related emails).
7. IF a webhook returns an error, THE Google_Workspace system prompt SHALL instruct the AI to inform Michael which specific endpoint failed and suggest checking the n8n service at http://100.106.180.101:5678.

---

### Requirement 9: Write Operation Safety and Confirmation

**User Story:** As Michael, I want all destructive or outbound actions to require my explicit confirmation, so that the AI cannot accidentally send emails, modify my calendar, or delete tasks without my approval.

#### Acceptance Criteria

1. THE Google_Workspace system prompt SHALL classify the following as write operations requiring confirmation: sending emails, creating calendar events, updating calendar events, deleting calendar events, and deleting tasks.
2. THE Google_Workspace system prompt SHALL classify the following as low-risk write operations that do NOT require confirmation: creating tasks and completing tasks.
3. WHEN the AI prepares a write operation requiring confirmation, THE Google_Workspace system prompt SHALL instruct the AI to present a clear summary of the action (recipient, subject, date, time, or task details) and explicitly ask "Should I go ahead?" before executing.
4. WHEN Michael confirms a write operation, THE Google_Workspace system prompt SHALL instruct the AI to execute the action immediately and report the result.
5. WHEN Michael declines or modifies a write operation, THE Google_Workspace system prompt SHALL instruct the AI to either cancel the action or present an updated preview incorporating the changes.
6. IF a write operation webhook returns an error after confirmation, THEN THE Google_Workspace system prompt SHALL instruct the AI to inform Michael that the action failed, include the error details, and suggest retrying or checking n8n.

---

### Requirement 10: Privacy and Access Control

**User Story:** As Michael, I want my Google account data to remain private and on-prem, so that sensitive emails, calendar events, and contacts are never exposed to unauthorized users or external services.

#### Acceptance Criteria

1. THE Google_Workspace webhooks SHALL only be accessible from the local Docker network and Tailscale network (100.x.x.x range) — the webhooks SHALL NOT be exposed to the public internet.
2. THE n8n workflows for Google integration SHALL NOT store email bodies, calendar event details, or contact information in any persistent database or file on disk — data SHALL only pass through n8n in transit from Google API to the webhook response.
3. THE Google_Workspace in AnythingLLM SHALL be configured so that only Michael's user account has access — Manon's account SHALL NOT be able to view or interact with this workspace.
4. THE n8n webhook responses SHALL NOT include the Google_OAuth2_Credential tokens, refresh tokens, or any authentication material in their response bodies.
5. WHEN the AI processes Google data in the Google_Workspace, THE AnythingLLM instance SHALL NOT embed or persist email content, calendar details, or contact information in its vector database — all Google data SHALL be treated as transient per-request data.

---

### Requirement 11: Error Handling and Resilience

**User Story:** As Michael, I want clear error messages when Google services are unavailable, so that I know what went wrong and how to fix it.

#### Acceptance Criteria

1. IF the Google API returns a rate limit error (HTTP 429), THEN THE affected webhook SHALL return an HTTP 429 response with a JSON body containing an `error` field indicating the rate limit and a `retryAfter` field with the suggested wait time in seconds.
2. IF the Google_OAuth2_Credential refresh fails, THEN THE affected webhook SHALL return an HTTP 401 response with a JSON body containing an `error` field instructing Michael to re-authenticate via the n8n UI at http://100.106.180.101:5678.
3. IF a webhook receives a request with an invalid or unrecognized path, THEN THE n8n instance SHALL return an HTTP 404 response with a JSON body containing an `error` field indicating the endpoint does not exist.
4. WHEN any Google webhook encounters an unexpected error, THE webhook SHALL return an HTTP 500 response with a JSON body containing an `error` field with a human-readable description and SHALL NOT expose stack traces or internal implementation details.
5. THE Google_Workspace system prompt SHALL instruct the AI to present error messages to Michael in plain language, translating technical error codes into actionable suggestions (e.g., "Your Google connection needs to be refreshed — open n8n and re-authorize the Google credential").
