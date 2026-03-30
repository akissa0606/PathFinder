"""Opening hours resolution — OSM first, Google Places fallback."""

import logging

from app.services import google_places, overpass

logger = logging.getLogger(__name__)


async def resolve_opening_hours(
    lat: float, lon: float, name: str
) -> tuple[str | None, str | None]:
    """
    Try Overpass (OSM) first, then Google Places as fallback.

    Returns:
        (opening_hours_string, source) or (None, None).
    """
    try:
        result = await overpass.get_opening_hours(lat, lon, name)
        if result and result.get("opening_hours"):
            return result["opening_hours"], "osm"
    except Exception:
        logger.exception("Overpass lookup failed for %s", name)

    try:
        hours = await google_places.get_opening_hours(lat, lon, name)
        if hours:
            return hours, "google"
    except Exception:
        logger.exception("Google Places lookup failed for %s", name)

    return None, None
