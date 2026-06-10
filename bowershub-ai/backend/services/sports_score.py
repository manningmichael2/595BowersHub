"""
Sports Score skill — live game scores via ESPN's public API.

Unified endpoint covers 20+ sports/leagues. No API key needed.
Base URL: https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard

Architecture:
1. Fast path: hardcoded lookups for known teams/leagues (instant, covers 95% of queries)
2. Fallback: Ollama local model interprets ambiguous queries (free, ~1-2s latency)
3. Never show raw errors — always return user-friendly markdown via _display

Supports: NFL, NBA, WNBA, MLB, NHL, MLS, Premier League, La Liga, Champions League,
World Cup, College Football, College Basketball, UFC, Tennis (ATP/WTA), Golf (PGA), F1.
"""
import logging
from datetime import date, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

# ---- League registry -------------------------------------------------------
# Maps user-friendly names and abbreviations to ESPN's sport/league path.
# Also includes common English words people use to refer to sports.

LEAGUES = {
    # American major sports
    "nfl": ("football", "nfl"),
    "nba": ("basketball", "nba"),
    "mlb": ("baseball", "mlb"),
    "nhl": ("hockey", "nhl"),
    "wnba": ("basketball", "wnba"),
    "mls": ("soccer", "usa.1"),
    # Common English aliases for the above
    "baseball": ("baseball", "mlb"),
    "football": ("football", "nfl"),
    "basketball": ("basketball", "nba"),
    "hockey": ("hockey", "nhl"),
    "soccer": ("soccer", "usa.1"),
    # College
    "ncaaf": ("football", "college-football"),
    "college football": ("football", "college-football"),
    "cfb": ("football", "college-football"),
    "ncaab": ("basketball", "mens-college-basketball"),
    "college basketball": ("basketball", "mens-college-basketball"),
    "cbb": ("basketball", "mens-college-basketball"),
    "ncaaw": ("basketball", "womens-college-basketball"),
    "march madness": ("basketball", "mens-college-basketball"),
    # Soccer / football
    "premier league": ("soccer", "eng.1"),
    "epl": ("soccer", "eng.1"),
    "prem": ("soccer", "eng.1"),
    "la liga": ("soccer", "esp.1"),
    "bundesliga": ("soccer", "ger.1"),
    "serie a": ("soccer", "ita.1"),
    "ligue 1": ("soccer", "fra.1"),
    "champions league": ("soccer", "uefa.champions"),
    "ucl": ("soccer", "uefa.champions"),
    "world cup": ("soccer", "fifa.world"),
    "friendlies": ("soccer", "fifa.friendly"),
    "international friendly": ("soccer", "fifa.friendly"),
    "womens world cup": ("soccer", "fifa.wwc"),
    "women's world cup": ("soccer", "fifa.wwc"),
    "nwsl": ("soccer", "usa.nwsl"),
    "liga mx": ("soccer", "mex.1"),
    # Combat / racing / other
    "ufc": ("mma", "ufc"),
    "mma": ("mma", "ufc"),
    "f1": ("racing", "f1"),
    "formula 1": ("racing", "f1"),
    "formula one": ("racing", "f1"),
    "pga": ("golf", "pga"),
    "golf": ("golf", "pga"),
    "atp": ("tennis", "atp"),
    "wta": ("tennis", "wta"),
    "tennis": ("tennis", "atp"),
}

