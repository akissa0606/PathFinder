# PathFinder — Complete API Specification

All endpoints are prefixed with `/api`. The backend runs on port 8000 during development.

---

## Trip Management

### POST /api/trips
Create a new trip.

**Request body:**
```json
{
  "city": "Pecs",
  "start_lat": 46.0727,
  "start_lon": 18.2088,
  "end_lat": 46.0727,
  "end_lon": 18.2088,
  "start_time": "10:00",
  "end_time": "18:00",
  "date": "2026-04-20",
  "transport_mode": "foot",
  "timezone": "Europe/Budapest"
}
```

- `end_lat/end_lon` equal to `start_lat/start_lon` = closed trip (circular route)
- `transport_mode`: `"foot"` | `"car"` | `"bicycle"`
- `timezone`: IANA timezone string, auto-detected by browser via `Intl.DateTimeFormat().resolvedOptions().timeZone`
- `start_time` and `date` default to current time/date if omitted
- Validation: end_time must be after start_time (same day assumed)

**Response 201:**
```json
{
  "id": "a1b2c3d4-...",
  "url": "/trip/a1b2c3d4-..."
}
```

---

### GET /api/trips/{trip_id}
Get trip with all places.

**Response 200:**
```json
{
  "id": "a1b2c3d4-...",
  "city": "Pecs",
  "start_lat": 46.0727,
  "start_lon": 18.2088,
  "end_lat": 46.0727,
  "end_lon": 18.2088,
  "start_time": "10:00",
  "end_time": "18:00",
  "date": "2026-04-20",
  "transport_mode": "foot",
  "timezone": "Europe/Budapest",
  "status": "active",
  "completed_at": null,
  "created_at": "2026-04-20T08:00:00+00:00",
  "updated_at": "2026-04-20T08:00:00+00:00",
  "places": [
    {
      "id": 1,
      "trip_id": "a1b2c3d4-...",
      "name": "Pécs Cathedral",
      "lat": 46.0762,
      "lon": 18.2281,
      "category": "tourism:cathedral",
      "priority": "must",
      "estimated_duration_min": 45,
      "opening_hours": "Mo-Sa 09:00-17:00",
      "opening_hours_source": "osm",
      "status": "pending",
      "arrived_at": null,
      "departed_at": null,
      "created_at": "2026-04-20T08:05:00+00:00"
    }
  ]
}
```

---

### PATCH /api/trips/{trip_id}
Update trip settings.

**Request body (all fields optional):**
```json
{
  "start_time": "09:00",
  "end_time": "19:00",
  "transport_mode": "bicycle",
  "timezone": "Europe/Budapest"
}
```

On `transport_mode` change: distance cache is cleared and recomputed in the background via OSRM.

**Response 200:** Full trip object (same shape as GET).

---

### DELETE /api/trips/{trip_id}
Delete trip and all associated data.

Cascade order: `trajectory_segments` → `distance_cache` → `places` → `trips`

**Response 204:** No body.

---

### POST /api/trips/{trip_id}/archive
Mark trip as completed. Also records the final trajectory segment from the last visited place to the trip's end point via OSRM.

**Response 200:** Full trip object with `status: "archived"` and `completed_at` set.

---

## Place Management

### POST /api/trips/{trip_id}/places
Add a place to the trip.

**Request body:**
```json
{
  "name": "Pécs Cathedral",
  "lat": 46.0762,
  "lon": 18.2281,
  "category": "tourism:cathedral",
  "priority": "must",
  "estimated_duration_min": 45,
  "opening_hours": null,
  "opening_hours_source": null
}
```

- `priority`: `"must"` | `"want"` | `"if_time"` (default: `"want"`)
- `category`: OSM-style `"type:value"` string (e.g. `"amenity:cafe"`, `"tourism:museum"`)
- After insertion, two background tasks run: hours resolution (Overpass → Google) and distance caching (OSRM)

**Response 201:** Full place object.

---

### PATCH /api/trips/{trip_id}/places/{place_id}
Update a place.

**Request body (all fields optional):**
```json
{
  "priority": "must",
  "estimated_duration_min": 60,
  "opening_hours": "Mo-Fr 09:00-18:00",
  "opening_hours_source": "manual"
}
```

**Response 200:** Updated place object.

---

### DELETE /api/trips/{trip_id}/places/{place_id}
Remove a place. Also cleans up `distance_cache` entries involving this place.

