"""
Calendar Service: read/write Google Calendar events via CalDAV + App Password.

Auth: Google account + App Password (same one used for Gmail IMAP/SMTP).
CalDAV URL: https://apidata.googleusercontent.com/caldav/v2/<email>/events/

Supports:
  - get_events(days_ahead)  — fetch events for today + N days
  - get_today_events()      — today only (used by briefing)
  - create_event(...)       — add an event to the calendar
"""

import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from backend.http_client import get_http_client

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CalDAV credentials (read from env at runtime)
# ──────────────────────────────────────────────

def _get_credentials() -> tuple[str, str, str]:
    """Return (url, user, password) from env vars, or raise ValueError if unconfigured."""
    url = os.environ.get("CALDAV_URL", "").strip()
    user = (os.environ.get("CALDAV_USER") or os.environ.get("GMAIL_SMTP_USER", "")).strip()
    password = (os.environ.get("CALDAV_PASSWORD") or os.environ.get("GMAIL_SMTP_PASSWORD", "")).strip()

    if not url:
        # Auto-construct Google CalDAV URL from user email if not explicitly set
        if user:
            url = f"https://www.google.com/calendar/dav/{user}/events/"
        else:
            raise ValueError("CALDAV_URL (or CALDAV_USER) not configured")

    if not user or not password:
        raise ValueError("CALDAV_USER / CALDAV_PASSWORD (or GMAIL_SMTP_USER / GMAIL_SMTP_PASSWORD) not configured")

    return url, user, password


def _is_configured() -> bool:
    """Returns True if CalDAV credentials are available."""
    try:
        _get_credentials()
        return True
    except ValueError:
        return False


# ──────────────────────────────────────────────
# iCal parsing helpers
# ──────────────────────────────────────────────

def _unfold_ical(text: str) -> str:
    """Unfold iCal line continuations (RFC 5545 §3.1)."""
    return re.sub(r"\r?\n[ \t]", "", text)


