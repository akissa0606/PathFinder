import logging
import re
from datetime import date, datetime, time, timedelta

from app.engine.category_defaults import get_duration_minutes

logger = logging.getLogger(__name__)


def calculate_feasibility(
    place: dict,
    travel_to_place_seconds: float,
    travel_to_endpoint_seconds: float,
    current_time: datetime,
    trip_end_time: datetime,
    trip_date: date,
) -> dict:
    """
    Calculate feasibility for a single place.

    Args:
        place: dict with keys: id, category, estimated_duration_min, opening_hours, status
        travel_to_place_seconds: OSRM duration from current position to this place
        travel_to_endpoint_seconds: OSRM duration from this place to trip endpoint
        current_time: current datetime
        trip_end_time: datetime when trip ends
        trip_date: date of the trip

    Returns dict with: place_id, color, slack_minutes, closing_urgency_minutes, reason
    """
    visit_duration_min = get_duration_minutes(
        place.get("category"), place.get("estimated_duration_min")
    )
    visit_duration_sec = visit_duration_min * 60

    travel_to = travel_to_place_seconds
    arrival_at_place = current_time + timedelta(seconds=travel_to)
    departure_from_place = arrival_at_place + timedelta(seconds=visit_duration_sec)
    travel_back = travel_to_endpoint_seconds
    finish_time = departure_from_place + timedelta(seconds=travel_back)

    # Slack
    slack_seconds = (trip_end_time - finish_time).total_seconds()
    remaining_seconds = (trip_end_time - current_time).total_seconds()
    slack_ratio = slack_seconds / remaining_seconds if remaining_seconds > 0 else 0

    # Opening hours
    closing_time = None
    closing_urgency = None
    window_remaining = None

    if place.get("opening_hours"):
        closing_time = parse_closing_time(place["opening_hours"], trip_date)
        if closing_time:
            closing_urgency = (closing_time - arrival_at_place).total_seconds()
            window_remaining = (closing_time - current_time).total_seconds()

    # Color logic
    if slack_seconds < 0:
        color = "gray"
        reason = "Not enough time to visit and reach endpoint"
    elif closing_time and arrival_at_place > closing_time:
        color = "gray"
        reason = f"Closed by the time you arrive ({arrival_at_place.strftime('%H:%M')})"
    elif closing_time and window_remaining is not None and window_remaining < 30 * 60:
        color = "red"
        reason = f"Closes in {_format_duration(window_remaining)}"
    elif slack_ratio < 0.10:
        color = "red"
        reason = "Very tight schedule"
    elif (
        closing_time
        and window_remaining is not None
        and window_remaining < 2 * 60 * 60
    ):
        color = "yellow"
        reason = f"Closes in {_format_duration(window_remaining)}"
    elif slack_ratio < 0.30:
        color = "yellow"
        reason = "Feasible but limited time"
    elif not place.get("opening_hours"):
        color = "unknown"
        reason = "No opening hours data — time-feasible"
    else:
        color = "green"
        reason = "Plenty of time"

    return {
        "place_id": place["id"],
        "color": color,
        "slack_minutes": round(slack_seconds / 60, 1),
        "closing_urgency_minutes": (
            round(closing_urgency / 60, 1) if closing_urgency is not None else None
        ),
        "reason": reason,
    }


def parse_closing_time(opening_hours: str, trip_date: date) -> datetime | None:
    """
    Parse OSM opening_hours format to extract closing time for the given date.

    Handles common formats like:
    - "Mo-Fr 09:00-17:00"
    - "Mo-Su 10:00-18:00"
    - "09:00-17:00"
    - "Mo-Fr 09:00-17:00; Sa 10:00-14:00"

    Returns datetime of closing time on trip_date, or None if unparseable.
    """
    DAY_MAP = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}
    weekday = trip_date.weekday()

    rules = [r.strip() for r in opening_hours.split(";")]

    for rule in rules:
        time_match = re.search(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", rule)
        if not time_match:
            continue

        close_str = time_match.group(2)
        day_part = rule[: time_match.start()].strip().rstrip(",").strip()

        if day_part:
            if _day_matches(day_part, weekday, DAY_MAP):
                h, m = close_str.split(":")
                return datetime.combine(trip_date, time(int(h), int(m)))
        else:
            h, m = close_str.split(":")
            return datetime.combine(trip_date, time(int(h), int(m)))

    return None


def _day_matches(day_part: str, weekday: int, day_map: dict) -> bool:
    """Check if weekday matches day specification like 'Mo-Fr', 'Sa,Su', 'Mo'."""
    segments = [s.strip() for s in day_part.split(",")]
    for seg in segments:
        range_match = re.match(r"([A-Z][a-z])\s*-\s*([A-Z][a-z])", seg)
        if range_match:
            start_day = day_map.get(range_match.group(1))
            end_day = day_map.get(range_match.group(2))
            if start_day is not None and end_day is not None:
                if start_day <= end_day:
                    if start_day <= weekday <= end_day:
                        return True
                else:
                    if weekday >= start_day or weekday <= end_day:
                        return True
        else:
            single = day_map.get(seg.strip())
            if single is not None and single == weekday:
                return True
    return False


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    minutes = int(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    mins = minutes % 60
    if mins:
        return f"{hours}h {mins}min"
    return f"{hours}h"
