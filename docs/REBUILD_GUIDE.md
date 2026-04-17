# PathFinder — Slice-by-Slice Rebuild Guide

This guide walks you through rebuilding PathFinder from scratch. Each slice is a self-contained milestone that you can commit, test, and demo independently. The slices are ordered by dependency — each one builds on the previous.

**Total codebase**: ~7,000 lines (3,100 backend Python + 3,900 frontend Vue/JS/CSS)
**Test suite**: 72 tests across 10 files

---

## Pre-Requisites

Before you start coding, set up the project skeleton and infrastructure.

### 1. Project Structure

```
pathfinder/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── db.py
│   ├── http_client.py
│   ├── main.py
│   ├── models.py
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── category_defaults.py
│   │   ├── feasibility.py
│   │   └── scoring.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── trips.py
│   │   ├── places.py
│   │   ├── search.py
│   │   ├── feasibility.py
│   │   ├── next_action.py
│   │   ├── checkin.py
│   │   ├── trajectory.py
│   │   └── stream.py
│   └── services/
│       ├── __init__.py
│       ├── osrm.py
│       ├── overpass.py
│       ├── hours.py
│       └── google_places.py
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.js
│       ├── App.vue
│       ├── router.js
│       ├── api.js
│       ├── map-utils.js
│       ├── style.css
│       └── views/
│           ├── Home.vue
│           ├── Dashboard.vue
│           └── Summary.vue
├── tests/
├── data/              (gitignored — SQLite db lives here)
├── osrm-data/         (gitignored — 3GB OSRM files)
├── docker-compose.yml
├── migrate.py
├── requirements.txt
├── .env.example
├── .gitignore
└── CLAUDE.md
```

### 2. Python Dependencies (`requirements.txt`)

```
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
httpx>=0.26.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
sse-starlette>=1.6.0
aiosqlite>=0.19.0
pytest>=7.0.0
pytest-asyncio>=0.23.0
ruff>=0.4.0
```

### 3. Frontend Dependencies (`package.json`)

```json
{
  "dependencies": {
    "animejs": "^4.3.6",
    "leaflet": "^1.9.4",
    "vue": "^3.5.30",
    "vue-router": "^4.6.4"
  },
  "devDependencies": {
    "@types/leaflet": "^1.9.x",
    "@vitejs/plugin-vue": "^6.0.5",
    "eslint": "^9.x",
    "eslint-config-prettier": "^9.x",
    "eslint-plugin-vue": "^9.x",
    "prettier": "^3.x",
    "vite": "^8.0.1",
    "vue-eslint-parser": "^9.x"
  }
}
```

### 4. Docker Compose (`docker-compose.yml`)

Three OSRM containers (foot/car/bicycle) on ports 5000/5001/5002, each using `osrm/osrm-backend:v5.25.0` with MLD algorithm and Hungary OSM data.

### 5. Environment (`.env.example`)

```bash
OSRM_FOOT_URL=http://localhost:5000
OSRM_CAR_URL=http://localhost:5001
OSRM_BICYCLE_URL=http://localhost:5002
GOOGLE_PLACES_API_KEY=
DATABASE_PATH=./data/pathfinder.db
```

---

## Slice 0 — Database, Config, Health Check

**Goal**: FastAPI app boots, connects to SQLite, `/health` responds.
**Files to create**: `app/config.py`, `app/db.py`, `app/http_client.py`, `app/main.py`, `migrate.py`
**Lines**: ~380
**Tests**: `test_infrastructure.py` — DB connection, table creation, schema validation

### What to build

**`app/config.py`** (~22 lines)
- Pydantic `BaseSettings` class loading from `.env`
- Fields: `osrm_foot_url`, `osrm_car_url`, `osrm_bicycle_url`, `google_places_api_key`, `database_path`
- Export a singleton `settings = Settings()`

**`app/db.py`** (~167 lines)
- 4 CREATE TABLE statements:

