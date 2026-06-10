# Proactive Assistant — Requirements

## Overview
Transform BowersHub AI from a reactive chat tool into a proactive personal assistant that surfaces relevant information without being asked, supports voice input on mobile, and delivers a daily morning briefing via push notification.

## Feature 1: Morning Briefing

### R1.1 — Scheduled daily briefing
The system generates a personalized morning briefing at a configurable time (default 7:00 AM Eastern) via apscheduler. No user action required.

### R1.2 — Briefing content
The briefing assembles data from available sources:
- Yesterday's spending total + any budget alerts approaching threshold
- Today's weather forecast (from native weather skill)
- Sports: any games today for teams the user cares about (Tigers, Lions, Red Wings, Pistons, USMNT)
- Inbox status: unread email count, any files in /files/inbox/ pending processing
- Knowledge reminder: surface one random fact from the knowledge base the user might find relevant (rotated daily)
- Today's schedule (once calendar is integrated — placeholder for now)

### R1.3 — Delivery via Pushover
The briefing is sent as a Pushover notification with a title and condensed body. Tapping the notification opens BowersHub AI to a dedicated "Briefing" conversation in the General workspace.

### R1.4 — Briefing message in chat
The full formatted briefing is also posted as an assistant message in a dedicated "Daily Briefing" conversation in the General workspace, creating a persistent log of every morning's brief.

### R1.5 — Configurable
User can enable/disable the briefing, change the delivery time, and select which sections to include, via Settings or a `/briefing` slash command.

## Feature 2: Proactive Alerts

### R2.1 — Budget threshold alerts
When the categorizer or any spending-related query detects a category has hit 80% or 100% of its monthly budget, send a Pushover notification immediately (debounced to once per budget per day).

### R2.2 — Upcoming game alerts
At a configurable time before game start (default 90 minutes), send a notification for tracked teams.

### R2.3 — Inbox activity alerts
When new files appear in /files/inbox/ (checked every 30 minutes), notify if count exceeds a threshold (default: 5 unprocessed).

### R2.4 — Reminders
When the user says "remind me in 2 hours to..." or "remind me tomorrow to...", the system stores a timed reminder and delivers it via Pushover at the specified time.

## Feature 3: Voice Input

### R3.1 — Microphone button in InputArea
A microphone icon button is added to the chat input bar (next to the send button). Tapping it starts Web Speech API recognition.

### R3.2 — Speech-to-text via browser
Uses the browser's built-in SpeechRecognition API (free, works on Android Chrome, desktop Chrome, Safari). No server-side transcription needed.

### R3.3 — Continuous recognition mode
While recording, the transcript populates the input field in real-time. The user can see what's being captured. Speaking pauses (>1.5s silence) auto-submit the message (configurable: auto-send or manual-send mode).

### R3.4 — Visual feedback
The mic button changes appearance while recording (red dot or pulsing animation). The input field shows "Listening..." placeholder when empty and recording.

### R3.5 — Graceful degradation
If SpeechRecognition is not supported (Firefox, older browsers), the mic button is hidden. No errors.

### R3.6 — Settings toggle
Voice input can be disabled in Settings → Voice section. Default: enabled.
