# Requirements Document

## Introduction

This feature extends the existing BowersHub AI platform (custom-chat-app spec) with four bundles of enhancements: admin-controlled branding (theme colors and app icon), per-user appearance preferences (theme and text size), workspace system-prompt viewing/editing, and a curated set of creative day-to-day features chosen to compound with existing infrastructure rather than introduce greenfield systems. Branding assets are stored on disk and managed through admin endpoints so visual identity changes do not require a code redeploy. User preferences persist server-side per account so they follow the user across devices when they sign into the PWA. Workspace system prompts are edited as raw markdown and rendered as human-readable content in-app, making the prompt that drives each workspace's behavior fully transparent and modifiable. The creative features — proactive morning card, pinned-context viewer/editor, quick capture overlay, voice mode, and scheduled prompts UI — were selected because each one builds directly on a service that already exists in the platform (briefing service, pinned context API, smart-capture skill, browser Web Speech APIs, hook engine).

This spec replaces three open BowersHub AI quality-of-life TODOs that overlap with the requested scope: TODO #32 (pinned-context viewer), TODO #34 (more slash commands — folded into scheduled prompts and quick capture), and TODO #37 (settings page write features — folded into per-user theme and text size).

## Glossary

- **BowersHub_AI**: The existing self-hosted personal AI assistant platform — FastAPI backend on port 5003 plus React PWA frontend, deployed as a single Docker container, accessed at `http://100.106.180.101:5003` (HTTP) and `https://595bowershub.tailc4d58a.ts.net` (HTTPS via Caddy). Defined in the `custom-chat-app` spec.
- **Admin**: A user with role `admin` in the `bh_users` table. The current sole admin is Michael.
- **User**: Any authenticated account in `bh_users`, including admins and members.
- **Theme**: A named palette of color tokens (background, surface, primary, accent, text, border, muted) that drives the UI's visual appearance.
- **Preset_Theme**: A theme defined by the platform and shipped in code. Preset themes cannot be deleted by users.
- **Custom_Theme**: A theme created by a user or admin through the theme builder. Stored in the database with an `owner_id` (admin-published themes use `owner_id = NULL` to indicate "available to all users").
- **Active_Theme**: The theme currently rendered in a given user's UI session, resolved from (in priority order) user override → admin default → built-in fallback.
- **App_Icon**: The PNG icon shown in the PWA manifest, browser favicon, and Android/iOS home-screen install. Stored on disk under `/files/branding/` inside the container, served at a stable URL.
- **Text_Size**: A user preference selecting the base font size scale for chat content, with values `small`, `medium` (default), `large`, and `extra_large` mapping to fixed CSS rem multipliers.
- **Workspace_System_Prompt**: The text in `bh_workspaces.system_prompt` that the Router prepends to every Layer 3 request in that workspace. Authored as markdown.
- **Pinned_Context**: The per-workspace static and dynamic context entries in `bh_pinned_context` (defined in the custom-chat-app spec, R15) that are always included in every AI request within that workspace.
- **Morning_Card**: A first-render card displayed at the top of a designated workspace's chat view that shows the most recent daily briefing output produced by the existing briefing service (R16 in custom-chat-app), formatted for visual scanning.
- **Quick_Capture**: A lightweight always-available capture interface — global keyboard shortcut on desktop and PWA share-target on mobile — that accepts a single short text or image input, sends it through the existing `smart-capture` skill pipeline, and confirms the result without requiring the user to navigate into the full chat UI.
- **Voice_Mode**: An interaction mode that uses the browser Web Speech API for speech-to-text (STT) input and the browser SpeechSynthesis API for text-to-speech (TTS) output of assistant responses, all running in-browser without sending audio to external services.
- **Scheduled_Prompt**: A user-defined recurring AI task with a name, cron expression, target workspace, prompt template, and result-delivery method (in-app pinned message or Pushover notification). Implemented as a row in the existing `bh_hooks` table with `event_type = 'schedule'` and `action_type = 'call_ai'`.
- **Branding_Asset_Store**: The on-disk directory `/files/branding/` (mounted from `/home/michael/files/branding/` on the host) where the active app icon and any uploaded brand assets are stored.

## Requirements

### Requirement 1: Admin Theme Color Management

**User Story:** As the admin, I want to manage the set of theme color palettes available to the platform, including built-in presets and custom-built palettes, so that the visual identity reflects my preferences without redeploying code.