**Response 204:** No body.

---

## Search & Geocoding

### GET /api/search
Search for POIs near a location.

**Query params:** `q` (required), `lat` (required), `lon` (required), `radius` (optional, default 2000 meters)

**Strategy:**
1. Query Overpass API for named nodes/ways within radius matching `q` (case-insensitive regex)
2. If all Overpass endpoints fail (timeout 4s each), fall back to Nominatim viewbox search

**Response 200:**
```json
[
  {
    "name": "Pécs Cathedral",
    "lat": 46.0762,
    "lon": 18.2281,
    "category": "tourism:cathedral",
    "opening_hours": "Mo-Sa 09:00-17:00"
  }
]
```

Returns empty array `[]` if nothing found.

---

### GET /api/geocode
Forward geocode an address.

**Query params:** `q` (required)

**Response 200:**
```json
[
  {
    "name": "Pécs, Baranya County, Hungary",
    "lat": 46.0727,
    "lon": 18.2088,
    "category": "city",
    "opening_hours": null
  }
]
```

Up to 5 results, ordered by Nominatim relevance.

---

## Feasibility

### GET /api/trips/{trip_id}/feasibility
Get feasibility assessment for all pending places.

**Query params:** `lat` (required), `lon` (required), `time` (optional, ISO datetime)

**Response 200:**
```json
{
  "places": [
    {
      "place_id": 1,
      "place_name": "Pécs Cathedral",
      "color": "green",
      "travel_minutes": 12.5,
      "slack_minutes": 45.0,
      "closing_time": "17:00",
      "urgency": false,
      "reason": "Comfortable — 45 min to spare"
    }
  ],
  "computed_at": "2026-04-20T10:30:00+00:00"
}
```

Colors: `"green"` | `"yellow"` | `"red"` | `"gray"` | `"unknown"`

---

## What Next?

### GET /api/trips/{trip_id}/next
Get top 3 "What Next?" recommendations.

**Query params:** `lat` (required), `lon` (required), `time` (optional)

**Response 200 (with recommendations):**
```json
{
  "recommendations": [
    {
      "place_id": 1,
      "place_name": "Pécs Cathedral",
      "score": 0.82,
      "opportunity_cost": 2,
      "travel_minutes": 8.3,
      "reason": "Visit now — skipping would make 2 other places unreachable"
    }
  ],
  "message": null
}
```

**Response 200 (no viable options):**
```json
{
  "recommendations": [],
  "message": "All pending places are currently unreachable"
}
```

Possible messages: `"No pending places"`, `"All pending places are currently unreachable"`.

---

## Check-In

### POST /api/trips/{trip_id}/checkin
Check in at a place.

**Request body:**
```json
{
  "place_id": 1,
  "action": "arrived"
}
```

- `action`: `"arrived"` | `"done"` | `"skipped"`
- State machine: `pending → arrived(visiting)`, `visiting → done`, `pending/visiting → skipped`
- Invalid transitions return 400

**Response 200:**
```json
{
  "place_id": 1,
  "status": "visiting",
  "arrived_at": "2026-04-20T10:45:00+00:00",
  "departed_at": null,
  "message": "Arrived at Pécs Cathedral",
  "trajectory_segment": {
    "id": 5,
    "from_lat": 46.0727,
    "from_lon": 18.2088,
    "to_lat": 46.0762,
    "to_lon": 18.2281,
    "place_id": 1,
    "geometry": "iefxGipcnB...",
    "distance_meters": 437.2,
    "duration_seconds": 312.0,
    "created_at": "2026-04-20T10:45:00+00:00"
  }
}
```

`trajectory_segment` is `null` if OSRM is unavailable (segment not recorded, no straight-line fallback).

---

## Trajectory

### GET /api/trips/{trip_id}/trajectory
Get all recorded journey segments.

**Response 200:**
```json
{
  "segments": [
    {
      "id": 5,
      "from_lat": 46.0727,
      "from_lon": 18.2088,
      "to_lat": 46.0762,
      "to_lon": 18.2281,
      "place_id": 1,
      "geometry": "iefxGipcnB...",
      "distance_meters": 437.2,
      "duration_seconds": 312.0,
      "created_at": "2026-04-20T10:45:00+00:00"
    }
  ]
}
```

