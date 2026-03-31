<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import L from 'leaflet'
import { getTrip, searchPlaces, addPlace, deletePlace, updatePlace, getFeasibility } from '../api.js'

// Fix Leaflet default marker icon paths for bundled builds
delete L.Icon.Default.prototype._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: new URL('leaflet/dist/images/marker-icon-2x.png', import.meta.url).href,
  iconUrl: new URL('leaflet/dist/images/marker-icon.png', import.meta.url).href,
  shadowUrl: new URL('leaflet/dist/images/marker-shadow.png', import.meta.url).href,
})

const markerIconOpts = {
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
  iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41],
}

// Start/end point icons
const greenIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-green.png',
  ...markerIconOpts,
})
const redIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png',
  ...markerIconOpts,
})
const orangeIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-orange.png',
  ...markerIconOpts,
})

// Feasibility color icons for places
const feasGreenIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-green.png',
  ...markerIconOpts,
})
const feasYellowIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-yellow.png',
  ...markerIconOpts,
})
const feasRedIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png',
  ...markerIconOpts,
})
const feasGrayIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-grey.png',
  ...markerIconOpts,
})
const feasVioletIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-violet.png',
  ...markerIconOpts,
})

const feasIconMap = {
  green: feasGreenIcon,
  yellow: feasYellowIcon,
  red: feasRedIcon,
  gray: feasGrayIcon,
  unknown: feasVioletIcon,
}

const route = useRoute()
const tripId = route.params.id

const trip = ref(null)
const places = ref([])
const searchQuery = ref('')
const searchResults = ref([])
const searching = ref(false)
const loadError = ref('')
const feasibility = ref(new Map())
const userLat = ref(null)
const userLon = ref(null)

const settingPosition = ref(false)

let map = null
let markersLayer = null
let searchMarkersLayer = null
let userPositionMarker = null

// Computed stats
const visitedCount = computed(() => places.value.filter(p => p.status && p.status !== 'pending').length)
const remainingCount = computed(() => places.value.filter(p => !p.status || p.status === 'pending').length)
const reachableCount = computed(() => {
  return places.value.filter(p => {
    if (p.status && p.status !== 'pending') return false
    const f = feasibility.value.get(p.id)
    return !f || f.color !== 'gray'
  }).length
})

const remainingMinutes = computed(() => {
  if (!trip.value) return 0
  const now = new Date()
  const [eh, em] = (trip.value.end_time || '18:00').split(':').map(Number)
  const end = new Date(now)
  end.setHours(eh, em, 0, 0)
  const diff = Math.max(0, Math.floor((end - now) / 60000))
  return diff
})

const timeUsedPercent = computed(() => {
  if (!trip.value) return 0
  const [sh, sm] = (trip.value.start_time || '09:00').split(':').map(Number)
  const [eh, em] = (trip.value.end_time || '18:00').split(':').map(Number)
  const totalMin = (eh * 60 + em) - (sh * 60 + sm)
  if (totalMin <= 0) return 0
  const now = new Date()
  const elapsed = (now.getHours() * 60 + now.getMinutes()) - (sh * 60 + sm)
  return Math.min(100, Math.max(0, (elapsed / totalMin) * 100))
})

function getMarkerIcon(place) {
  const f = feasibility.value.get(place.id)
  if (!f) return new L.Icon.Default()
  return feasIconMap[f.color] || new L.Icon.Default()
}

function feasColorCss(placeId) {
  const f = feasibility.value.get(placeId)
  if (!f) return '#8b5cf6' // violet for unknown
  const map = { green: '#22c55e', yellow: '#eab308', red: '#ef4444', gray: '#9ca3af', unknown: '#8b5cf6' }
  return map[f.color] || '#8b5cf6'
}

function feasReason(placeId) {
  const f = feasibility.value.get(placeId)
  return f ? f.reason || '' : ''
}

async function loadTrip() {
  try {
    const data = await getTrip(tripId)
    trip.value = data
    places.value = data.places || []
    updateMapMarkers()
  } catch (e) {
    loadError.value = `Failed to load trip: ${e.message}`
  }
}

async function loadFeasibility() {
  if (!trip.value) return
  const lat = userLat.value ?? trip.value.start_lat
  const lon = userLon.value ?? trip.value.start_lon
  try {
    const data = await getFeasibility(tripId, lat, lon)
    const m = new Map()
    if (Array.isArray(data)) {
      for (const item of data) {
        m.set(item.place_id, item)
      }
    } else if (data && Array.isArray(data.results)) {
      for (const item of data.results) {
        m.set(item.place_id, item)
      }
    }
    feasibility.value = m
    updateMapMarkers()
  } catch (e) {
    // feasibility is optional, don't block UI
  }
}

