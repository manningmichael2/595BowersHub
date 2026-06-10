"""Native skill: Google Calendar read/write via CalDAV + App Password."""

from backend.services.skill_registry import native_skill


@native_skill("calendar", "get-calendar", "schedule")
async def handle_calendar(params: dict) -> dict:
    """
    Fetch calendar events.

    Params:
      days (int): how many days ahead to look (default 7)
      query (str): optional — "today", "tomorrow", "week", "next week", or a number
    """
    from backend.services.calendar import get_events

    # Parse days from various param shapes
    days = 7  # default
    raw = params.get("days") or params.get("query") or params.get("range") or ""
    raw = str(raw).strip().lower()

    if raw in ("today",):
        days = 0
    elif raw in ("tomorrow",):
        days = 1
    elif raw in ("week", "this week"):
        days = 6
    elif raw in ("next week",):
        days = 13
    else:
        try:
            days = int(raw)
        except (ValueError, TypeError):
            pass  # stick with default of 7

    return await get_events(days_ahead=days)


@native_skill("calendar-create", "add-event", "create-event")
async def handle_calendar_create(params: dict) -> dict:
    """
    Create a calendar event.

    Params:
      summary (str): event title (required)
      start (str): ISO datetime or "YYYY-MM-DD HH:MM" (required)
      end (str): ISO datetime or "YYYY-MM-DD HH:MM" (optional, defaults to 1 hour after start)
      description (str): event notes (optional)
      location (str): event location (optional)
      all_day (bool): if true, creates an all-day event (optional)
    """
    from backend.services.calendar import create_event
    from datetime import datetime

    summary = params.get("summary") or params.get("title") or params.get("name")
    if not summary:
        return {"ok": False, "_display": "⚠️ Event title (summary) is required."}

    start_str = params.get("start") or params.get("start_time") or params.get("date")
    if not start_str:
        return {"ok": False, "_display": "⚠️ Event start time is required."}

    # Parse start datetime — accept ISO format or human-readable "YYYY-MM-DD HH:MM"
    start_dt = None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            start_dt = datetime.strptime(str(start_str).strip(), fmt)
            break
        except ValueError:
            continue

    if not start_dt:
        return {"ok": False, "_display": f"⚠️ Could not parse start time: `{start_str}`. Use format: `YYYY-MM-DD HH:MM`"}

    # Parse optional end time
    end_dt = None
    end_str = params.get("end") or params.get("end_time")
    if end_str:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
            try:
                end_dt = datetime.strptime(str(end_str).strip(), fmt)
                break
            except ValueError:
                continue

    all_day = bool(params.get("all_day") or params.get("allday"))
    description = params.get("description") or params.get("notes")
    location = params.get("location")

    return await create_event(
        summary=summary,
        start=start_dt,
        end=end_dt,
        description=description,
        location=location,
        all_day=all_day,
    )