`geometry` is Google encoded polyline format. `place_id` is `null` for the closing segment (archive leg to end point).

---

## SSE Stream

### GET /api/trips/{trip_id}/stream
Server-Sent Events stream for real-time updates.

**Query params:** `lat` (required), `lon` (required)

**Event: `feasibility_update`** (every 60 seconds)

Data payload: same shape as `GET /feasibility` response.

**Event: `urgency_alert`**

Emitted when a place's feasibility color degrades or a must-visit place is closing soon.

```json
{
  "place_id": 1,
  "place_name": "Pécs Cathedral",
  "message": "Closing in 25 minutes!",
  "severity": "critical"
}
```

`severity`: `"warning"` (yellow transition, closing < 60 min) | `"critical"` (red/gray transition, closing < 30 min)

---

## System

### GET /health

**Response 200:**
```json
{"status": "ok"}
```

---

## Common Error Responses

All endpoints return standard error JSON on failure:

```json
{"detail": "Trip not found"}
```

| Status | Meaning |
|--------|---------|
| 400 | Bad request (invalid check-in transition, validation failed) |
| 404 | Resource not found (trip or place doesn't exist) |
| 422 | Pydantic validation error (missing required field, wrong type) |
| 500 | Server error (rare — DB failure, uncaught exception) |

---

## Pydantic Models Reference

All request/response bodies are validated by Pydantic v2 models in `app/models.py`.

### TripCreate (POST /trips body)
| Field | Type | Default | Notes |
|-------|------|---------|-------|
| city | str | required | Free text |
| start_lat / start_lon | float | required | Validated: lat ±90, lon ±180 |
| end_lat / end_lon | float | required | Same as start = closed trip |
| start_time | str | current HH:MM | Format: `^\d{2}:\d{2}$`, 00:00–23:59 |
| end_time | str | required | Must be after start_time |
| date | str | today | YYYY-MM-DD |
| transport_mode | str | "foot" | "foot" \| "car" \| "bicycle" |
| timezone | str | "UTC" | IANA timezone, e.g. "Europe/Budapest" |

### PlaceAdd (POST /places body)
| Field | Type | Default | Notes |
|-------|------|---------|-------|
| name | str | required | |
| lat / lon | float | required | |
| category | str | null | OSM-style "type:value" |
| priority | str | "want" | "must" \| "want" \| "if_time" |
| estimated_duration_min | int | null | Minutes; falls back to category default |
| opening_hours | str | null | OSM format or null |
| opening_hours_source | str | null | "osm" \| "google" \| "manual" \| null |

### FeasibilityResponse (GET /feasibility response)
```json
{
  "current_time": "2026-04-20T10:30:00+00:00",
  "remaining_minutes": 450.0,
  "places": [...]
}
```

### FeasibilityResult (per place in FeasibilityResponse)
| Field | Type | Notes |
|-------|------|-------|
| place_id | int | |
| place_name | str | |
| color | str | "green"\|"yellow"\|"red"\|"gray"\|"unknown" |
| travel_minutes | float | OSRM or Haversine estimate |
| slack_minutes | float | How much time buffer remains |
| closing_time | str \| null | "HH:MM" in local time, or null |
| urgency | bool | True if closing soon or slack < 10% |
| reason | str | Human-readable explanation |

---

## Architecture Notes for Rebuilding

### Background Tasks
When adding a place (`POST /places`), two background tasks are queued (FastAPI `BackgroundTasks`):
1. `_resolve_hours_background` — queries Overpass then Google Places, updates the place record
2. `_cache_distances_background` — computes OSRM distance matrix for new place ↔ all existing places

Background tasks open their own `aiosqlite.connect(db_path)` because they run outside the FastAPI request lifecycle and cannot use dependency injection.

### Distance Cache
`distance_cache` table stores OSRM travel times between place pairs. Used by the feasibility engine to avoid calling OSRM on every request. Only the user's current position (which changes constantly) is computed fresh each time; place-to-place and place-to-endpoint times come from cache.

### FeasibilityContext
`compute_feasibility()` in `routers/feasibility.py` returns both a `FeasibilityResponse` (for the HTTP response) and a `FeasibilityContext` (internal dataclass). The context holds the pre-fetched places list, distance matrix, parsed times, and trip timezone. This is passed to `score_next_actions()` so `/next` doesn't re-fetch the DB or re-query OSRM.