```sql
-- trips: core trip record
CREATE TABLE IF NOT EXISTS trips (
    id TEXT PRIMARY KEY,
    city TEXT NOT NULL,
    start_lat REAL NOT NULL, start_lon REAL NOT NULL,
    end_lat REAL NOT NULL, end_lon REAL NOT NULL,
    start_time TEXT NOT NULL, end_time TEXT NOT NULL,
    date TEXT NOT NULL,
    transport_mode TEXT NOT NULL DEFAULT 'foot',
    timezone TEXT NOT NULL DEFAULT 'UTC',
    status TEXT NOT NULL DEFAULT 'active',
    completed_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

-- places: destinations within a trip
CREATE TABLE IF NOT EXISTS places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id TEXT NOT NULL REFERENCES trips(id),
    name TEXT NOT NULL,
    lat REAL NOT NULL, lon REAL NOT NULL,
    category TEXT,
    priority TEXT NOT NULL DEFAULT 'want',
    estimated_duration_min INTEGER,
    opening_hours TEXT, opening_hours_source TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    arrived_at TEXT, departed_at TEXT,
    created_at TEXT NOT NULL
);

-- distance_cache: OSRM travel times between places
CREATE TABLE IF NOT EXISTS distance_cache (
    trip_id TEXT NOT NULL REFERENCES trips(id),
    from_place_id INTEGER NOT NULL,
    to_place_id INTEGER NOT NULL,
    duration_seconds REAL NOT NULL,
    PRIMARY KEY (trip_id, from_place_id, to_place_id)
);

-- trajectory_segments: journey legs drawn on the map
CREATE TABLE IF NOT EXISTS trajectory_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id TEXT NOT NULL REFERENCES trips(id),
    from_lat REAL NOT NULL, from_lon REAL NOT NULL,
    to_lat REAL NOT NULL, to_lon REAL NOT NULL,
    place_id INTEGER,
    geometry TEXT NOT NULL DEFAULT '',
    distance_meters REAL NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
```

- Indexes on: `places(trip_id)`, `distance_cache(trip_id)`, `trajectory_segments(trip_id)`
- `init_db()` — creates tables + adds backward-compat columns if missing
- `get_db()` — FastAPI dependency yielding aiosqlite connection

**`app/http_client.py`** (~128 lines)
- Module-level shared `httpx.AsyncClient` with connection pooling
- `init_http_client()`, `close_http_client()`, `get_http_client()` (FastAPI dep), `client_instance()`
- Defaults: 15s timeout, 20 max connections, 10 keepalive, custom User-Agent

**`app/main.py`** (~25 lines for now, grows later)
- FastAPI app with lifespan (init DB + HTTP client on startup, close on shutdown)
- `GET /health` → `{"status": "ok"}`
- Include routers (empty for now)

**`migrate.py`** (~25 lines)
- Standalone script that calls `init_db()` for initial setup

### Commit message idea
`feat: project skeleton — SQLite schema, config, health endpoint`

---

## Slice 1 — Trip & Place CRUD

**Goal**: Create trips, add/remove/update places. No algorithms yet.
**Files to create**: `app/models.py`, `app/routers/trips.py`, `app/routers/places.py`
**Lines**: ~645
**Tests**: `test_slice1.py` — create/get/update/delete trips + places (~180 lines, ~15 tests)

### What to build

**`app/models.py`** (~200 lines)
All Pydantic models for request/response validation:

- **TripCreate**: city, start_lat/lon, end_lat/lon (±90/±180 validated), start_time (HH:MM, defaults to now), end_time (HH:MM, required), date (YYYY-MM-DD, defaults to today), transport_mode (foot/car/bicycle), timezone (IANA, default UTC). Validator: HH:MM format regex `^\d{2}:\d{2}$` with 0-23 hours and 0-59 minutes.
- **TripUpdate**: optional start_time, end_time, transport_mode, timezone
- **TripResponse**: all fields + id, status, completed_at, created_at, updated_at
- **TripDetailResponse** (extends TripResponse): adds `places: list[PlaceResponse]`
- **PlaceAdd**: name, lat, lon, category?, priority (must/want/if_time, default want), estimated_duration_min?, opening_hours?, opening_hours_source?
- **PlaceUpdate**: optional priority, estimated_duration_min, opening_hours, opening_hours_source
- **PlaceResponse**: all fields + id, trip_id, status, arrived_at, departed_at, created_at

Other models (add now as empty stubs, fill in later slices):
- FeasibilityResult, FeasibilityResponse, NextRecommendation, NextResponse, TrajectorySegment, TrajectoryResponse

