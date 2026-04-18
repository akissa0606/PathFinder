# PathFinder — Algorithm Documentation

This document explains the three core algorithms in detail: feasibility scoring, "What Next?" recommendation, and opening hours parsing. Understanding these is essential for a thesis defense.

---

## 1. Feasibility Engine

**File:** `app/engine/feasibility.py`  
**Purpose:** For each pending place, determine whether it's still possible to visit it within the trip's time constraints.

### The Core Question
"If I go to place X right now, can I visit it AND still make it back to my end point before my trip ends?"

### Input
- Current position (lat/lon)
- Current time
- Trip end time
- Trip end point coordinates
- List of pending places with visit durations
- Distance matrix (travel times in seconds between all points, from OSRM or Haversine fallback)

### Algorithm per place

```
total_needed = travel_to_place + visit_duration + travel_from_place_to_endpoint
available_time = trip_end_time - current_time
slack = available_time - total_needed
slack_ratio = slack / available_time   (0.0 = exactly fits, negative = impossible)
```

### Color assignment logic

```
if slack < 0:
    → GRAY (mathematically impossible, not enough time even ignoring opening hours)

if place has opening_hours:
    parse closing_time for today
    if current_time + travel_to_place >= closing_time:
        → GRAY (would arrive after closing)
    minutes_until_closing = closing_time - current_time

    if minutes_until_closing < 30 OR slack_ratio < 0.10:
        → RED (very urgent)
    elif minutes_until_closing < 120 OR slack_ratio < 0.30:
        → YELLOW (moderately urgent)
    else:
        → GREEN (comfortable)

elif slack_ratio < 0.10:
    → RED
elif slack_ratio < 0.30:
    → YELLOW
else:
    → UNKNOWN (no hours data, time is fine — shown as purple/violet in UI)
```

### OSRM Fallback (Haversine)

When OSRM containers are down, travel times are estimated using the Haversine great-circle formula with a detour factor:

```python
def haversine_meters(lat1, lon1, lat2, lon2):
    R = 6_371_000  # Earth radius in meters
    φ1, φ2 = radians(lat1), radians(lat2)
    Δφ = radians(lat2 - lat1)
    Δλ = radians(lon2 - lon1)
    a = sin(Δφ/2)**2 + cos(φ1)*cos(φ2)*sin(Δλ/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

straight_line = haversine_meters(...)
road_estimate = straight_line * 1.4   # 40% detour factor for real roads

# Speed by transport mode:
# foot:    1.4 m/s  (~5 km/h walking)
# bicycle: 4.2 m/s  (~15 km/h cycling)
# car:     8.3 m/s  (~30 km/h urban driving)

travel_seconds = road_estimate / speed
```

The 1.4 detour factor is a standard approximation: real road distances are typically 20-50% longer than straight-line distances, with 1.4 being a reasonable urban average.

### Distance Cache

OSRM is slow for large matrices. When a place is added:
1. A background task calls `get_distance_matrix()` for all place pairs in the trip
2. Results stored in `distance_cache` table
3. On feasibility requests: cached times are used for place-to-place; only user's current position requires a fresh OSRM call (since it changes constantly)

---

## 2. "What Next?" Scoring Engine

**File:** `app/engine/scoring.py`  
**Purpose:** Recommend the single best next destination using an opportunity-cost weighted scoring system.

### Why Opportunity Cost?

Simple proximity ("go to the nearest place") is wrong. If place A is close but doesn't close until 8 PM, and place B is slightly further but closes at 2 PM, you should go to B first. The opportunity cost of visiting A first is that B becomes unreachable.

### Algorithm

**Step 1: Filter candidates**
```
candidates = [p for p in pending_places if feasibility[p].color != "gray"]
```
Only places that are still reachable are considered.

**Step 2: Calculate opportunity cost for each candidate**
```
For candidate X:
    simulate: go to X now
    new_time = current_time + travel_to_X + visit_duration_X
    new_position = X's coordinates
    
    re-run feasibility for all OTHER pending places
    from new_position at new_time
    
    opportunity_cost_X = count of places that turn gray in this simulation
    (these are places you'd lose by visiting X first)
```

Counterintuitively: **high opportunity cost = high priority**. If visiting X first costs you 2 other places, X is NOT urgent — those 2 other places ARE urgent. So we use opportunity cost as a signal that the OTHER places need to be visited before X... but actually, visiting X first when other things become impossible means X is fine later. Wait, let me re-read.

