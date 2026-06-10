"""
Simple reminder time parser.

Parses natural-language time expressions into absolute datetimes.
Examples:
- "in 30 minutes check the oven" → (now + 30min, "check the oven")
- "in 2 hours call the dentist" → (now + 2h, "call the dentist")
- "tomorrow at 9am review budget" → (tomorrow 9am, "review budget")
- "at 5pm pick up groceries" → (today/tomorrow 5pm, "pick up groceries")
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

# Eastern timezone offset (UTC-4 in summer, UTC-5 in winter)
# Simple approach: use -4 for EDT (June is summer)
EDT = timezone(timedelta(hours=-4))


def parse_reminder(text: str) -> Optional[Tuple[datetime, str]]:
    """
    Parse a reminder string into (deliver_at, message).
    Returns None if parsing fails.
    """
    text = text.strip()
    if not text:
        return None

    now = datetime.now(EDT)

    # Pattern: "in N minutes/hours/days ..."
    m = re.match(
        r'^in\s+(\d+)\s+(minutes?|mins?|hours?|hrs?|days?)\s+(.+)$',
        text, re.IGNORECASE,
    )
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        message = m.group(3).strip()
        if unit.startswith("min"):
            delta = timedelta(minutes=amount)
        elif unit.startswith("h"):
            delta = timedelta(hours=amount)
        elif unit.startswith("d"):
            delta = timedelta(days=amount)
        else:
            return None
        return (now + delta, message)

    # Pattern: "tomorrow at HH:MM[am/pm] ..."
    m = re.match(
        r'^tomorrow\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+(.+)$',
        text, re.IGNORECASE,
    )
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = (m.group(3) or "").lower()
        message = m.group(4).strip()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        tomorrow = now + timedelta(days=1)
        target = tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return (target, message)

    # Pattern: "at HH:MM[am/pm] ..." (today, or tomorrow if time has passed)
    m = re.match(
        r'^at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+(.+)$',
        text, re.IGNORECASE,
    )
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = (m.group(3) or "").lower()
        message = m.group(4).strip()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)  # If time already passed, use tomorrow
        return (target, message)

    # Pattern: just "N minutes ..." or "N hours ..."
    m = re.match(
        r'^(\d+)\s+(minutes?|mins?|hours?|hrs?)\s+(.+)$',
        text, re.IGNORECASE,
    )
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        message = m.group(3).strip()
        if unit.startswith("min"):
            delta = timedelta(minutes=amount)
        elif unit.startswith("h"):
            delta = timedelta(hours=amount)
        else:
            return None
        return (now + delta, message)

    return None