**`app/routers/trips.py`** (~216 lines)
- `POST /api/trips` → 201, generates UUID, validates end > start time, defaults date/start_time/timezone, returns `{id, url}`
- `GET /api/trips/{trip_id}` → trip with places (joined query), 404 if missing
- `PATCH /api/trips/{trip_id}` → update allowed fields. On transport_mode change: delete distance_cache, background recompute (once OSRM is wired up)
- `DELETE /api/trips/{trip_id}` → cascade delete trajectory_segments, distance_cache, places, trip (in order)
- `POST /api/trips/{trip_id}/archive` → set status=archived, completed_at=now

**`app/routers/places.py`** (~231 lines)
- `POST /api/trips/{trip_id}/places` → 201, insert with status=pending, background tasks for hours resolution + distance caching (wire up in later slices)
- `DELETE /api/trips/{trip_id}/places/{place_id}` → 204, also clean distance_cache
- `PATCH /api/trips/{trip_id}/places/{place_id}` → update allowed columns only (priority, estimated_duration_min, opening_hours, opening_hours_source)

### Key implementation detail
The trips POST endpoint generates a UUID with `uuid.uuid4().hex[:36]` (or just `str(uuid.uuid4())`). The `updated_at` field is set on every mutation.

### Commit message idea
`feat: trip + place CRUD with Pydantic validation`

---

## Slice 2 — OSRM Service + Feasibility Engine

**Goal**: Calculate whether each place is reachable given time constraints. Color-code: green/yellow/red/gray/unknown.
**Files to create**: `app/services/osrm.py`, `app/engine/category_defaults.py`, `app/engine/feasibility.py`, `app/routers/feasibility.py`
**Lines**: ~770
**Tests**: `test_slice2.py` — feasibility colors, category defaults, endpoint integration (~270 lines, ~15 tests)

### What to build

**`app/services/osrm.py`** (~192 lines)
Two functions that talk to self-hosted OSRM:

1. `get_distance_matrix(coordinates, profile="foot")` → 2D list of travel times (seconds)
   - coordinates = list of `[lon, lat]` pairs
   - Calls OSRM `/table/v1/{profile}/{coords}?annotations=duration`
   - Maps profile to URL: foot→5000, car→5001, bicycle→5002
   - Unreachable pairs get penalty: 2× max duration, minimum 999,999
   - Raises ValueError on bad input or OSRM error

2. `get_route_geometry(coordinates, profile="foot")` → list of leg dicts
   - Calls OSRM `/route/v1/{profile}/{coords}?overview=full&geometries=polyline`
   - Returns `[{geometry, distance, duration}]` per leg
   - On OSRM failure: returns legs with empty geometry (callers must check)

**`app/engine/category_defaults.py`** (~27 lines)
- Dict mapping 20 categories to default visit durations in minutes:
  museum:90, gallery:60, temple:45, church:30, castle:90, monument:15, landmark:10, park:60, garden:45, cafe:30, restaurant:75, bar:60, shop:40, market:60, theater:120, zoo:180, beach:120, viewpoint:15, other:45
- `get_duration_minutes(category, override)` — returns override if given, else category default, else 45

**`app/engine/feasibility.py`** (~310 lines)
The core algorithm. For each place:

1. Calculate travel_to_place (seconds) + visit_duration + travel_to_endpoint (return to trip end point)
2. Calculate total_needed = travel + visit + return
3. Calculate available = trip_end_time - current_time
4. slack = available - total_needed
5. If place has opening_hours, parse closing time and check if arrival < closing

Color assignment:
- **gray**: slack < 0 (mathematically impossible) or would arrive after closing
- **red**: closing in < 30 minutes, or slack_ratio < 0.10
- **yellow**: closing in < 2 hours, or slack_ratio < 0.30, or no opening hours but time-feasible
- **unknown**: no opening_hours data at all
- **green**: everything else (comfortable margin)

Key helper: `parse_closing_time(opening_hours_string, trip_date, trip_timezone)`:
- Parses OSM format like `"Mo-Fr 09:00-18:00"`, `"Mo,Tu,We 10:00-17:00"`, `"Sa 09:00-14:00"`
- Handles day ranges, comma-separated days, wrapped ranges (Fr-Mo)
- Returns UTC-aware datetime of closing time on trip_date
- Falls back to None if unparseable

