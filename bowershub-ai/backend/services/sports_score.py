"""
Sports Score skill — live game scores via ESPN's public API.

Unified endpoint covers 20+ sports/leagues. No API key needed.
Base URL: https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard

Supports: NFL, NBA, WNBA, MLB, NHL, MLS, Premier League, La Liga, Champions League,
World Cup, Women's World Cup, College Football, College Basketball, UFC, Tennis (ATP/WTA),
Golf (PGA), F1, and more.
"""
import logging
from datetime import date
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

# ---- League registry -------------------------------------------------------
# Maps user-friendly names and abbreviations to ESPN's sport/league path

LEAGUES = {
    # American major sports
    "nfl": ("football", "nfl"),
    "nba": ("basketball", "nba"),
    "mlb": ("baseball", "mlb"),
    "nhl": ("hockey", "nhl"),
    "wnba": ("basketball", "wnba"),
    "mls": ("soccer", "usa.1"),
    # College
    "ncaaf": ("football", "college-football"),
    "college football": ("football", "college-football"),
    "ncaab": ("basketball", "mens-college-basketball"),
    "college basketball": ("basketball", "mens-college-basketball"),
    "ncaaw": ("basketball", "womens-college-basketball"),
    # Soccer / football
    "premier league": ("soccer", "eng.1"),
    "epl": ("soccer", "eng.1"),
    "la liga": ("soccer", "esp.1"),
    "bundesliga": ("soccer", "ger.1"),
    "serie a": ("soccer", "ita.1"),
    "ligue 1": ("soccer", "fra.1"),
    "champions league": ("soccer", "uefa.champions"),
    "ucl": ("soccer", "uefa.champions"),
    "world cup": ("soccer", "fifa.world"),
    "womens world cup": ("soccer", "fifa.wwc"),
    "women's world cup": ("soccer", "fifa.wwc"),
    "nwsl": ("soccer", "usa.nwsl"),
    "liga mx": ("soccer", "mex.1"),
    # Combat / racing / other
    "ufc": ("mma", "ufc"),
    "mma": ("mma", "ufc"),
    "f1": ("racing", "f1"),
    "formula 1": ("racing", "f1"),
    "nascar": ("racing", "nascar-cup"),  
    "pga": ("golf", "pga"),
    "golf": ("golf", "pga"),
    "atp": ("tennis", "atp"),
    "wta": ("tennis", "wta"),
    "tennis": ("tennis", "atp"),
}

# ---- Team → league mapping (fuzzy) ----------------------------------------
# Maps common team names to their league so the user can just say "Tigers score"