# ---- Team → league mapping -------------------------------------------------
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
    # Soccer - National teams & popular clubs
    "usmnt": "friendlies", "us mens": "friendlies", "usa soccer": "friendlies",
    "usa mens": "friendlies", "us soccer": "friendlies", "united states": "friendlies",
    "usa soccer mens": "friendlies", "mens soccer usa": "friendlies",
    "us men's": "friendlies", "usa men's soccer": "friendlies",
    "uswnt": "womens world cup", "us womens": "womens world cup",
    "usa womens": "womens world cup", "us women's": "womens world cup",
    # Premier League clubs
    "arsenal": "premier league", "gunners": "premier league",
    "aston villa": "premier league", "villa": "premier league",
    "bournemouth": "premier league", "brentford": "premier league",
    "brighton": "premier league", "chelsea": "premier league",
    "crystal palace": "premier league", "everton": "premier league",
    "fulham": "premier league", "ipswich": "premier league",
    "leicester": "premier league", "liverpool": "premier league",
    "man city": "premier league", "manchester city": "premier league",
    "man united": "premier league", "manchester united": "premier league",
    "man u": "premier league", "mufc": "premier league",
    "newcastle": "premier league", "magpies": "premier league",
    "nottingham forest": "premier league", "forest": "premier league",
    "southampton": "premier league", "tottenham": "premier league",
    "west ham": "premier league", "hammers": "premier league",
    "wolverhampton": "premier league", "wolves": "premier league",
    # La Liga
    "barcelona": "la liga", "barca": "la liga", "real madrid": "la liga",
    "atletico": "la liga", "atletico madrid": "la liga",
    # Champions League / European clubs
    "bayern": "champions league", "bayern munich": "champions league",
    "psg": "champions league", "paris": "champions league",
    "juventus": "champions league", "juve": "champions league",
    "inter": "champions league", "inter milan": "champions league",
    "ac milan": "champions league",
    "dortmund": "champions league", "borussia dortmund": "champions league",
}

# ---- Alias → ESPN team display name (for matching against scoreboard) ------
TEAM_DISPLAY_NAMES = {
    "usmnt": "united states", "us mens": "united states", "usa soccer": "united states",
    "usa mens": "united states", "us soccer": "united states", "united states": "united states",
    "usa soccer mens": "united states", "mens soccer usa": "united states",
    "us men's": "united states", "usa men's soccer": "united states",
    "uswnt": "united states", "us womens": "united states",
    "usa womens": "united states", "us women's": "united states",
    "man city": "manchester city", "city": "manchester city",
    "man united": "manchester united", "man u": "manchester united", "mufc": "manchester united",
    "spurs": "tottenham", "gunners": "arsenal",
    "barca": "barcelona", "bayern": "bayern munich",
    "psg": "paris saint-germain", "juve": "juventus",
    "habs": "canadiens", "leafs": "maple leafs", "caps": "capitals",
    "niners": "49ers", "bucs": "buccaneers",
    "cavs": "cavaliers", "mavs": "mavericks", "sixers": "76ers",
    "blazers": "trail blazers", "wolves": "timberwolves",
    "revs": "new england", "sounders": "seattle",
    "galaxy": "la galaxy", "timbers": "portland",
    "knights": "golden knights",
}


# ---- Resolution logic -------------------------------------------------------

def _expand_team_filter(team_filter: Optional[str]) -> Optional[str]:
    """Expand an alias to the ESPN display name for matching."""
    if not team_filter:
        return None
    return TEAM_DISPLAY_NAMES.get(team_filter, team_filter)


async def _ollama_available() -> bool:
    """Quick check if Ollama is reachable."""
    from backend.services.local_intelligence import is_available
    return await is_available()


