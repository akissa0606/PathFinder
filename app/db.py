"""SQLite schema, connection helper, and initialization."""

import os
from collections.abc import AsyncGenerator

import aiosqlite

from app.config import settings

CREATE_TRIPS = """
CREATE TABLE IF NOT EXISTS trips (
    id TEXT PRIMARY KEY,
    city TEXT NOT NULL,
    start_lat REAL NOT NULL,
    start_lon REAL NOT NULL,
    end_lat REAL NOT NULL,
    end_lon REAL NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    date TEXT NOT NULL,
    transport_mode TEXT NOT NULL DEFAULT 'foot',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

CREATE_PLACES = """
CREATE TABLE IF NOT EXISTS places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id TEXT NOT NULL REFERENCES trips(id),
    name TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    category TEXT,
    priority TEXT NOT NULL DEFAULT 'want',
    estimated_duration_min INTEGER,
    opening_hours TEXT,
    opening_hours_source TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    arrived_at TEXT,
    departed_at TEXT,
    created_at TEXT NOT NULL
);
"""

CREATE_DISTANCE_CACHE = """
CREATE TABLE IF NOT EXISTS distance_cache (
    trip_id TEXT NOT NULL REFERENCES trips(id),
    from_place_id INTEGER NOT NULL,
    to_place_id INTEGER NOT NULL,
    duration_seconds REAL NOT NULL,
    PRIMARY KEY (trip_id, from_place_id, to_place_id)
);
"""


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """FastAPI dependency that yields a DB connection and closes it on exit."""
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    os.makedirs(os.path.dirname(os.path.abspath(settings.database_path)), exist_ok=True)
    async with aiosqlite.connect(settings.database_path) as db:
        _ = await db.execute(CREATE_TRIPS)
        _ = await db.execute(CREATE_PLACES)
        _ = await db.execute(CREATE_DISTANCE_CACHE)
        _ = await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_places_trip_id ON places(trip_id)"
        )
        _ = await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_distance_cache_trip_id ON distance_cache(trip_id)"
        )
        await db.commit()
