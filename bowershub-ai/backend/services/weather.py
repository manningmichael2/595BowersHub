"""
Weather skill — current conditions + forecast via wttr.in.

Accepts any location (city, zip, airport code, landmark).
Defaults to user's home location if none specified.

wttr.in is free, no API key needed, supports thousands of locations.
"""
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Default location when the user just says "/weather" with no argument
DEFAULT_LOCATION = "Detroit,MI"


async def get_weather(location: Optional[str] = None) -> dict:
    """
    Get current weather + 3-day forecast for a location.
    
    Args:
        location: City, zip, airport code, or landmark. 
                  Examples: "New Orleans", "10001", "LAX", "Eiffel Tower"
                  Defaults to Detroit,MI if not specified.
    """
    loc = (location or "").strip() or DEFAULT_LOCATION

    # wttr.in with format=j1 returns structured JSON
    url = f"https://wttr.in/{loc}?format=j1"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"User-Agent": "curl/8.0"})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Location not found: '{loc}'. Try a city name, zip code, or airport code."}
        return {"error": f"Weather service returned {e.response.status_code}"}
    except Exception as e:
        return {"error": f"Weather service unavailable: {e}"}

    return _format_weather(data, loc)


def _format_weather(data: dict, location: str) -> dict:
    """Parse wttr.in JSON into a clean weather result with beautiful display."""
    current = data.get("current_condition", [{}])[0]
    nearest = data.get("nearest_area", [{}])[0]
    forecast_days = data.get("weather", [])

    # Resolve actual location name
    area_name = nearest.get("areaName", [{}])[0].get("value", location)
    region = nearest.get("region", [{}])[0].get("value", "")
    country = nearest.get("country", [{}])[0].get("value", "")
    resolved_location = area_name
    if region and region != area_name:
        resolved_location += f", {region}"
    elif country:
        resolved_location += f", {country}"

    # Current conditions
    temp_f = int(current.get("temp_F", 0))
    feels_f = int(current.get("FeelsLikeF", 0))
    condition = current.get("weatherDesc", [{}])[0].get("value", "Unknown")
    humidity = current.get("humidity", "?")
    wind_mph = current.get("windspeedMiles", "?")
    wind_dir = current.get("winddir16Point", "")
    uv = current.get("uvIndex", "?")

    # Weather emoji
    emoji = _condition_emoji(condition)

    # Build beautiful display
    lines = [
        f"## {emoji} {resolved_location}",
        "",
        f"**{temp_f}°F** — {condition}",
        f"Feels like {feels_f}°F · Humidity {humidity}% · Wind {wind_mph} mph {wind_dir} · UV {uv}",
        "",
    ]

    # 3-day forecast
    if forecast_days:
        lines.append("---")
        lines.append("")
        for i, day in enumerate(forecast_days[:3]):
            date_str = day.get("date", "")
            max_f = day.get("maxtempF", "?")
            min_f = day.get("mintempF", "?")
            hourly = day.get("hourly", [])
            noon = hourly[4] if len(hourly) > 4 else hourly[0] if hourly else {}
            desc = noon.get("weatherDesc", [{}])[0].get("value", "")
            rain = noon.get("chanceofrain", "0")
            snow = noon.get("chanceofsnow", "0")
            day_emoji = _condition_emoji(desc)

            # Position-based labels — immune to timezone issues
            if i == 0:
                day_label = "Today"
            elif i == 1:
                day_label = "Tomorrow"
            else:
                # For day 3+, derive from the date string directly
                try:
                    from datetime import datetime as _dt
                    day_label = _dt.strptime(date_str, "%Y-%m-%d").strftime("%A")
                except Exception:
                    day_label = date_str

            forecast_line = f"**{day_label}** — {day_emoji} {desc}, {min_f}°–{max_f}°F"
            extras = []
            if int(rain) > 20:
                extras.append(f"🌧 {rain}%")
            if int(snow) > 10:
                extras.append(f"❄️ {snow}%")
            if extras:
                forecast_line += f" ({', '.join(extras)})"
            lines.append(forecast_line)

    display = "\n".join(lines)

    return {
        "location": resolved_location,
        "temp_f": temp_f,
        "condition": condition,
        "_display": display,
    }


def _condition_emoji(condition: str) -> str:
    """Map weather condition text to an emoji."""
    c = condition.lower()
    if "sun" in c or "clear" in c:
        return "☀️"
    if "partly" in c or "partly cloudy" in c:
        return "⛅"
    if "cloud" in c or "overcast" in c:
        return "☁️"
    if "rain" in c or "drizzle" in c or "shower" in c:
        return "🌧"
    if "thunder" in c or "storm" in c:
        return "⛈️"
    if "snow" in c or "sleet" in c or "ice" in c:
        return "❄️"
    if "fog" in c or "mist" in c or "haze" in c:
        return "🌫"
    if "wind" in c:
        return "💨"
    return "🌤"


def _format_date_label(date_str: str) -> str:
    """Turn YYYY-MM-DD into a friendly label like 'Today', 'Tomorrow', 'Saturday'."""
    from datetime import datetime
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = date.today()
        diff = (d - today).days
        if diff == 0:
            return "Today"
        if diff == 1:
            return "Tomorrow"
        return d.strftime("%A")  # Day name
    except Exception:
        return date_str