def _parse_ical_dt(dtstring: str, tzid: Optional[str] = None) -> Optional[datetime]:
    """
    Parse an iCal DTSTART/DTEND value into a UTC-aware datetime.
    Handles:
      - DATE-TIME with Z suffix       (20260607T140000Z)
      - DATE-TIME without suffix      (20260607T090000) — treated as local (Detroit/ET)
      - DATE (all-day)                (20260607) — returns None (all-day marker)
    """
    dtstring = dtstring.strip()
    if "T" not in dtstring:
        # All-day event — return None to signal no specific time
        return None
    try:
        if dtstring.endswith("Z"):
            dt = datetime.strptime(dtstring, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        else:
            # Floating time — assume Eastern (UTC-4 EDT / UTC-5 EST)
            dt = datetime.strptime(dtstring[:15], "%Y%m%dT%H%M%S")
            # Rough Eastern offset (close enough for display purposes)
            offset = -4 if 3 <= datetime.now().month <= 11 else -5
            dt = dt.replace(tzinfo=timezone(timedelta(hours=offset)))
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _parse_ical_date_only(dtstring: str) -> Optional[date]:
    """Parse a DATE or DATE-TIME value into a plain date (no time zone)."""
    dtstring = dtstring.strip()[:8]
    try:
        return datetime.strptime(dtstring, "%Y%m%d").date()
    except ValueError:
        return None


def _parse_events_from_xml(xml_text: str, range_start: date, range_end: date) -> List[Dict[str, Any]]:
    """
    Extract VEVENT blocks from a CalDAV REPORT response and return structured dicts.

    Each event dict:
      {
        "uid": str,
        "summary": str,
        "start": datetime | date,   # datetime = timed, date = all-day
        "end": datetime | date | None,
        "location": str | None,
        "description": str | None,
        "all_day": bool,
        "display_time": str,        # human-readable, e.g. "9:00 AM" or "All day"
        "display_date": str,        # e.g. "Mon Jun 7"
        "_sort_key": str,
      }
    """
    events = []
    vevent_re = re.compile(r"BEGIN:VEVENT(.*?)END:VEVENT", re.DOTALL)

    for match in vevent_re.finditer(xml_text):
        block = _unfold_ical(match.group(1))

        def _prop(name: str) -> Optional[str]:
            """Extract a property value, handling parameterized names like DTSTART;TZID=..."""
            m = re.search(rf"^{name}[^:]*:(.*)", block, re.MULTILINE)
            return m.group(1).strip() if m else None

        def _prop_with_param(name: str) -> tuple[Optional[str], Optional[str]]:
            """Return (param_value, field_value) for parameterized props like DTSTART;TZID=America/New_York:..."""
            m = re.search(rf"^{name}(?:;([^:]+))?:(.*)", block, re.MULTILINE)
            if not m:
                return None, None
            param = m.group(1)  # e.g. "TZID=America/New_York"
            val = m.group(2).strip()
            tzid = None
            if param and param.startswith("TZID="):
                tzid = param.split("=", 1)[1]
            return tzid, val

        uid = _prop("UID") or str(uuid.uuid4())
        summary = _prop("SUMMARY") or "Untitled"
        location = _prop("LOCATION")
        description = _prop("DESCRIPTION")

        # DTSTART
        tzid, dtstart_val = _prop_with_param("DTSTART")
        if not dtstart_val:
            continue  # malformed

        # Determine if all-day
        all_day = "T" not in dtstart_val

        if all_day:
            event_date = _parse_ical_date_only(dtstart_val)
            if not event_date:
                continue
            # Check if this date is within our requested range
            if not (range_start <= event_date <= range_end):
                continue
            event_start = event_date
            display_time = "All day"
            display_date = event_date.strftime("%a %b %-d")
            sort_key = f"{event_date.isoformat()} 00:00"
        else:
            dt = _parse_ical_dt(dtstart_val, tzid)
            if not dt:
                continue
            # Convert to Detroit local time for display
            et_offset = -4 if 3 <= dt.month <= 11 else -5
            local_dt = dt.astimezone(timezone(timedelta(hours=et_offset)))
            event_date = local_dt.date()
            if not (range_start <= event_date <= range_end):
                continue
            event_start = local_dt
            display_time = local_dt.strftime("%-I:%M %p")
            display_date = local_dt.strftime("%a %b %-d")
            sort_key = f"{event_date.isoformat()} {local_dt.strftime('%H:%M')}"

        # DTEND (optional for display)
        _, dtend_val = _prop_with_param("DTEND")
        event_end = None
        if dtend_val:
            if "T" in dtend_val:
                event_end = _parse_ical_dt(dtend_val)
            else:
                event_end = _parse_ical_date_only(dtend_val)

        events.append({
            "uid": uid,
            "summary": summary,
            "start": event_start,
            "end": event_end,
            "location": location,
            "description": description,
            "all_day": all_day,
            "display_time": display_time,
            "display_date": display_date,
            "_sort_key": sort_key,
        })

    # Sort chronologically
    events.sort(key=lambda e: e["_sort_key"])
    return events


# ──────────────────────────────────────────────
# CalDAV HTTP helpers
# ──────────────────────────────────────────────

def _build_report_body(start_utc: datetime, end_utc: datetime) -> str:
    """Build a CalDAV calendar-query REPORT body for a time range."""
    fmt = "%Y%m%dT%H%M%SZ"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <D:getetag/>
    <C:calendar-data/>
  </D:prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT">
        <C:time-range start="{start_utc.strftime(fmt)}" end="{end_utc.strftime(fmt)}"/>
      </C:comp-filter>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>"""


async def _fetch_events_raw(
    url: str, user: str, password: str, start: datetime, end: datetime
) -> str:
    """Perform a CalDAV REPORT request and return the raw response body."""
    body = _build_report_body(start, end)
    client = get_http_client()
    resp = await client.request(
        method="REPORT",
        url=url,
        content=body.encode("utf-8"),
        headers={
            "Content-Type": "application/xml; charset=utf-8",
            "Depth": "1",
        },
        auth=(user, password),
    )
    if resp.status_code not in (200, 207):
        raise RuntimeError(
            f"CalDAV REPORT returned HTTP {resp.status_code}: {resp.text[:300]}"
        )
    return resp.text


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

async def get_events(days_ahead: int = 7) -> Dict[str, Any]:
    """
    Fetch calendar events for today + `days_ahead` days.
    Returns a dict with a `_display` key for direct rendering in chat.
    """
    if not _is_configured():
        return {"error": "Calendar not configured", "_display": "⚠️ Calendar not configured. Set CALDAV_USER and CALDAV_PASSWORD in your .env file."}

    try:
        url, user, password = _get_credentials()

        today = date.today()
        end_date = today + timedelta(days=days_ahead)

        start_utc = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_utc = datetime.combine(end_date + timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone.utc)

        xml = await _fetch_events_raw(url, user, password, start_utc, end_utc)
        events = _parse_events_from_xml(xml, today, end_date)

        return {
            "events": events,
            "count": len(events),
            "_display": _format_events_display(events, today, days_ahead),
        }

    except ValueError as e:
        return {"error": str(e), "_display": f"⚠️ {e}"}
    except RuntimeError as e:
        return {"error": str(e), "_display": f"⚠️ Could not reach Google Calendar: {e}"}
    except Exception as e:
        logger.exception("Calendar get_events failed")
        return {"error": str(e), "_display": "⚠️ Calendar fetch failed — check logs."}


async def get_today_events() -> List[Dict[str, Any]]:
    """
    Fetch today's events only. Returns a plain list (used by briefing).
    Returns [] on any error.
    """
    if not _is_configured():
        return []
    try:
        url, user, password = _get_credentials()
        today = date.today()
        start_utc = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_utc = datetime.combine(today + timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone.utc)
        xml = await _fetch_events_raw(url, user, password, start_utc, end_utc)
        return _parse_events_from_xml(xml, today, today)
    except Exception as e:
        logger.warning(f"get_today_events failed: {e}")
        return []


async def create_event(
    summary: str,
    start: datetime,
    end: Optional[datetime] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    all_day: bool = False,
) -> Dict[str, Any]:
    """
    Create a new calendar event.

    For timed events, pass timezone-aware datetimes (or naive Eastern times).
    For all-day events, set all_day=True and pass a date via start (time is ignored).

    Returns a dict with `ok`, `uid`, and `_display`.
    """
    if not _is_configured():
        return {"ok": False, "error": "Calendar not configured", "_display": "⚠️ Calendar not configured."}

    try:
        url, user, password = _get_credentials()
        event_uid = str(uuid.uuid4())
        now_utc = datetime.now(timezone.utc)

        if all_day:
            # DATE format
            start_date = start.date() if isinstance(start, datetime) else start
            end_date = (start_date + timedelta(days=1))
            dtstart_str = f"DTSTART;VALUE=DATE:{start_date.strftime('%Y%m%d')}"
            dtend_str = f"DTEND;VALUE=DATE:{end_date.strftime('%Y%m%d')}"
            display_str = start_date.strftime("%A, %B %-d")
        else:
            # Ensure UTC
            if start.tzinfo is None:
                # Treat as Eastern time
                et_offset = -4 if 3 <= start.month <= 11 else -5
                start = start.replace(tzinfo=timezone(timedelta(hours=et_offset)))
            start_utc = start.astimezone(timezone.utc)

            if end is None:
                end = start + timedelta(hours=1)
            if end.tzinfo is None:
                et_offset = -4 if 3 <= end.month <= 11 else -5
                end = end.replace(tzinfo=timezone(timedelta(hours=et_offset)))
            end_utc = end.astimezone(timezone.utc)

            dtstart_str = f"DTSTART:{start_utc.strftime('%Y%m%dT%H%M%SZ')}"
            dtend_str = f"DTEND:{end_utc.strftime('%Y%m%dT%H%M%SZ')}"

            # Display in Eastern
            et_offset = -4 if 3 <= start_utc.month <= 11 else -5
            local_start = start_utc.astimezone(timezone(timedelta(hours=et_offset)))
            display_str = local_start.strftime("%A, %B %-d at %-I:%M %p ET")

        # Build iCal VEVENT
        ical_lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//BowersHub AI//EN",
            "BEGIN:VEVENT",
            f"UID:{event_uid}@bowershub.ai",
            f"DTSTAMP:{now_utc.strftime('%Y%m%dT%H%M%SZ')}",
            dtstart_str,
            dtend_str,
            f"SUMMARY:{summary}",
        ]
        if description:
            # Escape special chars per RFC 5545
            desc_escaped = description.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")
            ical_lines.append(f"DESCRIPTION:{desc_escaped}")
        if location:
            loc_escaped = location.replace("\\", "\\\\").replace(",", "\\,")
            ical_lines.append(f"LOCATION:{loc_escaped}")
        ical_lines += ["END:VEVENT", "END:VCALENDAR"]

        ical_body = "\r\n".join(ical_lines) + "\r\n"
        event_url = url.rstrip("/") + f"/{event_uid}.ics"

        client = get_http_client()
        resp = await client.put(
            event_url,
            content=ical_body.encode("utf-8"),
            headers={"Content-Type": "text/calendar; charset=utf-8"},
            auth=(user, password),
        )
        if resp.status_code not in (200, 201, 204):
            raise RuntimeError(f"CalDAV PUT returned HTTP {resp.status_code}: {resp.text[:300]}")

        return {
            "ok": True,
            "uid": event_uid,
            "_display": f"✅ Event created: **{summary}** — {display_str}",
        }

    except ValueError as e:
        return {"ok": False, "error": str(e), "_display": f"⚠️ {e}"}
    except RuntimeError as e:
        return {"ok": False, "error": str(e), "_display": f"⚠️ Could not create event: {e}"}
    except Exception as e:
        logger.exception("Calendar create_event failed")
        return {"ok": False, "error": str(e), "_display": "⚠️ Calendar create failed — check logs."}


# ──────────────────────────────────────────────
# Display formatting
# ──────────────────────────────────────────────

def _format_events_display(events: List[Dict[str, Any]], today: date, days_ahead: int) -> str:
    """Format events list as a nice markdown display for chat."""
    if not events:
        span = "today" if days_ahead == 0 else f"the next {days_ahead + 1} days"
        return f"📅 No events scheduled for {span}."

    # Group by date
    by_date: Dict[str, List[Dict]] = {}
    for e in events:
        key = e["display_date"]
        by_date.setdefault(key, []).append(e)

    lines = ["**📅 Calendar**\n"]
    for date_label, day_events in by_date.items():
        is_today = day_events[0]["_sort_key"].startswith(today.isoformat())
        heading = f"**{'Today — ' if is_today else ''}{date_label}**"
        lines.append(heading)
        for ev in day_events:
            time_part = ev["display_time"]
            summary = ev["summary"]
            loc = f" _(at {ev['location']})_" if ev.get("location") else ""
            lines.append(f"- {time_part} — {summary}{loc}")
        lines.append("")

    return "\n".join(lines).rstrip()