def _resolve_league(team: Optional[str], sport: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Resolve user input to (sport_path, league_path, team_filter).
    Returns (None, None, error_message) on failure.
    
    Priority order:
    1. Check LEAGUES dict (handles league names and common sport words)
    2. Check TEAM_LEAGUE_MAP (handles team names)
    3. Fuzzy substring match on teams
    4. Return error (caller may try Ollama fallback)
    """
    # If sport/league is explicitly specified
    if sport:
        sport_lower = sport.lower().strip()
        if sport_lower in LEAGUES:
            sport_path, league_path = LEAGUES[sport_lower]
            return sport_path, league_path, team.lower().strip() if team else None
        if sport_lower in TEAM_LEAGUE_MAP:
            league_key = TEAM_LEAGUE_MAP[sport_lower]
            sport_path, league_path = LEAGUES[league_key]
            return sport_path, league_path, sport_lower
        return None, None, f"I don't have data for '{sport}'. Available: MLB, NFL, NBA, NHL, WNBA, MLS, Premier League, La Liga, UFC, F1, Golf, Tennis, College Football/Basketball."

    # No sport specified — resolve from team/query
    if not team:
        return None, None, None  # No input at all — caller should show default

    query_lower = team.lower().strip()

    # 1. Check if it's a league name FIRST (most common failure case)
    if query_lower in LEAGUES:
        sport_path, league_path = LEAGUES[query_lower]
        return sport_path, league_path, None

    # 2. Direct team lookup
    if query_lower in TEAM_LEAGUE_MAP:
        league_key = TEAM_LEAGUE_MAP[query_lower]
        sport_path, league_path = LEAGUES[league_key]
        return sport_path, league_path, query_lower

    # 3. Fuzzy substring match on team names
    for name, league_key in TEAM_LEAGUE_MAP.items():
        if query_lower in name or name in query_lower:
            sport_path, league_path = LEAGUES[league_key]
            return sport_path, league_path, name

    # 4. Check if query contains a league keyword
    for league_name, paths in LEAGUES.items():
        if league_name in query_lower:
            return paths[0], paths[1], None

    return None, None, f"I couldn't identify '{team}' as a team or league. Try a team name (Tigers, Chiefs, Arsenal) or a league (MLB, NFL, NBA, Premier League, UFC, F1)."


async def get_sports_score(team: Optional[str] = None, sport: Optional[str] = None) -> dict:
    """
    Get live/recent scores.
    
    Args:
        team: Team name or league (e.g., "Tigers", "MLB", "Premier League", "baseball")
        sport: Explicit league/sport override (e.g., "MLB", "Premier League")
    """
    sport_path, league_path, team_filter = _resolve_league(team, sport)

    # If resolution failed, try local intelligence as fallback
    if sport_path is None:
        error_msg = team_filter  # holds error message or None
        query = team or sport or ""
        
        if query:
            from backend.services.local_intelligence import interpret_sports_query
            interpretation = await interpret_sports_query(query)
            if interpretation:
                resolved_league = interpretation.get("league")
                resolved_team = interpretation.get("team")
                
                if resolved_league and resolved_league.lower() in LEAGUES:
                    sport_path, league_path = LEAGUES[resolved_league.lower()]
                    team_filter = resolved_team.lower() if resolved_team else None
                    # Validate team_filter exists in our map
                    if team_filter and team_filter not in TEAM_LEAGUE_MAP:
                        for name in TEAM_LEAGUE_MAP:
                            if team_filter in name or name in team_filter:
                                team_filter = name
                                break
                        else:
                            team_filter = None
                elif resolved_league:
                    return _friendly_error(
                        f"I don't have live data for {resolved_league}. "
                        f"I can check: MLB, NFL, NBA, NHL, WNBA, MLS, Premier League, La Liga, "
                        f"Champions League, UFC, F1, Golf, Tennis, College Football/Basketball."
                    )
        
        # Still no resolution
        if sport_path is None:
            if error_msg:
                return _friendly_error(error_msg)
            return _friendly_error(
                "Tell me a team or league and I'll get the latest scores. "
                "Examples: `/sports tigers`, `/sports mlb`, `/sports premier league`"
            )

    # Fetch from ESPN
    dates_to_try = [date.today(), date.today() - timedelta(days=1)]
    match_filter = _expand_team_filter(team_filter)

    for try_date in dates_to_try:
        date_str = try_date.strftime("%Y%m%d")
        url = f"{ESPN_BASE}/{sport_path}/{league_path}/scoreboard?dates={date_str}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    # ESPN doesn't support this endpoint — not our fault, give a friendly message
                    league_display = league_path.upper().replace(".", " ").replace("-", " ")
                    return _friendly_error(
                        f"ESPN doesn't have scoreboard data available for {league_display} right now. "
                        f"This league may be in the off-season or not tracked by ESPN's public API."
                    )
                data = resp.json()
        except Exception as e:
            return _friendly_error(f"Couldn't reach ESPN right now. Try again in a moment.")

        events = data.get("events", [])
        league_name = data.get("leagues", [{}])[0].get("name", league_path.upper())

        if not events:
            continue  # Try the next date

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
                if match_filter in g.get("away_team", "").lower()
                or match_filter in g.get("home_team", "").lower()
            ]
            if matched:
                if len(matched) == 1:
                    return {**matched[0], "_display": _render_single_game(matched[0])}
                return {"sport": league_name, "games": matched, "_display": _render_scoreboard(league_name, matched)}
            # No match for this date — try the next one
            if try_date == dates_to_try[-1]:
                return {
                    "team": team_filter.title(), "sport": league_name,
                    "_display": f"No recent {league_name} game found for **{team_filter.title()}** (checked today and yesterday).",
                }
            continue

        # No team filter — return all games for this date
        display = _render_scoreboard(league_name, games)
        return {"sport": league_name, "date": try_date.isoformat(), "games": games, "_display": display}

    # Both dates empty
    # Try to get the proper league name from the last response, or make one from the path
    league_name_display = league_path.replace(".", " ").replace("-", " ").title()
    # Map some common paths to better display names
    _LEAGUE_DISPLAY_NAMES = {
        "eng.1": "Premier League", "esp.1": "La Liga", "ger.1": "Bundesliga",
        "ita.1": "Serie A", "fra.1": "Ligue 1", "usa.1": "MLS",
        "usa.nwsl": "NWSL", "mex.1": "Liga MX", "fifa.world": "World Cup",
        "fifa.friendly": "International Friendlies", "fifa.wwc": "Women's World Cup",
        "uefa.champions": "Champions League",
        "nfl": "NFL", "nba": "NBA", "mlb": "MLB", "nhl": "NHL",
        "wnba": "WNBA", "f1": "Formula 1", "pga": "PGA Tour",
        "ufc": "UFC", "atp": "ATP Tennis", "wta": "WTA Tennis",
        "college-football": "College Football",
        "mens-college-basketball": "College Basketball",
    }
    league_name_display = _LEAGUE_DISPLAY_NAMES.get(league_path, league_name_display)
    
    if team_filter:
        return {
            "_display": f"No recent game found for **{team_filter.title()}** (checked today and yesterday).",
        }
    return {
        "_display": f"No {league_name_display} games scheduled today or yesterday.",
    }


def _friendly_error(message: str) -> dict:
    """Return an error as a user-friendly _display message, never raw JSON."""
    return {"_display": message}


async def get_box_score(team: Optional[str] = None, sport: Optional[str] = None) -> dict:
    """
    Get the full box score for a team's most recent/current game.
    Fetches detailed batting and pitching lines from ESPN's summary endpoint.
    """
    # First, find the game via the scoreboard
    sport_path, league_path, team_filter = _resolve_league(team, sport)
    
    if sport_path is None:
        # Try local intelligence fallback
        query = team or sport or ""
        if query:
            from backend.services.local_intelligence import interpret_sports_query
            interpretation = await interpret_sports_query(query)
            if interpretation:
                resolved_league = interpretation.get("league")
                resolved_team = interpretation.get("team")
                if resolved_league and resolved_league.lower() in LEAGUES:
                    sport_path, league_path = LEAGUES[resolved_league.lower()]
                    team_filter = resolved_team.lower() if resolved_team else None
                    if team_filter and team_filter not in TEAM_LEAGUE_MAP:
                        for name in TEAM_LEAGUE_MAP:
                            if team_filter in name or name in team_filter:
                                team_filter = name
                                break
                        else:
                            team_filter = None
        if sport_path is None:
            return _friendly_error("Specify a team to get the box score (e.g., 'tigers box score').")

    # Find the game ID from scoreboard
    match_filter = _expand_team_filter(team_filter)
    dates_to_try = [date.today(), date.today() - timedelta(days=1)]
    game_id = None
    league_name = ""

    for try_date in dates_to_try:
        date_str = try_date.strftime("%Y%m%d")
        url = f"{ESPN_BASE}/{sport_path}/{league_path}/scoreboard?dates={date_str}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    continue
                data = resp.json()
        except Exception:
            continue

        events = data.get("events", [])
        league_name = data.get("leagues", [{}])[0].get("name", league_path.upper())

        for event in events:
            if not team_filter:
                # No team filter — just grab the first game
                game_id = event.get("id")
                break
            # Match team
            comp = event.get("competitions", [{}])[0]
            for competitor in comp.get("competitors", []):
                team_name = competitor.get("team", {}).get("displayName", "").lower()
                if match_filter and match_filter in team_name:
                    game_id = event.get("id")
                    break
            if game_id:
                break
        if game_id:
            break

    if not game_id:
        if team_filter:
            return _friendly_error(f"No recent game found for **{team_filter.title()}** to show a box score.")
        return _friendly_error("No game found to show a box score.")

    # Fetch the game summary (has full box score)
    summary_url = f"{ESPN_BASE}/{sport_path}/{league_path}/summary?event={game_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(summary_url)
            if resp.status_code >= 400:
                return _friendly_error("ESPN box score data isn't available for this game.")
            summary = resp.json()
    except Exception:
        return _friendly_error("Couldn't fetch box score data from ESPN.")

    # Parse and render the box score
    boxscore = summary.get("boxscore", {})
    players = boxscore.get("players", [])
    
    if not players:
        return _friendly_error("Box score data isn't available yet for this game.")

    # Get game status from header
    header = summary.get("header", {})
    game_status = ""
    competitions = header.get("competitions", [{}])
    if competitions:
        game_status = competitions[0].get("status", {}).get("type", {}).get("shortDetail", "")

    display = _render_box_score(players, league_name, game_status)
    return {"_display": display, "game_id": game_id}


def _render_box_score(players: list, league_name: str, game_status: str) -> str:
    """Render a full box score as readable markdown."""
    lines = [f"## 📊 {league_name} — Box Score"]
    if game_status:
        lines.append(f"*{game_status}*")
    lines.append("")

    for team_block in players:
        team_name = team_block.get("team", {}).get("displayName", "?")
        lines.append(f"### {team_name}")
        lines.append("")

        for stat_cat in team_block.get("statistics", []):
            cat_type = stat_cat.get("type", "")
            labels = stat_cat.get("labels", [])
            athletes = stat_cat.get("athletes", [])

            if not athletes:
                continue

            if cat_type == "batting":
                lines.append("**Batting**")
                lines.append("")
                label_map = {l: i for i, l in enumerate(labels)}
                ab_i = label_map.get("AB", 1)
                r_i = label_map.get("R", 2)
                h_i = label_map.get("H", 3)
                rbi_i = label_map.get("RBI", 4)
                hr_i = label_map.get("HR", 5)
                bb_i = label_map.get("BB", 6)
                k_i = label_map.get("K", 7)
                avg_i = label_map.get("AVG", 8)

                # Header line
                lines.append("`Player            AB  R  H RBI HR BB  K  AVG`")
                for ath in athletes:
                    name = ath.get("athlete", {}).get("shortName", ath.get("athlete", {}).get("displayName", "?"))
                    stats = ath.get("stats", [])
                    if not stats:
                        continue
                    def _g(i, w=2):
                        v = stats[i] if i < len(stats) else "-"
                        return str(v).rjust(w)
                    lines.append(
                        f"`{name:<18}{_g(ab_i)} {_g(r_i)} {_g(h_i)} {_g(rbi_i, 3)} {_g(hr_i)} {_g(bb_i)} {_g(k_i)} {_g(avg_i, 4)}`"
                    )
                lines.append("")

            elif cat_type == "pitching":
                lines.append("**Pitching**")
                lines.append("")
                label_map = {l: i for i, l in enumerate(labels)}
                ip_i = label_map.get("IP", 0)
                h_i = label_map.get("H", 1)
                r_i = label_map.get("R", 2)
                er_i = label_map.get("ER", 3)
                bb_i = label_map.get("BB", 4)
                k_i = label_map.get("K", 5)
                hr_i = label_map.get("HR", 6)
                era_i = label_map.get("ERA", 8)

                lines.append("`Pitcher            IP   H  R ER BB  K HR  ERA`")
                for ath in athletes:
                    name = ath.get("athlete", {}).get("shortName", ath.get("athlete", {}).get("displayName", "?"))
                    stats = ath.get("stats", [])
                    if not stats:
                        continue
                    def _g(i, w=2):
                        v = stats[i] if i < len(stats) else "-"
                        return str(v).rjust(w)
                    lines.append(
                        f"`{name:<18}{_g(ip_i, 4)} {_g(h_i)} {_g(r_i)} {_g(er_i)} {_g(bb_i)} {_g(k_i)} {_g(hr_i)} {_g(era_i, 4)}`"
                    )
                lines.append("")

    return "\n".join(lines)


# ---- ESPN Response Parsing ---------------------------------------------------

def _parse_espn_event(event: dict, league_name: str) -> Optional[dict]:
    """Parse a single ESPN event into a clean score dict."""
    competitions = event.get("competitions", [])
    if not competitions:
        return None
    
    competition = competitions[0]
    competitors = competition.get("competitors", [])

    # Detect event type:
    # - UFC/MMA: multiple competitions per event, competitors have no homeAway
    # - Golf/F1/Tennis: single competition, many competitors or no homeAway
    # - Team sports: single competition, 2 competitors with homeAway set
    
    is_fight_card = (
        len(competitions) > 2  # Multiple fights = UFC card
        or (len(competitors) >= 2 and all(c.get("homeAway") is None for c in competitors)
            and ("ufc" in league_name.lower() or "fighting" in league_name.lower() or "mma" in league_name.lower()))
    )
    
    if is_fight_card:
        return _parse_individual_event(event, league_name)

    if len(competitors) < 2:
        return _parse_individual_event(event, league_name)
    
    # Check if it's actually a team sport (has homeAway) vs individual (no homeAway)
    has_home_away = any(c.get("homeAway") for c in competitors)
    if not has_home_away:
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

    # Records
    away_record = away.get("records", [{}])[0].get("summary") if away.get("records") else None
    home_record = home.get("records", [{}])[0].get("summary") if home.get("records") else None
    if away_record:
        result["away_record"] = away_record
    if home_record:
        result["home_record"] = home_record

    # --- Pitching matchup (MLB) ---
    for side, competitor, key in [("home", home, "home_pitcher"), ("away", away, "away_pitcher")]:
        for prob in competitor.get("probables", []):
            if prob.get("name") == "probableStartingPitcher":
                ath = prob.get("athlete", {})
                pitcher_info = {"name": ath.get("fullName", "TBD")}
                if prob.get("record"):
                    pitcher_info["record"] = prob["record"]
                for stat in prob.get("statistics", []):
                    abbr = stat.get("abbreviation", "")
                    if abbr == "ERA":
                        pitcher_info["era"] = stat.get("displayValue")
                    elif abbr == "W":
                        pitcher_info["wins"] = stat.get("displayValue")
                    elif abbr == "L":
                        pitcher_info["losses"] = stat.get("displayValue")
                result[key] = pitcher_info

    # Current pitcher (in-game situation)
    situation = competition.get("situation", {})
    if situation:
        current_pitcher = situation.get("pitcher", {})
        if current_pitcher:
            ath = current_pitcher.get("athlete", {})
            if ath.get("fullName"):
                result["current_pitcher"] = {
                    "name": ath["fullName"],
                    "summary": current_pitcher.get("summary", ""),
                }

    return result


def _parse_individual_event(event: dict, league_name: str) -> Optional[dict]:
    """Parse individual-competitor events (golf, F1, tennis, UFC)."""
    name = event.get("name", event.get("shortName", ""))
    status_obj = event.get("status", {})
    status_text = status_obj.get("type", {}).get("shortDetail", "")

    competitions = event.get("competitions", [])
    
    # UFC/MMA: multiple fights per event card
    if "ufc" in league_name.lower() or "fighting" in league_name.lower() or "mma" in league_name.lower():
        fights = []
        for comp in competitions:
            fighters = comp.get("competitors", [])
            if len(fighters) >= 2:
                f1 = fighters[0]
                f2 = fighters[1]
                f1_name = f1.get("athlete", {}).get("displayName", "?")
                f2_name = f2.get("athlete", {}).get("displayName", "?")
                winner = None
                if f1.get("winner"):
                    winner = f1_name
                elif f2.get("winner"):
                    winner = f2_name
                fight_status = comp.get("status", {}).get("type", {}).get("shortDetail", "")
                fights.append({
                    "fighter1": f1_name,
                    "fighter2": f2_name,
                    "winner": winner,
                    "status": fight_status,
                })
        return {
            "sport": league_name,
            "event": name,
            "status": status_text,
            "fights": fights,
            "leaders": None,
        }

    # Golf, F1, Tennis: single competition with ranked competitors
    competitors = competitions[0].get("competitors", []) if competitions else []
    top = []
    for c in competitors[:5]:
        athlete = c.get("athlete", {})
        display = athlete.get("displayName", c.get("team", {}).get("displayName", "?"))
        score = c.get("score", "")
        if not score and c.get("linescores"):
            score = c["linescores"][-1].get("value", "")
        top.append({"name": display, "score": str(score) if score else ""})

    return {
        "sport": league_name,
        "event": name,
        "status": status_text,
        "leaders": top if top else None,
    }


def _safe_int(val) -> int:
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

    status_lower = status.lower()
    is_final = _is_final(game)
    is_live = _is_live(game)
    is_scheduled = not is_final and not is_live

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
        # Show current pitcher if available
        current = game.get("current_pitcher")
        if current:
            summary = f" ({current['summary']})" if current.get("summary") else ""
            lines.append("")
            lines.append(f"⚾ Pitching: **{current['name']}**{summary}")
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

    # Pitching matchup
    away_pitcher = game.get("away_pitcher")
    home_pitcher = game.get("home_pitcher")
    if away_pitcher or home_pitcher:
        lines.append("")
        lines.append("**Pitching Matchup**")
        for team_name, pitcher in [(away, away_pitcher), (home, home_pitcher)]:
            if pitcher:
                record = pitcher.get("record", "")
                era = pitcher.get("era", "")
                stat_str = f" — {record}" if record else (f" — {era} ERA" if era else "")
                lines.append(f"- {team_name}: **{pitcher['name']}**{stat_str}")

    # Records
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

    individual = [g for g in games if "event" in g and "away_team" not in g]
    team_games = [g for g in games if "away_team" in g]

    if individual:
        for g in individual:
            event_name = g.get("event", "Unknown")
            status = g.get("status", "")
            leaders = g.get("leaders") or []
            fights = g.get("fights") or []
            status_icon = "✅" if _is_final(g) else "🔴" if _is_live(g) else "⏰"
            
            if fights:
                # UFC/MMA fight card
                lines.append(f"### {status_icon} {event_name}")
                lines.append("")
                for fight in fights:
                    f1 = fight["fighter1"]
                    f2 = fight["fighter2"]
                    winner = fight.get("winner")
                    if winner:
                        loser = f2 if winner == f1 else f1
                        lines.append(f"- **{winner}** def. {loser}")
                    else:
                        lines.append(f"- {f1} vs {f2} — {fight.get('status', 'Scheduled')}")
                lines.append("")
            elif leaders:
                top_names = ", ".join(
                    f"**{l['name']}**" + (f" ({l['score']})" if l.get('score') else "")
                    for l in leaders[:3]
                )
                lines.append(f"- {status_icon} {event_name} — {top_names}")
            else:
                lines.append(f"- {status_icon} {event_name} — {status or 'Scheduled'}")
        lines.append("")

    # Group by status
    live = [g for g in team_games if _is_live(g)]
    final = [g for g in team_games if _is_final(g)]
    scheduled = [g for g in team_games if not _is_live(g) and not _is_final(g)]

    if live:
        lines.append("### 🔴 Live")
        lines.append("")
        for g in live:
            lines.append("- " + _render_game_line(g))
        lines.append("")

    if final:
        lines.append("### ✅ Final")
        lines.append("")
        for g in final:
            lines.append("- " + _render_game_line(g))
        lines.append("")

    if scheduled:
        lines.append("### ⏰ Upcoming")
        lines.append("")
        for g in scheduled:
            lines.append("- " + _render_game_line(g))
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
        if away_score > home_score:
            return f"**{away} {away_score}** – {home_score} {home}"
        elif home_score > away_score:
            return f"{away} {away_score} – **{home_score} {home}**"
        else:
            return f"{away} {away_score} – {home_score} {home} (Tied)"
    elif _is_live(game):
        return f"🔴 {away} {away_score} – {home_score} {home} *({status})*"
    else:
        return f"{away} @ {home} — {status}"


def _is_live(game: dict) -> bool:
    status = game.get("status", "").lower().strip()
    if _is_final(game):
        return False
    if status in ("scheduled", "pre", "preview", ""):
        return False
    scores = game.get("away_score", 0) + game.get("home_score", 0)
    return (
        "live" in status
        or "in progress" in status
        or "inning" in status
        or "quarter" in status
        or ("half" in status and "final" not in status)
        or ("period" in status and "final" not in status)
        or (scores > 0 and ":" not in status and "pm" not in status and "am" not in status)
    )


def _is_final(game: dict) -> bool:
    status = game.get("status", "").lower().strip()
    return (
        "final" in status
        or status in ("ft", "full time", "ended", "complete", "completed", "post")
        or status.startswith("f/")
        or "after" in status
    )


# ---- Schedule (upcoming games) --------------------------------------------

MY_TEAMS = ["tigers", "lions", "pistons", "red wings", "michigan", "usmnt"]


async def get_sports_schedule(team: Optional[str] = None, sport: Optional[str] = None, days: int = 7) -> dict:
    """Get upcoming schedule for a team or league."""
    sport_path, league_path, team_filter = _resolve_league(team, sport)

    if sport_path is None:
        return _friendly_error(team_filter or "Specify a team or league for the schedule.")

    match_filter = _expand_team_filter(team_filter)
    today = date.today()
    upcoming_games = []

    for day_offset in range(days):
        check_date = today + timedelta(days=day_offset)
        date_str = check_date.strftime("%Y%m%d")
        url = f"{ESPN_BASE}/{sport_path}/{league_path}/scoreboard?dates={date_str}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    continue
                data = resp.json()
        except Exception:
            continue

        events = data.get("events", [])
        league_name = data.get("leagues", [{}])[0].get("name", league_path.upper())

        for event in events:
            game = _parse_espn_event(event, league_name)
            if not game:
                continue
            game["date"] = check_date.isoformat()

            if team_filter:
                away_lower = game.get("away_team", "").lower()
                home_lower = game.get("home_team", "").lower()
                if match_filter and (match_filter in away_lower or match_filter in home_lower):
                    upcoming_games.append(game)
            else:
                upcoming_games.append(game)

    if not upcoming_games:
        if team_filter:
            return {"_display": f"No upcoming games found for **{team_filter.title()}** in the next {days} days."}
        return {"_display": f"No upcoming games found in the next {days} days."}

    display = _render_schedule(team_filter, upcoming_games, days)
    return {"games": upcoming_games, "_display": display}


def _render_schedule(team_filter: Optional[str], games: list[dict], days: int) -> str:
    """Render upcoming schedule as markdown."""
    from itertools import groupby
    title = team_filter.title() if team_filter else games[0].get("sport", "Sports")
    lines = [f"## 📅 {title} — Upcoming Schedule", ""]

    for game_date, date_games in groupby(games, key=lambda g: g.get("date", "")):
        date_games_list = list(date_games)
        try:
            d = date.fromisoformat(game_date)
            if d == date.today():
                date_label = "Today"
            elif d == date.today() + timedelta(days=1):
                date_label = "Tomorrow"
            else:
                date_label = d.strftime("%a %b %-d")
        except (ValueError, TypeError):
            date_label = game_date

        lines.append(f"**{date_label}**")
        for g in date_games_list:
            away = g.get("away_team", "?")
            home = g.get("home_team", "?")
            status = g.get("status", "")

            if _is_final(g):
                away_score = g.get("away_score", 0)
                home_score = g.get("home_score", 0)
                lines.append(f"- ✅ {away} {away_score} – {home_score} {home}")
            elif _is_live(g):
                away_score = g.get("away_score", 0)
                home_score = g.get("home_score", 0)
                lines.append(f"- 🔴 {away} {away_score} – {home_score} {home} *({status})*")
            else:
                time_str = status if status and ":" in status else "TBD"
                lines.append(f"- {away} @ {home} — {time_str}")
        lines.append("")

    return "\n".join(lines)


async def get_my_teams_scores() -> dict:
    """Get scores for all of Michael's tracked teams."""
    results = []
    for team_name in MY_TEAMS:
        result = await get_sports_score(team=team_name)
        if result.get("away_team") or result.get("games"):
            results.append(result)

    if not results:
        return {"_display": "No recent games found for your tracked teams (Tigers, Lions, Pistons, Red Wings, Michigan, USMNT)."}

    lines = ["## 🏟️ My Teams — Latest Scores", ""]
    for r in results:
        if "away_team" in r:
            lines.append("- " + _render_game_line(r))
        elif "games" in r:
            for g in r["games"]:
                lines.append("- " + _render_game_line(g))
        elif "event" in r:
            lines.append(f"- {r['event']} — {r.get('status', '')}")
    lines.append("")

    return {"games": results, "_display": "\n".join(lines)}


async def get_my_teams_schedule(days: int = 7) -> dict:
    """Get upcoming schedule for all of Michael's tracked teams."""
    all_games = []
    for team_name in MY_TEAMS:
        result = await get_sports_schedule(team=team_name, days=days)
        games = result.get("games", [])
        all_games.extend(games)

    if not all_games:
        return {"_display": f"No upcoming games for your tracked teams in the next {days} days."}

    all_games.sort(key=lambda g: g.get("date", ""))
    display = _render_schedule(None, all_games, days)
    display = display.replace("## 📅 Sports — Upcoming Schedule", "## 📅 My Teams — Upcoming Schedule")
    return {"games": all_games, "_display": display}