#### Acceptance Criteria

1. THE BowersHub_AI SHALL ship with at least 4 Preset_Themes covering both dark and light modes: `Dark Navy` (current default), `Light Stone`, `Forest`, and `Mono`.
2. WHEN the admin opens the theme management page, THE BowersHub_AI SHALL list all Preset_Themes and all admin-published Custom_Themes with their names, color swatches, and a preview button.
3. WHEN the admin selects a theme and clicks "Set as platform default", THE BowersHub_AI SHALL persist that theme's identifier as the platform default in a settings table and apply it to all users who have not set a personal theme override.
4. WHEN the admin opens the custom theme builder, THE BowersHub_AI SHALL provide color pickers for each token (background, surface, primary, accent, text, text_muted, border, danger, success) with a live preview of a sample chat message and sidebar.
5. WHEN the admin saves a Custom_Theme, THE BowersHub_AI SHALL store the theme in the `bh_themes` table with `owner_id = NULL` to mark it as available to all users.
6. THE BowersHub_AI SHALL validate every color token in a Custom_Theme as a 6-digit or 8-digit hex string before saving, rejecting invalid values with a per-field error message.
7. IF a contrast ratio between the `text` token and the `background` token of a Custom_Theme is at or above 2.0:1 but below 4.5:1, THEN THE BowersHub_AI SHALL display a warning indicating the theme may be hard to read and SHALL allow the admin to save it.
8. IF a contrast ratio between the `text` token and the `background` token of a Custom_Theme is below 2.0:1, THEN THE BowersHub_AI SHALL block saving and display an error indicating the contrast is unusable.
9. WHEN the admin deletes a Custom_Theme that is currently set as a user's override or as the platform default, THE BowersHub_AI SHALL revert affected users to the platform default or the built-in `Dark Navy` Preset_Theme respectively.
10. WHERE a non-admin user attempts to call any theme management endpoint with create/update/delete intent, THE BowersHub_AI SHALL return HTTP 403.

### Requirement 2: Admin App Icon Management

**User Story:** As the admin, I want to upload and manage the app icon (PWA install icon, favicon, and maskable variant), so that I can change the brand identity without rebuilding the container.

#### Acceptance Criteria

1. WHEN the admin opens the icon management page, THE BowersHub_AI SHALL display the currently active App_Icon at 192px and 512px sizes alongside an "Upload new icon" control.
2. WHEN the admin uploads a square PNG of at least 512x512 pixels, THE BowersHub_AI SHALL store it in the Branding_Asset_Store, generate the 192px and maskable-512px variants automatically using Pillow, and replace the active App_Icon set.
3. THE BowersHub_AI SHALL validate uploaded icons for: MIME type `image/png`, square aspect ratio (within 1% tolerance), minimum dimension 512x512, and maximum file size 4 MB, rejecting invalid uploads with a descriptive error.
4. WHEN the App_Icon is updated, THE BowersHub_AI SHALL update the manifest.json icon paths to include a versioned query string (e.g., `?v=<timestamp>`) so installed PWAs and browsers re-fetch the new icon on next load.
5. THE BowersHub_AI SHALL serve the active App_Icon variants at stable paths under `/icons/` regardless of the underlying filename, so that manifest references and HTML `<link rel="icon">` tags do not change.
6. WHEN the admin clicks "Revert to default", THE BowersHub_AI SHALL restore the built-in icon set generated by `scripts/generate_icons.py` and update the manifest version string.
7. THE BowersHub_AI SHALL store the previous App_Icon set as a single rollback slot, allowing the admin to undo the most recent icon change with one click.
8. WHERE a user does not hold an icon-management permission (admin role or an explicit grant), THE BowersHub_AI SHALL return HTTP 403 from any icon upload, revert, or rollback endpoint.

### Requirement 3: Per-User Theme Selection

**User Story:** As a user, I want to choose my own theme from the available presets and custom themes (or build my own), so that the app looks the way I want on every device I sign into.

#### Acceptance Criteria

