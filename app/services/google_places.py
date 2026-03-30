"""Google Places API service — fetches opening hours via Text Search."""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def get_opening_hours(lat: float, lon: float, name: str) -> str | None:
    """
    Use Google Places Text Search (New) to find opening hours for a place.

    Returns the opening_hours weekday_text joined as a string, or None.
    """
    if not settings.google_places_api_key:
        return None

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.google_places_api_key,
        "X-Goog-FieldMask": "places.currentOpeningHours,places.regularOpeningHours",
    }
    body = {
        "textQuery": name,
        "locationBias": {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": 500.0,
            }
        },
        "maxResultCount": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        places = data.get("places", [])
        if not places:
            return None

        place = places[0]
        hours = place.get("regularOpeningHours") or place.get("currentOpeningHours")
        if not hours:
            return None

        weekday_text = hours.get("weekdayDescriptions")
        if weekday_text:
            return "; ".join(weekday_text)

        return None
    except Exception:
        logger.exception("Google Places API error for %s", name)
        return None
