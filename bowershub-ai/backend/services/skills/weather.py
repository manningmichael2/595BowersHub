"""Native skill: weather lookup via wttr.in."""

from backend.services.skill_registry import native_skill


@native_skill("weather", "get-weather")
async def handle_weather(params: dict) -> dict:
    from backend.services.weather import get_weather

    location = params.get("location") or params.get("city") or params.get("query")
    return await get_weather(location=location)