1. WHEN the user opens the Appearance section of Settings, THE BowersHub_AI SHALL display all Preset_Themes, all admin-published Custom_Themes, and any Custom_Themes owned by the user, with the current Active_Theme highlighted.
2. WHEN the user selects a theme, THE BowersHub_AI SHALL persist the selection in `bh_users.settings_json` under the key `theme_id`, and SHALL apply the new theme to the UI without a page reload as soon as the persistence call returns.
3. WHEN the user clicks "Use platform default", THE BowersHub_AI SHALL clear the user's theme override so that subsequent sessions render the admin-configured platform default.
4. WHEN the user opens the personal theme builder, THE BowersHub_AI SHALL provide the same color picker interface defined in Requirement 1.4, with a "Save personal theme" action that stores the theme in `bh_themes` with `owner_id = <user_id>`.
5. THE BowersHub_AI SHALL prevent any user from seeing or selecting Custom_Themes whose `owner_id` is set to a different user's id.
6. WHEN the user signs into the PWA on any device, THE BowersHub_AI SHALL apply the user's persisted theme selection on the first render after authentication, before any chat content is fetched.
7. THE BowersHub_AI SHALL resolve the Active_Theme using the priority order: user override (`bh_users.settings_json.theme_id`) → platform default (admin setting) → built-in `Dark Navy` Preset_Theme.
8. IF the user's selected theme is deleted or made unavailable, THEN THE BowersHub_AI SHALL fall back to the next item in the priority order and display a one-time toast informing the user that their theme was reset.

### Requirement 4: Per-User Text Size Preference

**User Story:** As a user, I want to choose a comfortable text size for chat content, so that I can read messages without straining on small phone screens or large desktop monitors.

#### Acceptance Criteria

1. THE BowersHub_AI SHALL support exactly four Text_Size values: `small` (0.875x base), `medium` (1.0x base, default), `large` (1.125x base), and `extra_large` (1.25x base).
2. WHEN the user opens the Appearance section of Settings, THE BowersHub_AI SHALL display the four Text_Size options as labeled buttons with each label rendered at its corresponding size as a live preview.
3. WHEN the user selects a Text_Size, THE BowersHub_AI SHALL persist the selection in `bh_users.settings_json` under the key `text_size` and apply the change to chat messages, code blocks, and rendered markdown without requiring the user to navigate away from Settings.
4. THE Text_Size preference SHALL apply only to chat content (user messages, assistant messages, code blocks, markdown rendering), not to UI chrome (sidebar, headers, buttons), so that the layout remains consistent.
5. WHEN the user signs into the PWA on a new device, THE BowersHub_AI SHALL apply the user's persisted Text_Size before the first chat message renders.
6. IF `bh_users.settings_json.text_size` is missing or contains an unrecognized value, THEN THE BowersHub_AI SHALL apply `medium` and SHALL NOT raise an error.

### Requirement 5: Workspace System Prompt Viewer

**User Story:** As an admin or workspace owner, I want to see the current system prompt for any workspace I have access to, rendered as readable markdown, so that I understand exactly what context is driving the AI's behavior in that workspace.

#### Acceptance Criteria

1. WHEN an admin opens the Workspace settings panel for any workspace, THE BowersHub_AI SHALL display the current `bh_workspaces.system_prompt` value rendered as markdown in a read-only viewer.
2. WHEN a non-admin workspace member opens the Workspace settings panel for a workspace they have access to, THE BowersHub_AI SHALL display the rendered system prompt in read-only mode without any edit controls.
3. THE rendered system prompt viewer SHALL support standard markdown features: headers, bold, italic, lists, code blocks with syntax highlighting, inline code, blockquotes, and tables.
4. WHEN the system prompt is empty, THE BowersHub_AI SHALL display the placeholder text "No system prompt set for this workspace" instead of rendering an empty area.
5. THE BowersHub_AI SHALL display the character count and approximate token count (using a 4-characters-per-token heuristic) below the rendered viewer.
6. WHERE a user attempts to view a workspace they are not assigned to, THE BowersHub_AI SHALL return HTTP 403 from the underlying API and the UI SHALL not render the panel.

### Requirement 6: Workspace System Prompt Editor

**User Story:** As an admin, I want to edit any workspace's system prompt as raw markdown in-app, with a live preview, so that I can refine workspace behavior without touching SQL or redeploying.

#### Acceptance Criteria

