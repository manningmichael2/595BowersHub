# Proactive Assistant — Tasks

## Task 1: Pushover notification service
- [ ] Create `backend/services/pushover.py` with `send_notification(title, message, priority=0, url=None)` function
- [ ] Uses httpx to POST to Pushover API
- [ ] Reads PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN from env
- [ ] Gracefully no-ops if credentials are missing (logs warning, doesn't crash)
- [ ] Add PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN to `.env.example`

## Task 2: Morning briefing service
- [ ] Extend `backend/services/briefing.py` with `generate_and_deliver_briefing()` 
- [ ] Gather: yesterday spending (direct Postgres), weather (native skill), sports (ESPN for tracked teams), inbox file count, random knowledge fact
- [ ] Format as clean markdown with sections
- [ ] Post as assistant message to a "Daily Briefing" conversation (create if not exists) in General workspace
- [ ] Send condensed version via Pushover
- [ ] Register in apscheduler in `main.py` at configurable time (default 7:00 AM)

## Task 3: Database migration for reminders
- [ ] Create `backend/migrations/010_reminders_and_briefing.sql`
- [ ] Table: `bh_reminders (id SERIAL PK, user_id INT FK, message TEXT, deliver_at TIMESTAMPTZ, delivered_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT NOW())`
- [ ] Index on `deliver_at WHERE delivered_at IS NULL`

## Task 4: Proactive alerts service
- [ ] Create `backend/services/alerts.py`
- [ ] `check_budgets()` — compare MTD category spend vs `budgets` table, notify on 80%/100% (debounce: once per category per day via a simple in-memory set or check against last alert timestamp)
- [ ] `check_inbox()` — count files in /files/inbox/, notify if > 5 (debounce: once per hour)
- [ ] `check_reminders()` — query bh_reminders where deliver_at <= now() and delivered_at IS NULL, deliver each via Pushover, mark delivered
- [ ] Register all three in apscheduler: budgets every hour, inbox every 30min, reminders every minute

## Task 5: /remind slash command
- [ ] Add `/remind` as a builtin command in router_engine.py
- [ ] Parse natural language time: "in 2 hours", "tomorrow at 9am", "in 30 minutes", "at 5pm"
- [ ] Insert into bh_reminders table
- [ ] Return confirmation: "✅ Reminder set for [time]: [message]"
- [ ] Handle missing args gracefully: "Usage: /remind in 2 hours take out the trash"

## Task 6: /briefing slash command
- [ ] Add `/briefing` as a builtin command
- [ ] `/briefing` — generate and display a briefing right now (same content as morning, but on-demand)
- [ ] `/briefing off` — disable the daily briefing
- [ ] `/briefing on` — enable it
- [ ] `/briefing time 6:30am` — change delivery time

## Task 7: Voice input button (frontend)
- [ ] Create `frontend/src/components/VoiceInputButton.tsx`
- [ ] Uses window.SpeechRecognition (with webkit prefix fallback)
- [ ] Props: `onTranscript(text: string)`, `onFinalTranscript(text: string)`
- [ ] Visual states: idle (mic icon), recording (red pulsing), processing
- [ ] Hidden if SpeechRecognition not available in the browser

## Task 8: Wire voice input into InputArea
- [ ] Import VoiceInputButton in InputArea.tsx
- [ ] Add it before/next to the send button
- [ ] `onTranscript` → update the textarea value in real-time (interim results)
- [ ] `onFinalTranscript` → set final text in textarea (user can review before sending)
- [ ] Respect `settings.voice.input_enabled` — hide button if disabled

## Task 9: Add Pushover env vars to running container
- [ ] Add PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN to the .env file
- [ ] Values come from Dashlane (already configured for 595BowersHub app)
- [ ] Rebuild and deploy container

## Task 10: Integration test and deploy
- [ ] Verify briefing generates without errors (dry run)
- [ ] Verify Pushover notification delivers to phone
- [ ] Verify /remind stores and fires a reminder
- [ ] Verify voice input works on desktop Chrome and Android PWA
- [ ] Full container rebuild and deploy