TEAM_LEAGUE_MAP = {
    # MLB
    "angels": "mlb", "astros": "mlb", "athletics": "mlb", "blue jays": "mlb",
    "braves": "mlb", "brewers": "mlb", "cardinals": "mlb", "cubs": "mlb",
    "diamondbacks": "mlb", "d-backs": "mlb", "dodgers": "mlb", "giants": "mlb",
    "guardians": "mlb", "mariners": "mlb", "marlins": "mlb", "mets": "mlb",
    "nationals": "mlb", "orioles": "mlb", "padres": "mlb", "phillies": "mlb",
    "pirates": "mlb", "rangers": "mlb", "rays": "mlb", "red sox": "mlb",
    "reds": "mlb", "rockies": "mlb", "royals": "mlb", "tigers": "mlb",
    "twins": "mlb", "white sox": "mlb", "yankees": "mlb",
    # NHL
    "bruins": "nhl", "sabres": "nhl", "red wings": "nhl", "panthers": "nhl",
    "canadiens": "nhl", "habs": "nhl", "senators": "nhl", "lightning": "nhl",
    "maple leafs": "nhl", "leafs": "nhl", "hurricanes": "nhl", "blue jackets": "nhl",
    "devils": "nhl", "islanders": "nhl", "flyers": "nhl",
    "penguins": "nhl", "capitals": "nhl", "caps": "nhl", "blackhawks": "nhl",
    "avalanche": "nhl", "stars": "nhl", "wild": "nhl", "predators": "nhl",
    "blues": "nhl", "jets": "nhl", "ducks": "nhl", "flames": "nhl",
    "oilers": "nhl", "kings": "nhl", "sharks": "nhl", "kraken": "nhl",
    "canucks": "nhl", "golden knights": "nhl", "knights": "nhl",
    # NBA
    "hawks": "nba", "celtics": "nba", "nets": "nba", "hornets": "nba",
    "bulls": "nba", "cavaliers": "nba", "cavs": "nba", "mavericks": "nba",
    "mavs": "nba", "nuggets": "nba", "pistons": "nba", "warriors": "nba",
    "rockets": "nba", "pacers": "nba", "clippers": "nba", "lakers": "nba",
    "grizzlies": "nba", "heat": "nba", "bucks": "nba", "timberwolves": "nba",
    "wolves": "nba", "pelicans": "nba", "knicks": "nba", "thunder": "nba",
    "magic": "nba", "76ers": "nba", "sixers": "nba", "suns": "nba",
    "trail blazers": "nba", "blazers": "nba", "spurs": "nba",
    "raptors": "nba", "jazz": "nba", "wizards": "nba",
    # NFL
    "falcons": "nfl", "ravens": "nfl", "bills": "nfl",
    "bears": "nfl", "bengals": "nfl", "browns": "nfl", "cowboys": "nfl",
    "broncos": "nfl", "lions": "nfl", "packers": "nfl", "texans": "nfl",
    "colts": "nfl", "jaguars": "nfl", "chiefs": "nfl", "raiders": "nfl",
    "chargers": "nfl", "rams": "nfl", "dolphins": "nfl", "vikings": "nfl",
    "patriots": "nfl", "saints": "nfl", "eagles": "nfl", "steelers": "nfl",
    "49ers": "nfl", "niners": "nfl", "seahawks": "nfl",
    "buccaneers": "nfl", "bucs": "nfl", "titans": "nfl", "commanders": "nfl",
    # WNBA
    "aces": "wnba", "dream": "wnba", "fever": "wnba", "liberty": "wnba",
    "lynx": "wnba", "mercury": "wnba", "mystics": "wnba", "sky": "wnba",
    "sparks": "wnba", "storm": "wnba", "sun": "wnba", "wings": "wnba",
    "valkyries": "wnba",
    # MLS
    "atlanta united": "mls", "austin fc": "mls", "charlotte fc": "mls",
    "chicago fire": "mls", "fc cincinnati": "mls", "colorado rapids": "mls",
    "columbus crew": "mls", "fc dallas": "mls", "dc united": "mls",
    "dynamo": "mls", "inter miami": "mls", "la galaxy": "mls", "galaxy": "mls",
    "lafc": "mls", "minnesota united": "mls", "cf montreal": "mls",
    "nashville sc": "mls", "new england revolution": "mls", "revs": "mls",
    "nycfc": "mls", "red bulls": "mls", "orlando city": "mls",
    "philadelphia union": "mls", "portland timbers": "mls", "timbers": "mls",
    "real salt lake": "mls", "san jose earthquakes": "mls",
    "seattle sounders": "mls", "sounders": "mls", "sporting kc": "mls",
    "st louis city": "mls", "toronto fc": "mls", "vancouver whitecaps": "mls",
}