1. WHEN the admin clicks "Edit prompt" in the Workspace settings panel, THE BowersHub_AI SHALL replace the read-only viewer with a side-by-side or tabbed layout showing a raw markdown text editor on one side and the rendered preview on the other.
2. THE markdown text editor SHALL support: monospace font, line numbers, soft wrap, and at minimum tab/shift-tab indentation.
3. WHEN the admin types in the editor, THE BowersHub_AI SHALL update the rendered preview within 300ms (debounced) without sending a request to the server.
4. WHEN the admin clicks "Save", THE BowersHub_AI SHALL persist the new value to `bh_workspaces.system_prompt` via a PATCH request, write a record to `bh_audit_log` indicating the workspace was modified, and display a success toast.
5. WHEN the admin clicks "Cancel" with unsaved changes, THE BowersHub_AI SHALL prompt for confirmation before discarding the changes.
6. THE BowersHub_AI SHALL reject save requests with a system prompt longer than 50,000 characters and SHALL display a length-limit error in the editor.
7. AFTER a successful save, THE Router_Engine in the BowersHub_AI SHALL use the new system prompt for the next message sent in that workspace, without requiring a container restart.
8. WHERE a non-admin user attempts to call the workspace update endpoint with a `system_prompt` field, THE BowersHub_AI SHALL return HTTP 403.

### Requirement 7: Pinned Context Viewer and Editor

**User Story:** As a user (admin or member with workspace access), I want to see and edit the pinned context entries that are loaded into every AI request for a workspace, so that I understand what background information the AI always has and can adjust it.

#### Acceptance Criteria

1. WHEN a user opens the Workspace settings panel for a workspace they have access to, THE BowersHub_AI SHALL display all entries in `bh_pinned_context` for that workspace as a list, showing each entry's title, type (`static` or `dynamic`), priority, token estimate, and last refresh timestamp (for dynamic entries).
2. WHEN the user clicks an entry's title, THE BowersHub_AI SHALL expand it to show the full content (for `static` entries) or the SQL query and most recent cached result (for `dynamic` entries).
3. WHEN an admin clicks "Add entry", THE BowersHub_AI SHALL display a form that captures: title, type (static/dynamic), content or SQL query, priority (integer), and refresh interval in minutes (dynamic only).
4. WHEN the admin saves a new pinned context entry, THE BowersHub_AI SHALL POST to the existing pinned-context endpoint defined in the custom-chat-app spec (R15) and refresh the list.
5. WHEN the admin clicks "Edit" on an entry, THE BowersHub_AI SHALL allow editing of all fields and PATCH the changes via the existing endpoint.
6. WHEN the admin clicks "Delete" on an entry, THE BowersHub_AI SHALL prompt for confirmation and DELETE the entry via the existing endpoint.
7. WHEN the admin clicks "Refresh now" on a `dynamic` entry, THE BowersHub_AI SHALL re-execute the query immediately, update `cached_result` and `cached_at`, and display the new result inline.
8. THE pinned context list SHALL display a running total of the estimated token usage across all entries with a visual warning when the total exceeds 75% of the workspace's pinned-context budget (default 2000 tokens per R15.3).
9. WHERE a non-admin user attempts to add, edit, delete, or refresh pinned context, THE BowersHub_AI SHALL return HTTP 403.

### Requirement 8: Proactive Morning Card

**User Story:** As a user, I want to see the most recent daily briefing as a visual card at the top of my home workspace when I open the app each morning, so that I get the day's important information without typing anything.

#### Acceptance Criteria

1. WHEN the user opens the BowersHub_AI to the workspace configured as their morning-card workspace (defaults to `General`), THE BowersHub_AI SHALL display the most recent briefing system message generated within the last 24 hours as a Morning_Card pinned at the top of the chat area.
2. THE Morning_Card SHALL render the briefing content as parsed sections rather than plain text: weather block, spending block, inbox block, schedule block, and "anything else" block, each with an icon and section header.
3. WHEN no briefing has been generated within the last 24 hours, THE BowersHub_AI SHALL display a Morning_Card with a "Generate today's briefing" button instead of stale content.
4. WHEN the user clicks "Generate today's briefing", THE BowersHub_AI SHALL invoke the existing briefing service on demand and replace the placeholder with the generated card once complete.
5. WHEN the user dismisses the Morning_Card with the close button, THE BowersHub_AI SHALL hide it for the remainder of the calendar day on that browser, persisting the dismissal in localStorage.
6. WHEN the user opens the app on a new calendar day, THE BowersHub_AI SHALL show the Morning_Card again unless dismissed for the new day.
7. WHERE the briefing data includes a section that returned no data (e.g., weather skill failed), THE Morning_Card SHALL render that section with a muted "—" placeholder rather than omitting the section entirely.
8. WHEN the user opens any workspace that is not the morning-card workspace, THE BowersHub_AI SHALL NOT display the Morning_Card.
9. THE user SHALL be able to change the morning-card workspace in Settings, choosing any workspace they have access to or selecting "Disable" to suppress the card platform-wide.

