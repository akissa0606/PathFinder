"""Trip CRUD endpoints."""

import logging
import uuid
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.models import PlaceResponse, TripCreate, TripDetailResponse, TripResponse, TripUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.post("/trips", response_model=dict, status_code=201)
async def create_trip(
    body: TripCreate, db: aiosqlite.Connection = Depends(get_db)
) -> dict:
    trip_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """INSERT INTO trips
           (id, city, start_lat, start_lon, end_lat, end_lon,
            start_time, end_time, date, transport_mode, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trip_id,
            body.city,
            body.start_lat,
            body.start_lon,
            body.end_lat,
            body.end_lon,
            body.start_time,
            body.end_time,
            body.date,
            body.transport_mode,
            now,
            now,
        ),
    )
    await db.commit()
    return {"id": trip_id, "url": f"/api/trips/{trip_id}"}


@router.get("/trips/{trip_id}", response_model=TripDetailResponse)
async def get_trip(
    trip_id: str, db: aiosqlite.Connection = Depends(get_db)
) -> TripDetailResponse:
    cursor = await db.execute("SELECT * FROM trips WHERE id = ?", (trip_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Trip not found")

    trip = TripResponse(**dict(row))

    cursor = await db.execute(
        "SELECT * FROM places WHERE trip_id = ? ORDER BY id", (trip_id,)
    )
    place_rows = await cursor.fetchall()
    places = [PlaceResponse(**dict(r)) for r in place_rows]

    return TripDetailResponse(**trip.model_dump(), places=places)


@router.patch("/trips/{trip_id}", response_model=TripResponse)
async def update_trip(
    trip_id: str,
    body: TripUpdate,
    db: aiosqlite.Connection = Depends(get_db),
) -> TripResponse:
    cursor = await db.execute("SELECT * FROM trips WHERE id = ?", (trip_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Trip not found")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        return TripResponse(**dict(row))

    now = datetime.now(timezone.utc).isoformat()
    updates["updated_at"] = now
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [trip_id]
    await db.execute(f"UPDATE trips SET {set_clause} WHERE id = ?", values)
    await db.commit()

    cursor = await db.execute("SELECT * FROM trips WHERE id = ?", (trip_id,))
    updated = await cursor.fetchone()
    if updated is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    return TripResponse(**dict(updated))


@router.delete("/trips/{trip_id}", status_code=204)
async def delete_trip(
    trip_id: str, db: aiosqlite.Connection = Depends(get_db)
) -> None:
    cursor = await db.execute("SELECT id FROM trips WHERE id = ?", (trip_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Trip not found")

    await db.execute("DELETE FROM distance_cache WHERE trip_id = ?", (trip_id,))
    await db.execute("DELETE FROM places WHERE trip_id = ?", (trip_id,))
    await db.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
    await db.commit()