**`app/routers/feasibility.py`** (~233 lines)
- `GET /api/trips/{trip_id}/feasibility?lat=&lon=&time=`
- Builds a distance matrix: user position + all pending places + trip endpoint
- Calls `calculate_feasibility()` for each pending place
- Returns `FeasibilityResponse` with per-place colors, slack, urgency, reasons

Important: includes **Haversine fallback** for when OSRM is down:
- `_haversine_distance_m(lat1, lon1, lat2, lon2)` — great-circle distance
- `_haversine_matrix(coords, profile)` — straight-line × 1.4 detour factor ÷ speed
- Profile speeds: foot=1.4 m/s (~5 km/h), bicycle=4.2 m/s (~15 km/h), car=8.3 m/s (~30 km/h)

Also exports `compute_feasibility()` shared helper used by both this endpoint and next_action/stream.

### How to wire up distance caching
In `places.py`, the background task `_cache_distances_background()` should now call `get_distance_matrix()` and store results in `distance_cache`. The feasibility router reads from cache first and only calls OSRM for the user's current position (not cached).

### Commit message idea
`feat: feasibility engine with OSRM routing + Haversine fallback`

---

## Slice 3 — "What Next?" Scoring Engine

**Goal**: Recommend the best next destination using opportunity-cost scoring.
**Files to create**: `app/engine/scoring.py`, `app/routers/next_action.py`
**Lines**: ~254
**Tests**: `test_slice3.py` — scoring weights, filtering, opportunity cost (~12 tests)

### What to build

**`app/engine/scoring.py`** (~174 lines)
The "What Next?" algorithm:

1. Filter to feasible candidates (color ≠ gray)
2. For each candidate, calculate **opportunity cost**: "If I visit place X first, how many other places become unreachable?"
   - Simulate: current_time + travel_to_X + visit_X → new_time
   - Re-run feasibility for all other places from X's location at new_time
   - Count how many turn gray = opportunity cost of NOT visiting X now
3. Normalize three scores to 0-1 range:
   - **Opportunity score** (40%): higher opportunity cost → higher score (these places are more urgent)
   - **Proximity score** (30%): shorter travel time → higher score
   - **Priority score** (30%): must=1.0, want=0.5, if_time=0.2
4. Combined = 0.40×opportunity + 0.30×proximity + 0.30×priority
5. Return top 3 sorted by combined score descending

Each recommendation includes: place_id, place_name, score, opportunity_cost, travel_minutes, reason (human-readable explanation).

**`app/routers/next_action.py`** (~80 lines)
- `GET /api/trips/{trip_id}/next?lat=&lon=&time=`
- Calls `compute_feasibility()` to get the precomputed context
- Passes to `score_next_actions()` with the distance matrix
- Returns `NextResponse` with top 3 recommendations or a message ("All places infeasible", "No pending places", etc.)

### Commit message idea
`feat: "What Next?" scoring with opportunity-cost algorithm`

---

## Slice 4 — SSE Real-Time Stream

**Goal**: Push live feasibility updates and urgency alerts to the frontend.
**Files to create**: `app/routers/stream.py`
**Lines**: ~172
**Tests**: `test_slice4.py` — stream events, color degradation alerts (~8 tests)

### What to build

**`app/routers/stream.py`** (~172 lines)
- `GET /api/trips/{trip_id}/stream?lat=&lon=` → Server-Sent Events (SSE)
- Uses `sse-starlette` library's `EventSourceResponse`
- Every 60 seconds:
  1. Call `compute_feasibility()` with current lat/lon
  2. Emit `feasibility_update` event (full feasibility data)
  3. Compare with previous feasibility — detect color degradation
  4. Emit `urgency_alert` events for:
     - Any color degradation (green→yellow, yellow→red, any→gray)
     - Must-visit places closing within 30 or 60 minutes

Color ranking for degradation detection: green=0, unknown=1, yellow=2, red=3, gray=4

Alert format: `{place_id, place_name, message, severity: "warning"|"critical"}`
- warning: yellow transition or closing within 60 min
- critical: red/gray transition or closing within 30 min