### Requirement 9: Quick Capture Overlay

**User Story:** As a user, I want a fast always-available way to capture a thought, photo, or note without opening the full chat — by hotkey on desktop or share-target on my phone — so that capturing daily inputs becomes friction-free.

#### Acceptance Criteria

1. WHEN the user presses Ctrl+Shift+K (or Cmd+Shift+K on macOS) anywhere in the BowersHub_AI app, THE BowersHub_AI SHALL display a Quick_Capture overlay centered on the screen with a single multi-line text input, an optional image attach button, and Save/Cancel buttons.
2. WHEN the user types text and clicks Save, THE BowersHub_AI SHALL POST the text to the existing `smart-capture` skill webhook (`/webhook/smart-capture/extract`) and display a confirmation showing the extracted intents.
3. WHEN the user attaches an image and clicks Save, THE BowersHub_AI SHALL upload the image via the existing files endpoint, then call `smart-capture/extract` with the resulting `image_path`, and display the extracted intents.
4. WHEN the user reviews the extracted intents and clicks "Confirm", THE BowersHub_AI SHALL call `smart-capture/commit` for each accepted intent and display a single success toast summarizing what was saved (e.g., "Saved 1 knowledge note, 1 shopping list item").
5. WHEN the user clicks "Cancel" or presses Escape, THE BowersHub_AI SHALL close the overlay without saving anything and SHALL NOT call any backend endpoints.
6. THE BowersHub_AI manifest.json SHALL declare a Web Share Target with `action: "/quick-capture"` and `params: {title, text, files}`, so that on Android the BowersHub_AI app appears in the system share sheet.
7. WHEN the user shares text or an image to BowersHub_AI from another Android app, THE BowersHub_AI SHALL open the Quick_Capture overlay pre-populated with the shared content and proceed through the same extract/confirm/commit flow.
8. THE Quick_Capture overlay SHALL operate within the user's current workspace context — captures inherit the workspace's permitted skills and target the workspace's domain conventions.
9. IF the smart-capture extract call fails, THEN THE BowersHub_AI SHALL display a clear error message in the overlay and offer "Retry" and "Save as raw note" actions, where "Save as raw note" appends the input verbatim to `/knowledge/captures/<slug>.md`.

### Requirement 10: Voice Mode

**User Story:** As a user, I want to talk to BowersHub AI hands-free in the woodshop or kitchen — speaking my message and hearing the response read aloud — so that the tool works while my hands are dirty.

#### Acceptance Criteria

1. THE BowersHub_AI SHALL provide a microphone button in the chat input area that, when clicked, activates Voice_Mode for input.
2. WHEN Voice_Mode input is active, THE BowersHub_AI SHALL use the browser Web Speech API (`SpeechRecognition`) to transcribe the user's speech to text in real time, displaying the partial transcription in the chat input field.
3. WHEN the user pauses speaking for 2 seconds (configurable in Settings), THE BowersHub_AI SHALL finalize the transcription and submit the message automatically, unless the user has selected "Manual send" in Voice_Mode preferences.
4. WHEN Voice_Mode output is enabled, THE BowersHub_AI SHALL use the browser SpeechSynthesis API to read each assistant response aloud as it streams in, using the user's preferred voice and speech rate from Settings.
5. THE Voice_Mode output SHALL skip code blocks, tables, and inline images when reading aloud, replacing them with brief verbal placeholders ("code block omitted", "table omitted").
6. WHEN the user clicks the microphone button while Voice_Mode is active, THE BowersHub_AI SHALL stop listening and finalize whatever has been transcribed so far without auto-submitting.
7. THE BowersHub_AI SHALL provide a stop-speaking button that immediately halts TTS output mid-sentence.
8. IF the browser does not support the Web Speech API, THEN THE BowersHub_AI SHALL hide the microphone button and display a one-time toast explaining that voice input is unavailable in this browser.
9. THE BowersHub_AI SHALL persist the user's Voice_Mode preferences (output enabled/disabled, voice name, speech rate, auto-submit pause threshold) in `bh_users.settings_json`.
10. THE BowersHub_AI SHALL NOT transmit any audio data to the backend or to any third-party service — all STT and TTS happen in-browser.

