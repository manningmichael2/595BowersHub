"""
Game-Day Alerts — Pushover notifications before tracked team games.

Checks ESPN scoreboard for today's games involving tracked teams.
Sends a push notification ~90 minutes before game time.

Runs every 30 minutes via apscheduler. Uses in-memory debounce to avoid
duplicate alerts for the same game.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Set

import httpx
from backend.http_client import get_http_client

from backend.services.alerts import _all_active_user_ids, _get_notifier
from backend.services.sports_score import MY_TEAMS, TEAM_LEAGUE_MAP, LEAGUES, _expand_team_filter
from backend.database import get_pool

logger = logging.getLogger(__name__)

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

# In-memory debounce: track game IDs we've already alerted for today
_alerted_games: Set[str] = set()
_alerted_date: str = ""

# How far ahead to alert (in minutes)
ALERT_WINDOW_MINUTES = 120  # Check games starting within 2 hours
ALERT_TARGET_MINUTES = 90   # Ideal: alert ~90 min before


async def check_gameday_alerts():
    """
    Check for upcoming games from tracked teams and send Pushover alerts.
    Called every 30 minutes by the scheduler.
    """
    global _alerted_games, _alerted_date

    # Reset debounce daily
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _alerted_date != today_str:
        _alerted_games = set()
        _alerted_date = today_str

    now = datetime.now(timezone.utc)
    today_yyyymmdd = now.strftime("%Y%m%d")

    # Check each tracked team
    for team_name in MY_TEAMS:
        league_key = TEAM_LEAGUE_MAP.get(team_name)
        if not league_key or league_key not in LEAGUES:
            continue

        sport_path, league_path = LEAGUES[league_key]
        match_filter = _expand_team_filter(team_name) or team_name

        try:
            url = f"{ESPN_BASE}/{sport_path}/{league_path}/scoreboard?dates={today_yyyymmdd}"
            client = get_http_client()
            resp = await client.get(url, timeout=10.0)
            if resp.status_code >= 400:
                continue
            data = resp.json()
        except Exception as e:
            logger.debug(f"Gameday alert: ESPN fetch failed for {team_name}: {e}")
            continue

        events = data.get("events", [])
        for event in events:
            game_id = event.get("id", "")
            if game_id in _alerted_games:
                continue

            # Check if this game involves our team
            comp = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            team_names = [c.get("team", {}).get("displayName", "").lower() for c in competitors]

            if not any(match_filter in t for t in team_names):
                continue

            # Check game state — only alert for pre-game
            state = event.get("status", {}).get("type", {}).get("state", "")
            if state != "pre":
                continue  # Game already started or finished

            # Parse start time
            start_str = comp.get("startDate") or event.get("date", "")
            if not start_str:
                continue

            try:
                # ESPN returns ISO format like "2026-06-07T17:35Z"
                start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            # Check if game starts within our alert window
            minutes_until = (start_time - now).total_seconds() / 60

            if 0 < minutes_until <= ALERT_WINDOW_MINUTES:
                # Game is within window — send alert
                _alerted_games.add(game_id)

                # Build alert message
                away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[0])
                home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[-1])
                away_name = away.get("team", {}).get("displayName", "?")
                home_name = home.get("team", {}).get("displayName", "?")

                # Time in Eastern
                eastern_offset = timedelta(hours=-4)  # EDT
                local_time = start_time + eastern_offset
                time_str = local_time.strftime("%-I:%M %p")

                # Get pitching info if MLB
                pitcher_info = ""
                if league_key == "mlb":
                    for side, competitor in [("away", away), ("home", home)]:
                        for prob in competitor.get("probables", []):
                            if prob.get("name") == "probableStartingPitcher":
                                ath = prob.get("athlete", {})
                                name = ath.get("shortName", ath.get("displayName", ""))
                                record = prob.get("record", "")
                                if name:
                                    pitcher_info += f"\n{competitor.get('team',{}).get('abbreviation','')}: {name} {record}"

                # League display
                league_display = data.get("leagues", [{}])[0].get("abbreviation", league_key.upper())

                title = f"🏟️ {league_display}: {away_name} @ {home_name}"
                message = f"<b>{away_name}</b> at <b>{home_name}</b>\n⏰ {time_str} ET"
                if pitcher_info:
                    message += f"\n\n<b>Pitching:</b>{pitcher_info}"

                minutes_int = int(minutes_until)
                message += f"\n\n<i>Starts in ~{minutes_int} minutes</i>"

                pool = get_pool()
                async with pool.acquire() as conn:
                    recipients = await _all_active_user_ids(conn)
                await _get_notifier().notify_users(
                    recipients,
                    event_type="gameday",
                    title=title,
                    message=message,
                    priority=0,
                    url="https://595bowershub.tailc4d58a.ts.net",
                    url_title="Open BowersHub AI",
                )
                logger.info(f"Game-day alert sent: {away_name} @ {home_name} at {time_str}")