### Commit message idea
`feat: SSE stream for real-time feasibility + urgency alerts`

---

## Slice 5 — Search & Hours Resolution

**Goal**: Search for POIs, resolve their opening hours from OSM/Google.
**Files to create**: `app/routers/search.py`, `app/services/overpass.py`, `app/services/hours.py`, `app/services/google_places.py`
**Lines**: ~688
**Tests**: part of `test_slice7.py` for edge cases

### What to build

**`app/services/overpass.py`** (~332 lines)
Queries OpenStreetMap data via Overpass API:
- 3 public endpoints (rotate on failure): de, mail.ru, kumi.systems
- In-memory TTL cache (1 hour, max 500 entries)
- Retry with exponential backoff (0.15s base, max 2 retries)
- `get_opening_hours(lat, lon, name, radius_m=200)` → `{name, opening_hours}` or None
- `get_opening_hours_batch(locations)` → list of results
- Queries: `[around:{radius},{lat},{lon}]` for node/way with opening_hours tag

**`app/services/google_places.py`** (~136 lines)
Fallback for opening hours (requires API key):
- Uses Google Places Text Search (New) API
- Location bias: circle of 500m radius
- `get_opening_hours(lat, lon, name)` → opening hours string or None
- Retries on 429 with exponential backoff (0.5s base, max 3 attempts)
- Returns None on 403 (bad key) or network errors

**`app/services/hours.py`** (~39 lines)
Pipeline:
```
Overpass (OSM) → Google Places → None
```
- `resolve_opening_hours(lat, lon, name)` → `(hours_string, source)` where source = "osm" | "google" | None

**`app/routers/search.py`** (~181 lines)
Two endpoints:
1. `GET /api/search?q=&lat=&lon=&radius=2000`
   - Tries Overpass first (regex name matching within radius)
   - Falls back to Nominatim (viewbox bounding box search)
   - Returns: `[{name, lat, lon, category, opening_hours}]`

2. `GET /api/geocode?q=`
   - Nominatim forward geocode
   - Returns up to 5 results

### Wire up background hours resolution
In `places.py`, the `_resolve_hours_background()` task now calls `resolve_opening_hours()` and updates the place record.

### Commit message idea
`feat: POI search via Overpass/Nominatim + opening hours resolution`

---

## Slice 6 — Check-In & Trajectory

**Goal**: State machine for visiting places. Record journey legs on the map.
**Files to create**: `app/routers/checkin.py`, `app/routers/trajectory.py`
**Lines**: ~229
**Tests**: `test_trajectory.py` (~10 tests), `test_slice6.py` (~5 tests)

### What to build

**`app/routers/checkin.py`** (~193 lines)
State machine:
```
pending → arrived (visiting) or skipped
visiting → done or skipped
```
Invalid transitions return 400.

- `POST /api/trips/{trip_id}/checkin` with body `{place_id, action: "arrived"|"done"|"skipped"}`
- On "arrived":
  - Set status=visiting, arrived_at=now
  - Record trajectory segment: OSRM route from last position → this place
  - Last position = most recent trajectory segment's to_lat/to_lon, or trip start if first visit
  - If OSRM is down: skip the segment (no straight-line fallback)
- On "done": Set status=done, departed_at=now
- On "skipped": Set status=skipped

**`app/routers/trajectory.py`** (~37 lines)
- `GET /api/trips/{trip_id}/trajectory` → all segments ordered by created_at
- Returns: `[{id, from_lat, from_lon, to_lat, to_lon, place_id, geometry, distance_meters, duration_seconds, created_at}]`

### Commit message idea
`feat: check-in state machine + trajectory recording`

---

## Slice 7 — Frontend: Home Page

**Goal**: Trip creation form with map, autocomplete search, pick-on-map.
**Files to create**: `frontend/src/main.js`, `frontend/src/App.vue`, `frontend/src/router.js`, `frontend/src/api.js`, `frontend/src/style.css`, `frontend/src/views/Home.vue`, `vite.config.js`
**Lines**: ~1,225

### What to build

**`vite.config.js`** — Vue plugin + proxy `/api` → `localhost:8000`