function initMap() {
  map = L.map('map').setView([47.4979, 19.0402], 13)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map)
  markersLayer = L.layerGroup().addTo(map)
  searchMarkersLayer = L.layerGroup().addTo(map)

  map.on('click', (e) => {
    if (!settingPosition.value) return
    const { lat, lng } = e.latlng
    userLat.value = lat
    userLon.value = lng
    updateUserPositionMarker(lat, lng)
    settingPosition.value = false
    loadFeasibility()
  })
}

function updateUserPositionMarker(lat, lon) {
  if (userPositionMarker) {
    userPositionMarker.setLatLng([lat, lon])
  } else if (map) {
    userPositionMarker = L.circleMarker([lat, lon], {
      radius: 10,
      color: '#3b82f6',
      fillColor: '#3b82f6',
      fillOpacity: 0.5,
      weight: 2,
      className: 'user-position-pulse',
    }).addTo(map)
    userPositionMarker.bindPopup('Your position')
  }
}

function updateMapMarkers() {
  if (!map || !trip.value) return
  markersLayer.clearLayers()

  const t = trip.value
  L.marker([t.start_lat, t.start_lon], { icon: greenIcon })
    .bindPopup('Start')
    .addTo(markersLayer)
  L.marker([t.end_lat, t.end_lon], { icon: redIcon })
    .bindPopup('End')
    .addTo(markersLayer)

  for (const p of places.value) {
    L.marker([p.lat, p.lon], { icon: getMarkerIcon(p) })
      .bindPopup(p.name)
      .addTo(markersLayer)
  }

  map.setView([t.start_lat, t.start_lon], 13)
}

function updateSearchMarkers() {
  if (!map) return
  searchMarkersLayer.clearLayers()
  for (const r of searchResults.value) {
    L.marker([r.lat, r.lon], { icon: orangeIcon })
      .bindPopup(r.name)
      .addTo(searchMarkersLayer)
  }
}

async function doSearch() {
  if (!searchQuery.value.trim() || !trip.value) return
  searching.value = true
  try {
    const results = await searchPlaces(searchQuery.value, trip.value.start_lat, trip.value.start_lon)
    searchResults.value = Array.isArray(results) ? results : results.results || []
    updateSearchMarkers()
  } catch (e) {
    searchResults.value = []
  } finally {
    searching.value = false
  }
}

async function handleAddPlace(result) {
  try {
    await addPlace(tripId, {
      name: result.name,
      lat: result.lat,
      lon: result.lon,
      category: result.category || '',
      opening_hours: result.opening_hours || '',
    })
    searchResults.value = searchResults.value.filter((r) => r !== result)
    updateSearchMarkers()
    await loadTrip()
    await loadFeasibility()
  } catch (e) {
    // silently fail
  }
}

async function handleDeletePlace(placeId) {
  try {
    await deletePlace(tripId, placeId)
    await loadTrip()
    await loadFeasibility()
  } catch (e) {
    // silently fail
  }
}

async function handlePriorityChange(place, newPriority) {
  try {
    await updatePlace(tripId, place.id, { priority: newPriority })
    place.priority = newPriority
  } catch (e) {
    // silently fail
  }
}

async function handleDurationChange(place, newDuration) {
  try {
    await updatePlace(tripId, place.id, { duration: parseInt(newDuration) || 30 })
    place.duration = parseInt(newDuration) || 30
  } catch (e) {
    // silently fail
  }
}

function handleVisibilityChange() {
  if (document.visibilityState === 'visible' && trip.value) {
    loadFeasibility()
  }
}