def _resolve_league(team: Optional[str], sport: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Resolve user input to (sport_path, league_path, team_filter).
    Returns (None, None, error_message) on failure.
    """
    # If sport/league is explicitly specified
    if sport:
        sport_lower = sport.lower().strip()
        if sport_lower in LEAGUES:
            sport_path, league_path = LEAGUES[sport_lower]
            return sport_path, league_path, team.lower().strip() if team else None
        # Maybe they said a team name in the sport field
        if sport_lower in TEAM_LEAGUE_MAP:
            league_key = TEAM_LEAGUE_MAP[sport_lower]
            sport_path, league_path = LEAGUES[league_key]
            return sport_path, league_path, sport_lower
        return None, None, f"Unknown sport/league '{sport}'. Try: {', '.join(sorted(set(LEAGUES.keys())))}"

    # No sport specified — resolve from team name
    if not team:
        return None, None, "Provide a team name or sport/league (e.g., 'Tigers', 'MLB scores', 'Premier League')"

    team_lower = team.lower().strip()

    # Direct team lookup
    if team_lower in TEAM_LEAGUE_MAP:
        league_key = TEAM_LEAGUE_MAP[team_lower]
        sport_path, league_path = LEAGUES[league_key]
        return sport_path, league_path, team_lower

    # Fuzzy substring match
    for name, league_key in TEAM_LEAGUE_MAP.items():
        if team_lower in name or name in team_lower:
            sport_path, league_path = LEAGUES[league_key]
            return sport_path, league_path, name

    # Maybe it's a league name
    if team_lower in LEAGUES:
        sport_path, league_path = LEAGUES[team_lower]
        return sport_path, league_path, None

    return None, None, (
        f"Couldn't identify '{team}'. Try a team name (Tigers, Red Wings, Chiefs) "
        f"or a league (MLB, NHL, NBA, NFL, WNBA, Premier League, MLS, UFC, F1)."
    )


async def get_sports_score(team: Optional[str] = None, sport: Optional[str] = None) -> dict:
    """
    Get live/recent scores. 
    
    Args:
        team: Team name (e.g., "Tigers", "Red Wings", "Lions", "Inter Miami")
        sport: League/sport (e.g., "MLB", "Premier League", "WNBA", "UFC", "F1")
    """
    sport_path, league_path, team_filter = _resolve_league(team, sport)

    if sport_path is None:
        return {"error": team_filter}  # team_filter holds the error message

    # Fetch scoreboard from ESPN
    url = f"{ESPN_BASE}/{sport_path}/{league_path}/scoreboard"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"ESPN API returned {e.response.status_code} for {sport_path}/{league_path}"}
    except Exception as e:
        return {"error": f"Failed to reach ESPN: {e}"}

    events = data.get("events", [])
    league_name = data.get("leagues", [{}])[0].get("name", league_path.upper())

    if not events:
        result = {"sport": league_name, "date": date.today().isoformat(), "games": [], "status": "No games scheduled"}
        if team_filter:
            result["team"] = team_filter.title()
            result["status"] = "No game today"
        return result

    # Parse all games
    games = []
    for event in events:
        game = _parse_espn_event(event, league_name)
        if game:
            games.append(game)

    # Filter to specific team if requested
    if team_filter:
        matched = [
            g for g in games
            if team_filter in g.get("away_team", "").lower()
            or team_filter in g.get("home_team", "").lower()
        ]
        if matched:
            if len(matched) == 1:
                return {**matched[0], "_display": _render_single_game(matched[0])}
            return {"sport": league_name, "games": matched, "_display": _render_scoreboard(league_name, matched)}
        return {"team": team_filter.title(), "sport": league_name, "status": "No game today",
                "_display": f"No {league_name} game today for **{team_filter.title()}**."}

    display = _render_scoreboard(league_name, games)
    return {"sport": league_name, "date": date.today().isoformat(), "games": games, "_display": display}


def _parse_espn_event(event: dict, league_name: str) -> Optional[dict]:
    """Parse a single ESPN event into a clean score dict."""
    competition = event.get("competitions", [{}])[0]
    competitors = competition.get("competitors", [])

    if len(competitors) < 2:
        # Single-competitor events (golf, F1, tennis, UFC) — different format
        return _parse_individual_event(event, league_name)

    # Team sport — find home/away
    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

    status_obj = event.get("status", {})
    status_type = status_obj.get("type", {})
    status_text = status_type.get("shortDetail", status_type.get("description", "Unknown"))

    result = {
        "sport": league_name,
        "away_team": away.get("team", {}).get("displayName", "?"),
        "home_team": home.get("team", {}).get("displayName", "?"),
        "away_score": _safe_int(away.get("score", "0")),
        "home_score": _safe_int(home.get("score", "0")),
        "status": status_text,
    }

    # Add records if available
    away_record = away.get("records", [{}])[0].get("summary") if away.get("records") else None
    home_record = home.get("records", [{}])[0].get("summary") if home.get("records") else None
    if away_record:
        result["away_record"] = away_record
    if home_record:
        result["home_record"] = home_record

    return result


def _parse_individual_event(event: dict, league_name: str) -> Optional[dict]:
    """Parse individual-competitor events (golf, F1, tennis, UFC)."""
    name = event.get("name", event.get("shortName", ""))
    status_obj = event.get("status", {})
    status_text = status_obj.get("type", {}).get("shortDetail", "")

    competitors = event.get("competitions", [{}])[0].get("competitors", [])
    
    # For individual sports, list top competitors
    top = []
    for c in competitors[:5]:
        athlete = c.get("athlete", {})
        display = athlete.get("displayName", c.get("team", {}).get("displayName", "?"))
        score = c.get("score", c.get("linescores", [{}])[-1].get("value") if c.get("linescores") else "")
        top.append({"name": display, "score": str(score) if score else ""})

    return {
        "sport": league_name,
        "event": name,
        "status": status_text,
        "leaders": top if top else None,
    }


def _safe_int(val) -> int:
    """Safely convert a score value to int."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


# ---- Display formatters ---------------------------------------------------

def _render_single_game(game: dict) -> str:
    """Render a single game score in beautiful markdown."""
    sport = game.get("sport", "")
    away = game.get("away_team", "?")
    home = game.get("home_team", "?")
    away_score = game.get("away_score", 0)
    home_score = game.get("home_score", 0)
    status = game.get("status", "")

    # Determine game state
    is_final = "final" in status.lower()
    is_live = not is_final and away_score + home_score > 0 and "scheduled" not in status.lower()
    is_scheduled = "scheduled" in status.lower() or (not is_final and not is_live and ":" in status)

    lines = [f"## 🏟️ {sport}", ""]

    if is_scheduled:
        lines.append(f"**{away}** vs **{home}**")
        lines.append("")
        lines.append(f"⏰ {status}")
    elif is_live:
        lines.append(f"🔴 **LIVE** — {status}")
        lines.append("")
        lines.append(f"**{away}** — {away_score}")
        lines.append(f"**{home}** — {home_score}")
    else:
        # Final — highlight winner
        if away_score > home_score:
            lines.append(f"**{away} — {away_score}** ✓")
            lines.append(f"{home} — {home_score}")
        elif home_score > away_score:
            lines.append(f"{away} — {away_score}")
            lines.append(f"**{home} — {home_score}** ✓")
        else:
            lines.append(f"{away} — {away_score}")
            lines.append(f"{home} — {home_score}")
        lines.append("")
        lines.append(f"✅ {status}")

    # Records if available
    away_rec = game.get("away_record")
    home_rec = game.get("home_record")
    if away_rec or home_rec:
        lines.append("")
        parts = []
        if away_rec:
            parts.append(f"{away}: {away_rec}")
        if home_rec:
            parts.append(f"{home}: {home_rec}")
        lines.append(f"*{' · '.join(parts)}*")

    return "\n".join(lines)


def _render_scoreboard(league_name: str, games: list[dict]) -> str:
    """Render a multi-game scoreboard."""
    lines = [f"## 🏟️ {league_name} Scoreboard", ""]

    # Group by status: live first, then final, then scheduled
    live = [g for g in games if _is_live(g)]
    final = [g for g in games if _is_final(g)]
    scheduled = [g for g in games if not _is_live(g) and not _is_final(g)]

    if live:
        lines.append("### 🔴 Live")
        for g in live:
            lines.append(_render_game_line(g))
        lines.append("")

    if final:
        lines.append("### ✅ Final")
        for g in final:
            lines.append(_render_game_line(g))
        lines.append("")

    if scheduled:
        lines.append("### ⏰ Upcoming")
        for g in scheduled:
            lines.append(_render_game_line(g))
        lines.append("")

    if not games:
        lines.append("No games today.")

    return "\n".join(lines)


def _render_game_line(game: dict) -> str:
    """Render a single game as a compact one-line summary."""
    away = game.get("away_team", "?")
    home = game.get("home_team", "?")
    away_score = game.get("away_score", 0)
    home_score = game.get("home_score", 0)
    status = game.get("status", "")

    if _is_final(game):
        winner = "→" if away_score > home_score else "←" if home_score > away_score else "="
        if winner == "→":
            return f"**{away} {away_score}** – {home_score} {home}"
        elif winner == "←":
            return f"{away} {away_score} – **{home_score} {home}**"
        else:
            return f"{away} {away_score} – {home_score} {home} (Tied)"
    elif _is_live(game):
        return f"🔴 {away} {away_score} – {home_score} {home} *({status})*"
    else:
        return f"{away} @ {home} — {status}"


def _is_live(game: dict) -> bool:
    status = game.get("status", "").lower()
    scores = game.get("away_score", 0) + game.get("home_score", 0)
    return (
        "live" in status
        or "in progress" in status
        or ("period" in status and "final" not in status)
        or ("inning" in status)
        or ("quarter" in status)
        or ("half" in status and "final" not in status)
        or (scores > 0 and "final" not in status and "scheduled" not in status
            and ":" not in status and "pm" not in status.lower() and "am" not in status.lower())
    )


def _is_final(game: dict) -> bool:
    status = game.get("status", "").lower()
    return "final" in status or "ft" == status.strip() or status.startswith("f/")