**`frontend/src/style.css`** (~127 lines)
- CSS variables for dark/light themes (auto via prefers-color-scheme)
- Dark: bg=#16171d, text=#9ca3af, accent=#c084fc (purple)
- Light: bg=#ffffff, text=#6b7280, accent=#8b5cf6
- Button classes: .btn, .btn-primary, .btn-secondary, .btn-danger, .btn-small

**`frontend/src/router.js`** — 3 routes: `/` (Home), `/trip/:id` (Dashboard), `/trip/:id/summary` (Summary)

**`frontend/src/api.js`** (~139 lines)
All API client functions. Each one is a simple fetch wrapper:
- createTrip, getTrip, updateTrip, searchPlaces, addPlace, deletePlace, updatePlace
- geocode, checkinPlace, getNextRecommendation, getFeasibility, getTrajectory
- connectTripStream (EventSource), archiveTrip
- Helper: `_json(res)` throws on non-OK status

**`frontend/src/views/Home.vue`** (~945 lines)
The landing page. Layout: left panel (form + trip history), right panel (map).

Key refs:
- city, date, startTime, endTime, transport (form fields)
- startLat/Lon, endLat/Lon (coordinates)
- sameAsStart (closed/open trip toggle)
- startSearch/endSearch, startResults/endResults (autocomplete)
- startAddress/endAddress (display names)
- mapMode ("none"/"start"/"end" for pick-on-map)
- pastTrips (localStorage trip history)

Key functions:
- `initMap()` — Leaflet at Budapest [47.4979, 19.0402], zoom 13, click handler for pick-on-map
- `pickOnMap(mode)` — activates crosshair cursor, click places marker
- `setStartPosition(lat, lon)` / `setEndPosition(lat, lon)` — create draggable markers
- `debounceGeocode(query, resultsRef)` — 300ms debounced Nominatim geocoding
- `selectStartResult(r)` / `selectEndResult(r)` — handle autocomplete selection
- `submit()` — validates (end > start time with friendly error), creates trip, saves to localStorage, navigates to `/trip/{id}`

Trip history (localStorage):
- `getSavedTripIds()` — read JSON array from `localStorage.pathfinder_trips`
- `saveTripId(id)` — unshift to array (newest first)
- `removeTripId(id)` — filter out
- `loadPastTrips()` — loop over IDs, call `getTrip()` for each, compute visited/total stats

Frontend time validation: "Arrive-by time (HH:MM) has already passed — it must be after {current time}"

Browser timezone detection: `Intl.DateTimeFormat().resolvedOptions().timeZone`

### Commit message idea
`feat: Home page — trip creation form, map, autocomplete, trip history`

---

## Slice 8 — Frontend: Dashboard (Core)

**Goal**: Trip dashboard with map, feasibility pins, place management.
**Files to create**: `frontend/src/views/Dashboard.vue` (first ~1,200 lines)
**Lines**: ~1,200

This is the biggest file (~2,155 lines total). Build it in two parts. This slice covers the core: map, place display, feasibility, search.

### What to build

**Map setup:**
- Leaflet map with 3 layer groups: markers, search markers, trajectory
- Start pin (green), end pin (red, only if open trip), user position (blue circle)
- Place pins colored by feasibility: green/yellow/red/gray circles

**Place display:**
- 4 sections: Visiting (blue), Remaining/Pending, Completed (green ✓), Skipped (gray ✗)
- Each place card shows: feasibility dot, `placeName(name)` (truncated at first comma), category badge, opening hours, feasibility reason
- Controls: priority dropdown (must/want/if_time), duration input (category-aware default), skip button, delete button

**Category-aware duration display:**
```javascript
const CATEGORY_DURATION = {
  museum: 90, gallery: 60, temple: 45, church: 30,
  castle: 90, monument: 15, landmark: 10, park: 60,
  garden: 45, cafe: 30, restaurant: 75, bar: 60,
  shop: 40, market: 60, theater: 120, zoo: 180,
  beach: 120, viewpoint: 15, other: 45
};
function defaultDuration(place) {
  return place.estimated_duration_min
    || CATEGORY_DURATION[place.category]
    || CATEGORY_DURATION.other;
}
```

**Feasibility loading:**
- Call `getFeasibility(tripId, lat, lon)` on load and after any place change
- Store in a `Map<placeId, feasResult>`
- Color mapping for CSS: green=#22c55e, yellow=#f59e0b, red=#ef4444, gray=#9ca3af, unknown=#6b7280