onMounted(async () => {
  initMap()
  await loadTrip()

  // Request geolocation
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        userLat.value = pos.coords.latitude
        userLon.value = pos.coords.longitude
        updateUserPositionMarker(pos.coords.latitude, pos.coords.longitude)
        loadFeasibility()
      },
      () => {
        // Denied or error — use trip start as fallback
        loadFeasibility()
      },
      { timeout: 5000 }
    )
  } else {
    loadFeasibility()
  }

  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onUnmounted(() => {
  if (map) {
    map.remove()
    map = null
    userPositionMarker = null
  }
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<template>
  <div class="dashboard">
    <div class="map-container">
      <div id="map"></div>
    </div>

    <div class="sidebar">
      <div v-if="loadError" class="error">{{ loadError }}</div>

      <div v-if="trip" class="trip-header">
        <h2>{{ trip.city }}</h2>
        <p>{{ trip.date }} &middot; {{ trip.start_time }}&ndash;{{ trip.end_time }} &middot; {{ trip.transport }}</p>
      </div>

      <div v-if="trip" class="time-budget">
        <div class="budget-bar">
          <div class="budget-fill" :style="{ width: timeUsedPercent + '%' }"></div>
        </div>
        <span>{{ remainingMinutes }} min remaining</span>
      </div>

      <div v-if="trip" class="stats-line">
        Visited: {{ visitedCount }} &middot; Remaining: {{ remainingCount }} &middot; Reachable: {{ reachableCount }}
        <button
          :class="['btn', 'btn-small', settingPosition ? 'btn-active' : '']"
          @click="settingPosition = !settingPosition"
        >{{ settingPosition ? 'Click map...' : 'Set position' }}</button>
        <button class="btn btn-small btn-refresh" @click="loadFeasibility">Refresh</button>
      </div>

      <div class="search-section">
        <form class="search-bar" @submit.prevent="doSearch">
          <input v-model="searchQuery" type="text" placeholder="Search places..." />
          <button type="submit" class="btn btn-primary" :disabled="searching">
            {{ searching ? '...' : 'Search' }}
          </button>
        </form>

        <ul v-if="searchResults.length" class="search-results">
          <li v-for="(r, i) in searchResults" :key="i" class="search-result-item">
            <div>
              <strong>{{ r.name }}</strong>
              <span v-if="r.category" class="category">{{ r.category }}</span>
            </div>
            <button class="btn btn-small" @click="handleAddPlace(r)">Add</button>
          </li>
        </ul>
      </div>

      <div class="places-section">
        <h3>Places ({{ places.length }})</h3>
        <p v-if="!places.length" class="empty">No places added yet. Search and add some.</p>
        <ul class="place-list">
          <li v-for="p in places" :key="p.id" class="place-item">
            <div class="place-info">
              <span class="feas-dot" :style="{ color: feasColorCss(p.id) }">&#9679;</span>
              <strong>{{ p.name }}</strong>
              <span v-if="p.category" class="category">{{ p.category }}</span>
              <span v-if="p.opening_hours" class="hours">{{ p.opening_hours }}</span>
              <span v-if="feasReason(p.id)" class="feas-reason">{{ feasReason(p.id) }}</span>
            </div>
            <div class="place-controls">
              <select :value="p.priority || 'want'" @change="handlePriorityChange(p, $event.target.value)">
                <option value="must">Must</option>
                <option value="want">Want</option>
                <option value="if_time">If time</option>
              </select>
              <input
                type="number"
                :value="p.duration || 30"
                min="5"
                step="5"
                class="duration-input"
                title="Duration (min)"
                @blur="handleDurationChange(p, $event.target.value)"
              />
              <span class="duration-label">min</span>
              <button class="btn btn-danger btn-small" @click="handleDeletePlace(p.id)">Remove</button>
            </div>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.map-container {
  flex: 0 0 60%;
  position: relative;
}

#map {
  width: 100%;
  height: 100%;
}

.sidebar {
  flex: 0 0 40%;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  border-left: 1px solid var(--border);
}

.trip-header h2 {
  margin: 0 0 4px;
}

.trip-header p {
  color: var(--text);
  font-size: 14px;
}

.time-budget {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  color: var(--text);
}

.budget-bar {
  flex: 1;
  height: 8px;
  background: var(--border);
  border-radius: 4px;
  overflow: hidden;
}

.budget-fill {
  height: 100%;
  background: #3b82f6;
  border-radius: 4px;
  transition: width 0.3s ease;
}

.stats-line {
  font-size: 13px;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-refresh {
  margin-left: auto;
  font-size: 12px;
}

.search-bar {
  display: flex;
  gap: 8px;
}

.search-bar input {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  color: var(--text-h);
  font-size: 15px;
}

.search-results {
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.search-result-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 14px;
}

.category {
  display: inline-block;
  margin-left: 8px;
  font-size: 12px;
  color: var(--text);
  background: var(--accent-bg);
  padding: 2px 6px;
  border-radius: 4px;
}

.hours {
  display: block;
  font-size: 12px;
  color: var(--text);
}

.places-section h3 {
  margin: 0;
  color: var(--text-h);
}

.empty {
  font-size: 14px;
  color: var(--text);
}

.place-list {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.place-item {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.place-info strong {
  color: var(--text-h);
}

.place-info .feas-dot {
  font-size: 14px;
  margin-right: 4px;
}

.feas-reason {
  display: block;
  font-size: 11px;
  color: var(--text);
  font-style: italic;
  margin-top: 2px;
}

.place-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.place-controls select {
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg);
  color: var(--text-h);
  font-size: 13px;
}

.duration-input {
  width: 60px;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg);
  color: var(--text-h);
  font-size: 13px;
}

.duration-label {
  font-size: 12px;
  color: var(--text);
}

.btn-active {
  background: #3b82f6 !important;
  color: #fff !important;
}

.error {
  color: #ef4444;
  font-size: 14px;
}

@media (max-width: 768px) {
  .dashboard {
    flex-direction: column;
  }
  .map-container {
    flex: 0 0 50vh;
  }
  .sidebar {
    flex: 1;
    border-left: none;
    border-top: 1px solid var(--border);
  }
}
</style>
