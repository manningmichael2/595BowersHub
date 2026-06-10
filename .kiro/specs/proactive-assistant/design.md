# Proactive Assistant — Design

## Architecture

### Morning Briefing

```
apscheduler (7am daily)
    → briefing_service.generate_briefing()
        → queries: spending (Postgres), weather (native skill), scores (ESPN), inbox (filesystem), knowledge (random fact)
        → assembles markdown
        → posts to "Daily Briefing" conversation via internal API
        → sends Pushover notification with condensed summary
```

**Backend files:**
- `backend/services/briefing.py` — already exists with partial implementation; extend with full data gathering and Pushover delivery
- `backend/main.py` — add briefing to apscheduler (alongside categorizer)

**Data flow:**
- Spending: direct Postgres query (no AI cost)
- Weather: call `get_weather("Clawson, MI")` 
- Scores: call `get_sports_score(team)` for each tracked team
- Inbox: `Path("/files/inbox").iterdir()` count
- Knowledge: random row from knowledge files

**Pushover integration:**
- Uses `PUSHOVER_USER_KEY` and `PUSHOVER_API_TOKEN` env vars (already documented in steering)
- Simple httpx POST to `https://api.pushover.net/1/messages.json`
- Priority 0 (normal) for daily briefing, priority 1 (high) for budget alerts

### Proactive Alerts

```
apscheduler jobs:
    - budget_check: every hour, compares MTD spend vs budgets table
    - game_alert: every 30 min, checks ESPN for tracked teams' upcoming games
    - inbox_check: every 30 min, counts /files/inbox/ items
    - reminder_check: every minute, fires stored reminders at their target time
```

**Backend files:**
- `backend/services/alerts.py` — new file, all alert logic
- `backend/models/reminder.py` — Reminder model (or store in bh_reminders table)

**Reminder storage:**
- New table `bh_reminders (id, user_id, message, deliver_at, delivered_at, created_at)`
- Created via L3 tool call or `/remind` slash command

### Voice Input

**Frontend only — no backend changes needed.**

```
InputArea.tsx
    → VoiceInputButton component
        → uses window.SpeechRecognition || webkitSpeechRecognition
        → onresult: updates input field text
        → onend: optionally auto-sends if configured
```

**Files:**
- `frontend/src/components/VoiceInputButton.tsx` — new component
- `frontend/src/components/InputArea.tsx` — add VoiceInputButton next to send
- `frontend/src/stores/settings.ts` — add `voice.input_enabled` setting

## Database Changes

### New table: bh_reminders
```sql
CREATE TABLE public.bh_reminders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES bh_users(id),
    message TEXT NOT NULL,
    deliver_at TIMESTAMPTZ NOT NULL,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON public.bh_reminders (deliver_at) WHERE delivered_at IS NULL;
```

### Settings extension
Add to existing `bh_user_settings`:
- `briefing_enabled` BOOLEAN DEFAULT true
- `briefing_time` TIME DEFAULT '07:00'
- `briefing_sections` JSONB DEFAULT '["spending","weather","scores","inbox","knowledge"]'
- `tracked_teams` JSONB DEFAULT '["tigers","lions","red wings","pistons","usmnt"]'
- `voice_input_enabled` BOOLEAN DEFAULT true

## Environment Variables (new)
```
PUSHOVER_USER_KEY=...
PUSHOVER_API_TOKEN=...
```

## Files to Create/Modify

### New files:
- `backend/services/alerts.py`
- `backend/services/pushover.py`
- `backend/migrations/010_reminders_and_briefing.sql`
- `frontend/src/components/VoiceInputButton.tsx`

### Modified files:
- `backend/services/briefing.py` (extend)
- `backend/main.py` (register alert jobs in apscheduler)
- `backend/services/router_engine.py` (add /remind, /briefing commands)
- `frontend/src/components/InputArea.tsx` (add voice button)
- `bowershub-ai/.env.example` (add Pushover vars)