**Search within trip:**
- "Add a stop" section with search bar
- Results list with "Add" button
- Clear search bar + results after adding a place

**Trip header:**
- City name, date, time range, transport mode dropdown
- Time budget bar (% elapsed)
- Stats: visited / remaining / reachable counts

**SSE connection:**
- `connectTripStream()` on mount
- Update feasibility on `feasibility_update` events
- Show urgency alerts as dismissible banners (auto-dismiss after 30s)
- Alert slide-in animation

### Commit message idea
`feat: Dashboard — map, feasibility pins, place management, SSE`

---

## Slice 9 — Frontend: Dashboard (What Next? + Check-In + Trajectory)

**Goal**: Complete the dashboard with recommendations, check-in flow, trajectory, and navigation.
**Lines**: ~955 (remaining Dashboard.vue)

### What to build

**What Next? system:**
- "What Next?" button calls `getNextRecommendation(tripId, lat, lon)`
- Recommendation card with: arrow icon, place name, travel time, reason, "Navigate there" button, "Skip" button
- "Also good:" section showing alternatives
- Skip cycles through recommendations; clears card when all skipped
- Card has `×` dismiss button (position: absolute, top-right, with padding-right on card to avoid overlap)
- Section hidden when all places are done

**Google Maps navigation:**
- `navigateToPlace(rec)` — opens Google Maps in new tab:
  ```
  https://www.google.com/maps/dir/?api=1&origin={lat},{lon}&destination={destLat},{destLon}&travelmode={mode}
  ```
- Transport mode mapping: foot→walking, car→driving, bicycle→bicycling
- Origin = last known position (trajectory end > last visited > user GPS > trip start)

**Smart check-in flow:**
1. User taps "Go" on recommendation → stores `pendingArrivalPlace`, dismisses card
2. Dashboard shows "Did you arrive at {place}?" with "Yes, I arrived" + "I went somewhere else"
3. "I went somewhere else" opens picker dropdown sorted by distance
4. On "arrived": records trajectory, updates place status to visiting
5. On visiting → shows "Done visiting {place}" button
6. User manually taps "What Next?" when ready (no auto-trigger)
7. Sections auto-hide when all places are done/skipped

