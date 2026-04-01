"""OSRM service — travel time matrix for foot/car/bicycle profiles."""

from typing import cast

import httpx

from app.config import settings


def _base_url(profile: str) -> str:
    urls = {
        "foot": settings.osrm_foot_url,
        "car": settings.osrm_car_url,
        "bicycle": settings.osrm_bicycle_url,
    }
    if profile not in urls:
        raise ValueError(
            f"Unknown OSRM profile: {profile!r}. Must be foot, car, or bicycle."
        )
    return urls[profile]


async def get_distance_matrix(
    coordinates: list[list[float]],
    profile: str = "foot",
) -> list[list[float]]:
    """
    Fetch a travel time matrix from OSRM for the given coordinates.

    Args:
        coordinates: Sequence of (longitude, latitude) pairs. OSRM uses lon,lat order.
        profile: Transport mode — "foot", "car", or "bicycle".

    Returns:
        2D list where result[i][j] is travel time in seconds from coordinates[i] to coordinates[j].
        Unreachable pairs are replaced with a large penalty value.

    Raises:
        httpx.HTTPStatusError: On HTTP errors (e.g. 429 rate limit).
        ValueError: On OSRM error responses.
    """
    if not coordinates:
        return []

    if len(coordinates) == 1:
        return [[0]]

    coord_str = ";".join(f"{lon},{lat}" for lon, lat in coordinates)
    url = f"{_base_url(profile)}/table/v1/{profile}/{coord_str}?annotations=duration"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

    if data.get("code") != "Ok":
        msg = data.get("message", "Unknown OSRM error")
        raise ValueError(f"OSRM error: {msg}")

    raw_durations = data.get("durations")
    if raw_durations is None:
        raise ValueError("OSRM response missing 'durations' field")
    durations = cast(list[list[float | None]], raw_durations)

    max_duration = 0.0
    for row in durations:
        for val in row:
            if val is not None:
                max_duration = max(max_duration, val)

    # Unreachable pairs get a penalty large enough to make any route through them
    # cost-prohibitive. We use 2× the largest real duration as a dynamic floor,
    # with a hard minimum of 999 999 s (~11.5 days) for sparse matrices where
    # all real durations might be short.
    penalty = max(max_duration * 2, 999_999)

    result: list[list[float]] = []
    for row in durations:
        result.append([(val if val is not None else penalty) for val in row])

    return result
