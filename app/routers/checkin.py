"""Check-in endpoint: arrived / done / skipped."""

import logging
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.models import CheckinRequest, CheckinResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Valid state transitions: current_status -> allowed actions
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"arrived", "skipped"},
    "visiting": {"done", "skipped"},
}


@router.post("/trips/{trip_id}/checkin", response_model=CheckinResponse)
async def checkin(
    trip_id: str,
    body: CheckinRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> CheckinResponse:
    """
    Check in at a place.

    Actions:
        arrived: Mark place as currently visiting (sets arrived_at).
        done: Mark place as done (sets departed_at). Must be visiting first.
        skipped: Mark place as skipped. Can be pending or visiting.
    """
    # Verify trip exists
    cursor = await db.execute("SELECT id FROM trips WHERE id = ?", (trip_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Trip not found")

    # Get place
    cursor = await db.execute(
        "SELECT * FROM places WHERE id = ? AND trip_id = ?",
        (body.place_id, trip_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Place not found")

    place = dict(row)
    current_status = place["status"]
    action = body.action

    # Validate transition
    allowed = VALID_TRANSITIONS.get(current_status, set())
    if action not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot '{action}' a place that is '{current_status}'",
        )

    now = datetime.now(timezone.utc).isoformat()

    if action == "arrived":
        _ = await db.execute(
            "UPDATE places SET status = 'visiting', arrived_at = ? WHERE id = ?",
            (now, body.place_id),
        )
        message = f"Arrived at {place['name']}"

    elif action == "done":
        _ = await db.execute(
            "UPDATE places SET status = 'done', departed_at = ? WHERE id = ?",
            (now, body.place_id),
        )
        message = f"Finished visiting {place['name']}"

    elif action == "skipped":
        _ = await db.execute(
            "UPDATE places SET status = 'skipped' WHERE id = ?",
            (body.place_id,),
        )
        message = f"Skipped {place['name']}"

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    await db.commit()

    # Re-read updated place
    cursor = await db.execute("SELECT * FROM places WHERE id = ?", (body.place_id,))
    updated = dict(await cursor.fetchone())  # type: ignore[arg-type]

    return CheckinResponse(
        place_id=updated["id"],
        status=updated["status"],
        arrived_at=updated["arrived_at"],
        departed_at=updated["departed_at"],
        message=message,
    )