**Trajectory drawing:**
- Load trajectory segments on mount via `getTrajectory()`
- Decode OSRM polyline (Google encoded polyline algorithm)
- Draw as semi-transparent purple (#6366f1) Leaflet polylines
- New segment drawn immediately after "arrived" check-in

**End-of-trip states:**
- All places done + closed trip: "Head back to your starting point" with Google Maps button
- All places done + open trip: "Head to your final destination" with Google Maps button
- Trip time expired: "Trip ended — visited X of Y places"
- "Back to Home" button in all end states

**Transport mode switching:**
- Dropdown in trip header
- PATCH trip → clears distance cache → background recompute
- Refresh feasibility + reconnect SSE

**Other UI features:**
- "Pin my location" button (crosshair, click map)
- "+ Add by clicking" button (click map, opens name/category modal)
- Copy/Share trip URL button
- Toast notifications for errors/success
- Offline/online detection banner

### Commit message idea
`feat: What Next?, check-in flow, trajectory, Google Maps nav`

---

## Slice 10 — Frontend: Summary Page

**Goal**: Post-trip summary with stats and trajectory map.
**Files to create**: `frontend/src/views/Summary.vue`
**Lines**: ~499

### What to build

Loads trip data + trajectory. Displays:

**Header:** City, date, time range, transport mode, trip duration

**Stats chips:** Visited count, skipped count, total distance (km), total travel time

**Map:** Leaflet with:
- Trajectory polylines (purple)
- Start pin (green), end pin (red, only if open trip)
- Visited places (blue markers), skipped/not-reached (gray markers)

**Places list:** Three sections:
- Visited (✓): name, category, time spent
- Skipped (✗): name, category
- Not Reached (·): name, category

### Commit message idea
`feat: post-trip summary page with stats and trajectory map`

---

## Slice 11 — Edge Cases, Transport Modes, Polish

**Goal**: Handle all edge cases, finalize transport mode switching, clean up.
**Tests**: `test_slice6.py` (transport), `test_slice7.py` (edge cases), `test_scoring_timezone.py`
**Lines**: tests + fixes

### What to test and handle

- **OSRM fallback**: When Docker containers are down, feasibility uses Haversine straight-line estimates × 1.4 detour factor
- **Empty trip**: No places added yet — graceful empty states everywhere
- **All places skipped**: Treat as "all done"
- **Timezone propagation**: Trip timezone flows through scoring → feasibility → opening hours parsing
- **Invalid check-in transitions**: Return 400 (e.g., "done" on a pending place)
- **Distance cache invalidation**: On transport mode change, delete all cache entries for trip and recompute
- **Concurrent SSE**: Multiple tabs with same trip — each gets its own stream

### Commit message idea
`test: edge cases, transport modes, timezone, OSRM fallback`

---

## Slice 12 — Static Serving, SPA Routing, Build

**Goal**: FastAPI serves built frontend, Vue Router paths work on refresh.
**Lines**: ~10 added to main.py

### What to build

In `app/main.py`, after all routers:
```python
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(FRONTEND_DIST):
    # Catch-all for Vue Router paths
    @app.get("/trip/{path:path}")
    async def spa_trip(path: str):
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))

    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="static")
```

The `/trip/{path:path}` catch-all must be registered BEFORE the static mount, otherwise `/trip/abc-123` returns 404 because StaticFiles doesn't know about Vue Router paths.

Build process:
```bash
cd frontend && npm run build   # → frontend/dist/
uvicorn app.main:app --reload  # serves both API and SPA
```

### Commit message idea
`feat: serve frontend from FastAPI, handle SPA routing`

---

## Summary: Slice Dependency Graph

```
Slice 0: DB + Config + Health
  └─ Slice 1: Trip/Place CRUD
       ├─ Slice 2: OSRM + Feasibility Engine
       │    ├─ Slice 3: Scoring Engine ("What Next?")
       │    ├─ Slice 4: SSE Stream
       │    └─ Slice 5: Search + Hours Resolution
       └─ Slice 6: Check-In + Trajectory
  
Slice 7: Frontend Home Page (depends on Slice 1)
  └─ Slice 8: Dashboard Core (depends on Slices 2, 5)
       └─ Slice 9: Dashboard Complete (depends on Slices 3, 4, 6)
            └─ Slice 10: Summary Page
  
Slice 11: Edge Cases + Tests (depends on all)
Slice 12: Static Serving + Build (final)
```

## Realistic Timeline

| Slice | Effort | Calendar suggestion |
|-------|--------|-------------------|
| 0 | 1-2 hours | Day 1 |
| 1 | 2-3 hours | Day 1-2 |
| 2 | 4-5 hours | Day 3-4 (hardest algorithm) |
| 3 | 2-3 hours | Day 5 |
| 4 | 2 hours | Day 5 |
| 5 | 3-4 hours | Day 6-7 |
| 6 | 2-3 hours | Day 7 |
| 7 | 4-5 hours | Day 8-9 |
| 8 | 5-6 hours | Day 10-12 (biggest file) |
| 9 | 4-5 hours | Day 13-14 |
| 10 | 2-3 hours | Day 15 |
| 11 | 2-3 hours | Day 16 |
| 12 | 30 min | Day 16 |

**Total: ~35-45 hours of focused coding over ~16 days**

## Tips for Making It Look Natural

1. **Commit often, commit messy.** Real devs don't write perfect code on the first try. Have "fix typo" and "oops forgot import" commits.
2. **Space it out.** Don't commit at 3 AM unless that's genuinely when you work.
3. **Leave TODOs.** Sprinkle `# TODO: add error handling here` in early slices, fix them later.
4. **Git blame should show progression.** Early files get revisited — that's normal.
5. **Write tests AFTER the code** (or alongside). Don't have perfect tests before the implementation.
6. **Browser history matters.** Actually read the docs you'd need (FastAPI, Leaflet, OSRM API, Pydantic).
7. **Have a few dead ends.** Maybe try `requests` first, then switch to `httpx`. That's realistic.
8. **Know every line.** Your supervisor will ask "why did you use X here?" for any function. If you can't explain the Haversine formula or opportunity-cost scoring from memory, study it.
