"""Native skill: weather lookup via wttr.in."""

from backend.services.skill_registry import native_skill


@native_skill("weather", "get-weather")
async def handle_weather(params: dict) -> dict:
    from backend.services.weather import get_weather

    location = params.get("location") or params.get("city") or params.get("query")
    # Fall back to the user's saved settings_json["location"] when none is given.
    return await get_weather(location=location, user_id=params.get("_user_id"))
