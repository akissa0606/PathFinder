"""Feasibility endpoint."""

import logging
from datetime import date, datetime, time, timezone

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import get_db
from app.engine.feasibility import calculate_feasibility
from app.models import FeasibilityResponse, FeasibilityResult
from app.services.osrm import get_distance_matrix

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


async def compute_feasibility(
    db: aiosqlite.Connection,
    trip_id: str,
    lat: float | None = None,
    lon: float | None = None,
    time_override: str | None = None,
) -> tuple[FeasibilityResponse, dict[int, str], dict[int, str]]:
    """Shared feasibility computation.

    Returns:
        (FeasibilityResponse, {place_id: name}, {place_id: priority})
    """
    cursor = await db.execute("SELECT * FROM trips WHERE id = ?", (trip_id,))
    trip_row = await cursor.fetchone()
    if not trip_row:
        raise HTTPException(status_code=404, detail="Trip not found")
    trip = dict(trip_row)

    cur_lat = lat if lat is not None else trip["start_lat"]
    cur_lon = lon if lon is not None else trip["start_lon"]

    trip_date = date.fromisoformat(trip["date"])
    end_h, end_m = trip["end_time"].split(":")
    trip_end_dt = datetime.combine(trip_date, time(int(end_h), int(end_m)))

    if time_override:
        t_h, t_m = time_override.split(":")
        current_time = datetime.combine(trip_date, time(int(t_h), int(t_m)))
    else:
        current_time = datetime.now(timezone.utc).replace(tzinfo=None)

    remaining_minutes = max(0, (trip_end_dt - current_time).total_seconds() / 60)

    cursor = await db.execute(
        "SELECT * FROM places WHERE trip_id = ? AND status = 'pending' ORDER BY id",
        (trip_id,),
    )
    places = [dict(r) for r in await cursor.fetchall()]

    place_names: dict[int, str] = {p["id"]: p["name"] for p in places}
    place_priorities: dict[int, str] = {p["id"]: p.get("priority", "want") for p in places}

    if not places:
        return (
            FeasibilityResponse(
                current_time=current_time.isoformat(),
                remaining_minutes=round(remaining_minutes, 1),
                places=[],
            ),
            place_names,
            place_priorities,
        )

    coords = [[cur_lon, cur_lat]]
    for p in places:
        coords.append([p["lon"], p["lat"]])
    coords.append([trip["end_lon"], trip["end_lat"]])

    matrix = await get_distance_matrix(coords, trip["transport_mode"])

    endpoint_idx = len(places) + 1

    results: list[FeasibilityResult] = []
    for i, place in enumerate(places):
        place_idx = i + 1
        travel_to_place = matrix[0][place_idx]
        travel_to_endpoint = matrix[place_idx][endpoint_idx]

        result = calculate_feasibility(
            place=place,
            travel_to_place_seconds=travel_to_place,
            travel_to_endpoint_seconds=travel_to_endpoint,
            current_time=current_time,
            trip_end_time=trip_end_dt,
            trip_date=trip_date,
        )
        results.append(FeasibilityResult(**result))

    return (
        FeasibilityResponse(
            current_time=current_time.isoformat(),
            remaining_minutes=round(remaining_minutes, 1),
            places=results,
        ),
        place_names,
        place_priorities,
    )


@router.get("/trips/{trip_id}/feasibility", response_model=FeasibilityResponse)
async def get_feasibility(
    trip_id: str,
    lat: float | None = Query(None),
    lon: float | None = Query(None),
    time_override: str | None = Query(None, alias="time"),
    db: aiosqlite.Connection = Depends(get_db),
) -> FeasibilityResponse:
    """
    Compute feasibility for all pending places in a trip.

    Query params:
        lat, lon: Current position. If not provided, uses trip start location.
        time: Optional ISO time override for testing (e.g. "14:30").
    """
    response, _, _ = await compute_feasibility(db, trip_id, lat, lon, time_override)
    return response