### Requirement 11: Scheduled Prompts UI

**User Story:** As a user, I want to set up recurring AI tasks like "every Sunday at 8am, summarize my week's spending and put it in a pinned message", so that the AI proactively delivers value without me asking each time.

#### Acceptance Criteria

1. WHEN the user opens the Scheduled Prompts page, THE BowersHub_AI SHALL list all `bh_hooks` rows where `event_type = 'schedule'` and `action_type = 'call_ai'` that are scoped to workspaces the user has access to, showing each entry's name, schedule (human-readable cron), target workspace, and enabled state.
2. WHEN the user clicks "New scheduled prompt", THE BowersHub_AI SHALL display a form that captures: name, target workspace (limited to those the user has access to), prompt template text, schedule (with both a cron expression input and a friendly preset picker for "every day at X", "weekly on Y at X", "monthly on day Z at X"), and delivery method (`pin in workspace` or `Pushover`).
3. WHEN the user saves a new scheduled prompt, THE BowersHub_AI SHALL create a `bh_hooks` row with `event_type = 'schedule'`, `action_type = 'call_ai'`, the chosen `cron_expression`, and `action_config` containing the prompt template and delivery method.
4. WHEN a scheduled prompt fires at its cron time, THE Hook_Engine in the BowersHub_AI SHALL invoke the AI with the prompt template and the workspace's normal context (system prompt, pinned context, recent messages), then deliver the result via the configured method.
5. WHEN the delivery method is `pin in workspace`, THE BowersHub_AI SHALL insert the AI response as a system message in the workspace's primary conversation with `metadata.pinned = true` and `metadata.scheduled_prompt_id = <hook_id>`.
6. WHEN the delivery method is `Pushover`, THE BowersHub_AI SHALL send the AI response as a Pushover notification using the existing notification service, truncating to 1000 characters with a "view full response" link to the workspace.
7. WHEN the user clicks "Edit" on a scheduled prompt, THE BowersHub_AI SHALL allow modification of all fields and PATCH the underlying hook row.
8. WHEN the user clicks "Disable" on a scheduled prompt, THE BowersHub_AI SHALL set `is_enabled = false` on the hook row, causing the Hook_Engine scheduler to skip future executions.
9. WHEN the user clicks "Run now" on a scheduled prompt, THE BowersHub_AI SHALL trigger an immediate execution of that prompt outside its normal schedule and report the result in the UI.
10. THE BowersHub_AI SHALL display the last 10 execution log entries (from `bh_hook_log`) for each scheduled prompt, showing timestamp, success state, and a snippet of the response or error.
11. THE BowersHub_AI SHALL validate every cron expression on save, rejecting invalid syntax with a descriptive error and a link to cron-expression help.
12. IF the AI invocation fails when a scheduled prompt fires, THEN THE Hook_Engine SHALL log the failure to `bh_hook_log` with the error message, SHALL NOT retry automatically, and SHALL surface the failure in the next-fire log entry shown in the UI.

### Requirement 12: Settings Navigation Consolidation

**User Story:** As a user, I want all my preferences and the admin tools (when I have admin access) to be findable in one consistent Settings area, so that I don't hunt through three different menus to change my theme, my text size, my voice preferences, and my scheduled prompts.

#### Acceptance Criteria

1. THE BowersHub_AI Settings page SHALL contain the following sections, in order: Profile, Appearance, Voice, Notifications, Briefing, Context Capture, Scheduled Prompts.
2. THE Appearance section SHALL contain theme selection (Requirement 3), text size selection (Requirement 4), and a "Build a custom theme" button that opens the personal theme builder.
3. THE Voice section SHALL contain Voice_Mode preferences as defined in Requirement 10.9.
4. THE Scheduled Prompts section SHALL link to the Scheduled Prompts page defined in Requirement 11.
5. WHERE the user has admin role, THE BowersHub_AI SHALL display an additional "Admin" entry in the Settings navigation that opens the Admin Console.
6. THE Admin Console SHALL contain at minimum: Theme Management (Requirement 1), Icon Management (Requirement 2), and the existing Admin Panel sections (Users, Skills, Hooks, Cost, Workspaces) defined in the custom-chat-app spec (R29).
7. IF the user is not authenticated, THEN THE BowersHub_AI SHALL redirect any Settings or Admin route to the login page before evaluating role-based access.