Actually the logic is: the opportunity cost of visiting X is how many places become impossible AFTER visiting X. High opportunity cost means visiting X "locks you out" of many other places. Therefore places with HIGH opportunity cost are ones you should visit LAST (or carefully). But the scoring weights it at 40%, with higher opportunity cost → higher score. The rationale: if visiting X causes maximum damage to your remaining options, it means X is the constraint — X must be dealt with now because deferring it while visiting others might make X itself unreachable (since X's closing time is the constraint creating that bottleneck).

In practice: places with high opportunity cost tend to be the ones with tight closing time windows.

**Step 3: Normalize all scores to [0, 1]**
```
opportunity_score = opportunity_cost / max(opportunity_cost_across_all_candidates)
proximity_score = 1 - (travel_time / max(travel_time_across_all_candidates))
priority_score = {"must": 1.0, "want": 0.5, "if_time": 0.2}[place.priority]
```

**Step 4: Weighted combination**
```
combined = 0.40 × opportunity_score
         + 0.30 × proximity_score
         + 0.30 × priority_score
```

Weights rationale:
- **40% opportunity cost**: The most important signal — time constraints drive urgency
- **30% proximity**: Efficiency matters; nearby places are preferred when urgency is equal
- **30% priority**: User preference (must-see vs. nice-to-have)

**Step 5: Return top 3**
Sort by combined score descending, return first 3.

### Human-readable reason generation

Each recommendation includes a reason string:
- "Visit now — skipping would make 2 other places unreachable"
- "Closest option with good time margin"
- "High priority, closes at 17:00 (in 45 min)"

---

## 3. Opening Hours Parser

**File:** `app/engine/feasibility.py`, function `parse_closing_time()`  
**Purpose:** Parse OSM-format opening hours strings and return the closing time for a specific date.

### OSM Opening Hours Format

OpenStreetMap uses a structured string format, e.g.:
- `"Mo-Fr 09:00-18:00"` — weekdays 9am to 6pm
- `"Mo,We,Fr 10:00-17:00"` — Monday, Wednesday, Friday
- `"Sa 09:00-14:00; Su 10:00-13:00"` — different hours per day
- `"24/7"` — always open
- `"Mo-Su 08:00-22:00"` — every day

### Algorithm

```
1. Split by ";" to get multiple day-range rules
2. For each rule:
   a. Parse the day specification (left side of space before time)
   b. Parse the time range (right side)
   c. Check if trip_date's weekday matches the day specification
3. Return closing time as timezone-aware datetime if match found
```

**Day matching:**
```
day_abbr = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}
trip_weekday = trip_date.weekday()  # 0=Monday

# Range like "Mo-Fr":
if "-" in day_spec:
    start_day, end_day = day_spec.split("-")
    start_idx = day_abbr[start_day]
    end_idx = day_abbr[end_day]
    if start_idx <= end_idx:
        match = start_idx <= trip_weekday <= end_idx
    else:
        # Wrapped range like "Fr-Mo"
        match = trip_weekday >= start_idx or trip_weekday <= end_idx

# List like "Mo,We,Fr":
elif "," in day_spec:
    days = [day_abbr[d.strip()] for d in day_spec.split(",")]
    match = trip_weekday in days
```

**Time parsing:**
```
time_part = "09:00-18:00"
open_h, open_m = 9, 0
close_h, close_m = 18, 0

closing_naive = datetime(trip_date.year, trip_date.month, trip_date.day, close_h, close_m)
closing_aware = timezone.localize(closing_naive)  # Using pytz or zoneinfo
closing_utc = closing_aware.astimezone(utc)
```

Returns `None` if the string is unparseable — the feasibility engine treats `None` as "unknown hours."

---

## 4. Trajectory System

**File:** `app/routers/checkin.py`, `app/routers/trips.py`  
**Purpose:** Record the actual path walked/driven between places.

### When a segment is recorded

1. User checks in as "arrived" at a place → segment from last position to this place
2. Trip is archived → segment from last position to trip end point

### OSRM Route Geometry

Segments use OSRM's polyline-encoded route geometry:
```
GET http://localhost:5000/route/v1/foot/{from_lon},{from_lat};{to_lon},{to_lat}
    ?overview=full&geometries=polyline
```

Response includes `geometry` (Google encoded polyline), `distance` (meters), `duration` (seconds).

**Google Encoded Polyline Algorithm** (for frontend decoding):
```javascript
function decodePolyline(encoded) {
    // Each coordinate is encoded as variable-length integers
    // Result: array of [lat, lng] pairs
    // See: https://developers.google.com/maps/documentation/utilities/polylinealgorithm
}
```

### Last Position Logic

```
if trajectory_segments exist for this trip:
    from_position = most_recent_segment.to_lat, to_lon
else:
    from_position = trip.start_lat, trip.start_lon
```

### Closing Segment (Archive)

When archiving:
```
last_pos = last trajectory segment endpoint (or trip start if no segments)
if distance(last_pos, trip.end_point) > 10m:
    call OSRM to route last_pos → trip.end_point
    store as trajectory_segment with place_id = NULL
```

This ensures the summary map shows a complete path including the return leg.

---

## 5. SSE Urgency Detection

**File:** `app/routers/stream.py`  
**Purpose:** Detect when a place's situation is getting worse and alert the user.

### Color Degradation Detection

```python
COLOR_RANK = {"green": 0, "unknown": 1, "yellow": 2, "red": 3, "gray": 4}

for place_id in current_feasibility:
    prev_color = previous_feasibility.get(place_id)
    curr_color = current_feasibility[place_id]
    
    if prev_color and COLOR_RANK[curr_color] > COLOR_RANK[prev_color]:
        # Color got worse → emit urgency_alert
        severity = "critical" if curr_color in ("red", "gray") else "warning"
        emit urgency_alert(place_id, message, severity)
```

### Must-Visit Closing Alerts

Additionally, for `priority = "must"` places with known closing time:
```
minutes_until_close = (closing_time - now).total_seconds() / 60

if minutes_until_close < 30:
    emit urgency_alert(severity="critical", message="Closing in X minutes!")
elif minutes_until_close < 60:
    emit urgency_alert(severity="warning", message="Closing in X minutes")
```

---

## 6. Timezone Handling

**Why timezones matter:** Trip times (`start_time`, `end_time`) are stored as plain `HH:MM` strings. Opening hours from OSM are also local times. A trip ending at 18:00 in Budapest means 16:00 UTC. All feasibility comparisons must use UTC-aware datetimes.

### How it flows through the system

```
Browser: Intl.DateTimeFormat().resolvedOptions().timeZone → "Europe/Budapest"
      ↓ stored in trips.timezone (IANA timezone string)

compute_feasibility() in routers/feasibility.py:
    trip_tz = ZoneInfo(trip["timezone"])   # e.g. Europe/Budapest
    trip_end_dt = datetime.combine(trip_date, time(18, 0), tzinfo=trip_tz).astimezone(utc)
    current_time = datetime.now(utc)
      ↓ trip_timezone string passed to calculate_feasibility()

calculate_feasibility() in engine/feasibility.py:
    Passes trip_timezone to parse_closing_time()
      ↓

parse_closing_time():
    closing_naive = datetime(year, month, day, close_h, close_m)
    tz = ZoneInfo(trip_timezone)
    closing_aware = closing_naive.replace(tzinfo=tz)
    closing_utc = closing_aware.astimezone(utc)
    → compared against current_time (also UTC)
```

### Key rules

1. All `datetime` objects in feasibility comparisons are **UTC-aware**. Never compare naive datetimes.
2. `ZoneInfo` from Python 3.9+ standard library handles IANA names like `"Europe/Budapest"`. No pytz needed.
3. Always wrap `ZoneInfo(name)` in `try/except` and fall back to `timezone.utc` for invalid timezone names.
4. `trip_date` is the local date (stored as `YYYY-MM-DD`). Combined with `trip_timezone` to convert local HH:MM to UTC.

---

## 7. Anime.js Map Animations

**File:** `frontend/src/map-utils.js`  
**Purpose:** Animate a moving dot along Leaflet polylines.

### How it works with Leaflet

Leaflet uses SVG rendering by default. Each `L.polyline` has a `._path` property pointing to the actual SVG `<path>` element. Anime.js v4's `createMotionPath()` can animate any SVG element along a path.

```javascript
import { animate, createMotionPath } from "animejs";

function animateDotAlongPolyline(polyline, durationMs, color, onComplete) {
    const path = polyline._path;           // SVG <path> element
    const parent = path.parentNode;        // Leaflet's <g> element
    
    // Create a circle in the same SVG coordinate space
    const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    dot.setAttribute("cx", "0");
    dot.setAttribute("cy", "0");
    dot.setAttribute("r", "7");
    parent.appendChild(dot);
    
    // createMotionPath returns {translateX, translateY, rotate} as function values
    // that map 0→totalLength progress to x/y coordinates along the path
    animate(dot, {
        ...createMotionPath(path),
        duration: durationMs,
        ease: "inOutSine",          // v4 syntax (not "easing")
        onComplete() {              // v4 syntax (not "complete")
            dot.remove();
            onComplete?.();
        }
    });
}
```

### Three use cases

1. **Arrival animation**: After check-in "arrived", animate dot along the new trajectory segment (2s)
2. **What Next? preview**: Animate an amber dot along a temporary dashed line from current position to the recommendation (1.5s), then remove the line
3. **Journey replay** (Summary page): Animate dot through all segments sequentially, with 300ms pause between each

### Anime.js v4 API notes (changed from v3)

| v3 | v4 |
|---|---|
| `easing: "easeInOutSine"` | `ease: "inOutSine"` |
| `complete: fn` | `onComplete: fn` |
| `targets, props, options` (3 args) | `targets, combinedParams` (2 args) |
| `anime({...})` | `animate(targets, params)` |
