"""'What Next?' recommendation endpoint."""

import logging
from datetime import date, datetime, time, timezone

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import get_db
from app.engine.scoring import score_next_actions
from app.models import NextRecommendation, NextResponse
from app.services.osrm import get_distance_matrix

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.get("/trips/{trip_id}/next", response_model=NextResponse)
async def get_next_recommendation(
    trip_id: str,
    lat: float | None = Query(None),
    lon: float | None = Query(None),
    time_override: str | None = Query(None, alias="time"),
    db: aiosqlite.Connection = Depends(get_db),
) -> NextResponse:
    """
    Get top 3 recommended next places to visit.

    Query params:
        lat, lon: Current position. Falls back to trip start.
        time: Optional ISO time override for testing (e.g. "14:30").
    """
    # Get trip
    cursor = await db.execute("SELECT * FROM trips WHERE id = ?", (trip_id,))
    trip_row = await cursor.fetchone()
    if not trip_row:
        raise HTTPException(status_code=404, detail="Trip not found")
    trip = dict(trip_row)

    # Current position
    cur_lat = lat if lat is not None else trip["start_lat"]
    cur_lon = lon if lon is not None else trip["start_lon"]

    # Parse trip date and times
    trip_date = date.fromisoformat(trip["date"])
    end_h, end_m = trip["end_time"].split(":")
    trip_end_dt = datetime.combine(trip_date, time(int(end_h), int(end_m)))

    # Current time
    if time_override:
        t_h, t_m = time_override.split(":")
        current_time = datetime.combine(trip_date, time(int(t_h), int(t_m)))
    else:
        current_time = datetime.now(timezone.utc).replace(tzinfo=None)

    # Get pending places
    cursor = await db.execute(
        "SELECT * FROM places WHERE trip_id = ? AND status = 'pending' ORDER BY id",
        (trip_id,),
    )
    places = [dict(r) for r in await cursor.fetchall()]

    if not places:
        return NextResponse(
            recommendations=[],
            message="No pending places. Add some places or head to your endpoint.",
        )

    # Build coordinate list: [current_position] + [all places] + [endpoint]
    coords = [[cur_lon, cur_lat]]
    for p in places:
        coords.append([p["lon"], p["lat"]])
    coords.append([trip["end_lon"], trip["end_lat"]])

    # Get distance matrix from OSRM
    matrix = await get_distance_matrix(coords, trip["transport_mode"])

    endpoint_idx = len(places) + 1

    # Precompute feasibility for all pending places so we can:
    # 1) Avoid duplicate feasibility work in the scorer
    # 2) Detect the special case where every place is infeasible (color == 'gray')
    from app.engine.feasibility import calculate_feasibility

    precomputed_feasibility: dict[int, dict] = {}
    for i, place in enumerate(places):
        place_idx = i + 1
        travel_to_place = matrix[0][place_idx]
        travel_to_endpoint = matrix[place_idx][endpoint_idx]

        feas = calculate_feasibility(
            place=place,
            travel_to_place_seconds=travel_to_place,
            travel_to_endpoint_seconds=travel_to_endpoint,
            current_time=current_time,
            trip_end_time=trip_end_dt,
            trip_date=trip_date,
        )
        precomputed_feasibility[place["id"]] = feas

    # If every pending place is infeasible right now, return a helpful message
    all_infeasible = all(
        (precomputed_feasibility.get(p["id"], {}).get("color") == "gray")
        for p in places
    )
    if all_infeasible:
        must_pending = [p for p in places if p.get("priority") == "must"]
        if must_pending:
            msg = (
                "No reachable places right now. Some 'must' places remain but are currently unreachable "
                "(closed or too far). Consider adjusting your schedule or transport mode."
            )
        else:
            msg = (
                "No reachable places right now — all pending places are currently infeasible "
                "(closed or too far). Consider adjusting your schedule or transport mode."
            )
        return NextResponse(recommendations=[], message=msg)

    # Compute recommendations, passing the precomputed feasibility map to avoid recomputation
    recommendations = score_next_actions(
        places=places,
        matrix=matrix,
        current_time=current_time,
        trip_end_time=trip_end_dt,
        trip_date=trip_date,
        endpoint_idx=endpoint_idx,
        precomputed_feasibility=precomputed_feasibility,
    )

    return NextResponse(
        recommendations=[NextRecommendation(**r) for r in recommendations],
        message=None,
    )
