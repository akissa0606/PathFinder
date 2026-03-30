"""Place CRUD endpoints for a trip."""

import logging
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.config import settings
from app.db import get_db
from app.models import PlaceAdd, PlaceResponse, PlaceUpdate
from app.services.hours import resolve_opening_hours
from app.services.osrm import get_distance_matrix

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


async def _resolve_hours_background(
    place_id: int, lat: float, lon: float, name: str, db_path: str
) -> None:
    """Background task to resolve opening hours and update the place."""
    import aiosqlite as _aiosqlite

    try:
        hours, source = await resolve_opening_hours(lat, lon, name)
        if hours:
            async with _aiosqlite.connect(db_path) as db:
                await db.execute(
                    "UPDATE places SET opening_hours = ?, opening_hours_source = ? WHERE id = ?",
                    (hours, source, place_id),
                )
                await db.commit()
            logger.info("Resolved hours for place %d: %s (%s)", place_id, hours, source)
    except Exception:
        logger.exception("Failed to resolve hours for place %d", place_id)


async def _cache_distances_background(
    trip_id: str, place_id: int, lat: float, lon: float, db_path: str
) -> None:
    """Background task to compute OSRM distances between new place and existing places/trip endpoints."""
    import aiosqlite as _aiosqlite

    try:
        async with _aiosqlite.connect(db_path) as db:
            db.row_factory = _aiosqlite.Row
            # Get trip for start/end coords and transport mode
            cursor = await db.execute("SELECT * FROM trips WHERE id = ?", (trip_id,))
            trip = await cursor.fetchone()
            if not trip:
                return
            trip = dict(trip)

            # Get all places for this trip
            cursor = await db.execute(
                "SELECT id, lat, lon FROM places WHERE trip_id = ?", (trip_id,)
            )
            all_places = [dict(r) for r in await cursor.fetchall()]

            if len(all_places) < 2:
                # Only the new place exists, nothing to compute distances to
                return

            # Build coordinate list: all places
            coords = [[p["lon"], p["lat"]] for p in all_places]
            profile = trip["transport_mode"]

            matrix = await get_distance_matrix(coords, profile)

            # Cache all pairs involving the new place
            new_idx = next(
                i for i, p in enumerate(all_places) if p["id"] == place_id
            )

            for i, p in enumerate(all_places):
                if i == new_idx:
                    continue
                # new -> other
                await db.execute(
                    """INSERT OR REPLACE INTO distance_cache
                       (trip_id, from_place_id, to_place_id, duration_seconds)
                       VALUES (?, ?, ?, ?)""",
                    (trip_id, place_id, p["id"], matrix[new_idx][i]),
                )
                # other -> new
                await db.execute(
                    """INSERT OR REPLACE INTO distance_cache
                       (trip_id, from_place_id, to_place_id, duration_seconds)
                       VALUES (?, ?, ?, ?)""",
                    (trip_id, p["id"], place_id, matrix[i][new_idx]),
                )
            await db.commit()
            logger.info("Cached distances for place %d in trip %s", place_id, trip_id)
    except Exception:
        logger.exception("Failed to cache distances for place %d", place_id)


@router.post(
    "/trips/{trip_id}/places", response_model=PlaceResponse, status_code=201
)
async def add_place(
    trip_id: str,
    body: PlaceAdd,
    background_tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
) -> PlaceResponse:
    # Verify trip exists
    cursor = await db.execute("SELECT id FROM trips WHERE id = ?", (trip_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Trip not found")

    now = datetime.now(timezone.utc).isoformat()
    cursor = await db.execute(
        """INSERT INTO places
           (trip_id, name, lat, lon, category, priority,
            estimated_duration_min, opening_hours, opening_hours_source,
            status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (
            trip_id,
            body.name,
            body.lat,
            body.lon,
            body.category,
            body.priority,
            body.estimated_duration_min,
            body.opening_hours,
            body.opening_hours_source,
            now,
        ),
    )
    await db.commit()
    pid = cursor.lastrowid
    if pid is None:
        raise HTTPException(status_code=500, detail="Failed to insert place")

    cursor = await db.execute("SELECT * FROM places WHERE id = ?", (pid,))
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to read inserted place")

    # Background: resolve hours if not user-supplied
    if not body.opening_hours:
        background_tasks.add_task(
            _resolve_hours_background,
            pid,
            body.lat,
            body.lon,
            body.name,
            settings.database_path,
        )

    # Background: cache OSRM distances
    background_tasks.add_task(
        _cache_distances_background,
        trip_id,
        pid,
        body.lat,
        body.lon,
        settings.database_path,
    )

    return PlaceResponse(**dict(row))


@router.delete("/trips/{trip_id}/places/{place_id}", status_code=204)
async def delete_place(
    trip_id: str,
    place_id: int,
    db: aiosqlite.Connection = Depends(get_db),
) -> None:
    cursor = await db.execute(
        "SELECT id FROM places WHERE id = ? AND trip_id = ?", (place_id, trip_id)
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Place not found")

    await db.execute(
        "DELETE FROM distance_cache WHERE trip_id = ? AND (from_place_id = ? OR to_place_id = ?)",
        (trip_id, place_id, place_id),
    )
    await db.execute("DELETE FROM places WHERE id = ?", (place_id,))
    await db.commit()


@router.patch(
    "/trips/{trip_id}/places/{place_id}", response_model=PlaceResponse
)
async def update_place(
    trip_id: str,
    place_id: int,
    body: PlaceUpdate,
    db: aiosqlite.Connection = Depends(get_db),
) -> PlaceResponse:
    cursor = await db.execute(
        "SELECT * FROM places WHERE id = ? AND trip_id = ?", (place_id, trip_id)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Place not found")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        return PlaceResponse(**dict(row))

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [place_id]
    await db.execute(f"UPDATE places SET {set_clause} WHERE id = ?", values)
    await db.commit()

    cursor = await db.execute("SELECT * FROM places WHERE id = ?", (place_id,))
    updated = await cursor.fetchone()
    if updated is None:
        raise HTTPException(status_code=404, detail="Place not found")
    return PlaceResponse(**dict(updated))
