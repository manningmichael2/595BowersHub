"""Native skill: live sports data via ESPN API.

Handles multiple query types:
- score: live/recent game scores (default)
- boxscore: full batting/pitching lines for a specific game
- standings: division/league standings
- schedule: upcoming games
"""

from backend.services.skill_registry import native_skill


@native_skill("sports-score")
async def handle_sports_score(params: dict) -> dict:
    from backend.services.sports_score import get_sports_score, get_box_score

    query_type = (params.get("query_type") or params.get("type") or "score").lower().strip()
    team = params.get("team")
    sport = params.get("sport")

    if query_type in ("boxscore", "box score", "box", "stats", "batting", "pitching", "lines"):
        return await get_box_score(team=team, sport=sport)
    else:
        return await get_sports_score(team=team, sport=sport)
