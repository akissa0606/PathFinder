<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { createTrip, geocode } from '../api.js'
import L from 'leaflet'

// Fix Leaflet default marker icon paths
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
const greenIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-green.png',
  ...markerIconOpts,
})
const redIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png',
  ...markerIconOpts,
})

const router = useRouter()

const city = ref('')
const date = ref('')
const startTime = ref('09:00')
const endTime = ref('18:00')
const transport = ref('foot')
const startLat = ref('')
const startLon = ref('')
const endLat = ref('')
const endLon = ref('')
const sameAsStart = ref(true)
const loading = ref(false)
const error = ref('')

// Geocode search state
const startSearch = ref('')
const endSearch = ref('')
const startResults = ref([])
const endResults = ref([])
const startAddress = ref('')
const endAddress = ref('')
const mapMode = ref('start') // 'start' or 'end'

let map = null
let startMarker = null
let endMarker = null
let debounceTimer = null

function initMap() {
  map = L.map('home-map').setView([47.4979, 19.0402], 13)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map)

  map.on('click', (e) => {
    const { lat, lng } = e.latlng
    if (mapMode.value === 'start') {
      setStartPosition(lat, lng)
      startAddress.value = `${lat.toFixed(5)}, ${lng.toFixed(5)}`
    } else {
      setEndPosition(lat, lng)
      endAddress.value = `${lat.toFixed(5)}, ${lng.toFixed(5)}`
    }
  })
}

function setStartPosition(lat, lon) {
  startLat.value = lat.toFixed(6)
  startLon.value = lon.toFixed(6)
  if (startMarker) {
    startMarker.setLatLng([lat, lon])
  } else {
    startMarker = L.marker([lat, lon], { icon: greenIcon, draggable: true }).addTo(map)
    startMarker.bindPopup('Start').openPopup()
    startMarker.on('dragend', () => {
      const pos = startMarker.getLatLng()
      startLat.value = pos.lat.toFixed(6)
      startLon.value = pos.lng.toFixed(6)
      startAddress.value = `${pos.lat.toFixed(5)}, ${pos.lng.toFixed(5)}`
    })
  }
  if (sameAsStart.value) {
    setEndPosition(lat, lon)
  }
}

function setEndPosition(lat, lon) {
  endLat.value = lat.toFixed(6)
  endLon.value = lon.toFixed(6)
  if (sameAsStart.value) {
    if (endMarker) { endMarker.remove(); endMarker = null }
    return
  }
  if (endMarker) {
    endMarker.setLatLng([lat, lon])
  } else {
    endMarker = L.marker([lat, lon], { icon: redIcon, draggable: true }).addTo(map)
    endMarker.bindPopup('End')
    endMarker.on('dragend', () => {
      const pos = endMarker.getLatLng()
      endLat.value = pos.lat.toFixed(6)
      endLon.value = pos.lng.toFixed(6)
      endAddress.value = `${pos.lat.toFixed(5)}, ${pos.lng.toFixed(5)}`
    })
  }
}

watch(sameAsStart, (val) => {
  if (val) {
    if (endMarker) { endMarker.remove(); endMarker = null }
    endLat.value = startLat.value
    endLon.value = startLon.value
  }
})

function debounceGeocode(query, resultRef) {
  clearTimeout(debounceTimer)
  if (!query || query.length < 2) { resultRef.value = []; return }
  debounceTimer = setTimeout(async () => {
    try {
      resultRef.value = await geocode(query)
    } catch {
      resultRef.value = []
    }
  }, 300)
}

watch(startSearch, (val) => debounceGeocode(val, startResults))
watch(endSearch, (val) => debounceGeocode(val, endResults))

function selectStartResult(r) {
  startSearch.value = ''
  startResults.value = []
  startAddress.value = r.name
  setStartPosition(r.lat, r.lon)
  map.setView([r.lat, r.lon], 15)
}

function selectEndResult(r) {
  endSearch.value = ''
  endResults.value = []
  endAddress.value = r.name
  setEndPosition(r.lat, r.lon)
  map.setView([r.lat, r.lon], 15)
}

function useMyLocation() {
  if (!navigator.geolocation) { error.value = 'Geolocation not supported'; return }
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      setStartPosition(pos.coords.latitude, pos.coords.longitude)
      startAddress.value = 'Current location'
      map.setView([pos.coords.latitude, pos.coords.longitude], 15)
    },
    (err) => { error.value = `Location error: ${err.message}` }
  )
}

async function submit() {
  error.value = ''
  if (!city.value || !date.value || !startLat.value || !startLon.value) {
    error.value = 'Please fill in all required fields'
    return
  }
  const eLat = sameAsStart.value ? startLat.value : endLat.value
  const eLon = sameAsStart.value ? startLon.value : endLon.value
  if (!eLat || !eLon) {
    error.value = 'Please provide end location'
    return
  }

  loading.value = true
  try {
    const trip = await createTrip({
      city: city.value,
      date: date.value,
      start_time: startTime.value,
      end_time: endTime.value,
      transport: transport.value,
      start_lat: parseFloat(startLat.value),
      start_lon: parseFloat(startLon.value),
      end_lat: parseFloat(eLat),
      end_lon: parseFloat(eLon),
    })
    router.push(`/trip/${trip.id}`)
  } catch (e) {
    error.value = `Failed to create trip: ${e.message}`
  } finally {
    loading.value = false
  }
}

onMounted(() => { initMap() })
onUnmounted(() => {
  clearTimeout(debounceTimer)
  if (map) { map.remove(); map = null }
})
</script>

<template>
  <div class="home-layout">
    <div class="form-panel">
      <h1>PathFinder</h1>
      <p class="subtitle">Plan your trip with feasibility-guided exploration</p>

      <form class="trip-form" @submit.prevent="submit">
        <div class="form-group">
          <label for="city">City</label>
          <input id="city" v-model="city" type="text" placeholder="e.g. Budapest" required />
        </div>

        <div class="form-row">
          <div class="form-group">
            <label for="date">Date</label>
            <input id="date" v-model="date" type="date" required />
          </div>
          <div class="form-group">
            <label for="start-time">Start time</label>
            <input id="start-time" v-model="startTime" type="time" />
          </div>
          <div class="form-group">
            <label for="end-time">End time</label>
            <input id="end-time" v-model="endTime" type="time" />
          </div>
        </div>

        <div class="form-group">
          <label for="transport">Transport mode</label>
          <select id="transport" v-model="transport">
            <option value="foot">Walking</option>
            <option value="car">Driving</option>
            <option value="bicycle">Cycling</option>
          </select>
        </div>

        <fieldset>
          <legend>Start location</legend>
          <div class="form-group">
            <input
              v-model="startSearch"
              type="text"
              placeholder="Search address or place..."
              autocomplete="off"
            />
            <ul v-if="startResults.length" class="autocomplete-list">
              <li v-for="(r, i) in startResults" :key="i" @click="selectStartResult(r)">
                {{ r.name }}
              </li>
            </ul>
          </div>
          <p v-if="startAddress" class="selected-address">{{ startAddress }}</p>
          <p v-if="startLat && startLon" class="coords-display">{{ startLat }}, {{ startLon }}</p>
          <a class="geo-link" href="#" @click.prevent="useMyLocation">Use my location</a>
        </fieldset>

        <fieldset>
          <legend>End location</legend>
          <label class="checkbox-label">
            <input type="checkbox" v-model="sameAsStart" />
            Same as start
          </label>
          <template v-if="!sameAsStart">
            <div class="form-group">
              <input
                v-model="endSearch"
                type="text"
                placeholder="Search address or place..."
                autocomplete="off"
              />
              <ul v-if="endResults.length" class="autocomplete-list">
                <li v-for="(r, i) in endResults" :key="i" @click="selectEndResult(r)">
                  {{ r.name }}
                </li>
              </ul>
            </div>
            <p v-if="endAddress" class="selected-address">{{ endAddress }}</p>
            <p v-if="endLat && endLon" class="coords-display">{{ endLat }}, {{ endLon }}</p>
          </template>
        </fieldset>

        <div class="map-mode-toggle">
          <span>Click map to set:</span>
          <button
            type="button"
            :class="['btn', 'btn-small', mapMode === 'start' ? 'btn-primary' : 'btn-secondary']"
            @click="mapMode = 'start'"
          >Set start</button>
          <button
            type="button"
            :class="['btn', 'btn-small', mapMode === 'end' ? 'btn-primary' : 'btn-secondary']"
            @click="mapMode = 'end'"
          >Set end</button>
        </div>

        <p v-if="error" class="error">{{ error }}</p>

        <button type="submit" class="btn btn-primary" :disabled="loading">
          {{ loading ? 'Creating...' : 'Create Trip' }}
        </button>
      </form>
    </div>

    <div class="map-panel">
      <div id="home-map"></div>
    </div>
  </div>
</template>

<style scoped>
.home-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.form-panel {
  flex: 0 0 420px;
  overflow-y: auto;
  padding: 30px 24px;
  display: flex;
  flex-direction: column;
}

.map-panel {
  flex: 1;
  position: relative;
}

#home-map {
  width: 100%;
  height: 100%;
}

h1 {
  text-align: center;
  margin-bottom: 4px;
}

.subtitle {
  text-align: center;
  margin-bottom: 24px;
  color: var(--text);
}

.trip-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  position: relative;
}

.form-row {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

fieldset {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

legend {
  color: var(--text-h);
  font-weight: 500;
  padding: 0 8px;
}

label {
  font-size: 14px;
  color: var(--text);
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

input, select {
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  color: var(--text-h);
  font-size: 15px;
}

input:focus, select:focus {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

.autocomplete-list {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  list-style: none;
  padding: 0;
  margin: 2px 0 0;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  max-height: 200px;
  overflow-y: auto;
  z-index: 1000;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

.autocomplete-list li {
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
  border-bottom: 1px solid var(--border);
  color: var(--text-h);
}

.autocomplete-list li:last-child {
  border-bottom: none;
}

.autocomplete-list li:hover {
  background: var(--accent-bg, #f0f0f0);
}

.selected-address {
  font-size: 13px;
  color: var(--text);
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.coords-display {
  font-size: 12px;
  color: var(--text);
  margin: 0;
  font-family: monospace;
}

.geo-link {
  font-size: 12px;
  color: var(--accent, #3b82f6);
}

.map-mode-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text);
}

.error {
  color: #ef4444;
  font-size: 14px;
}

@media (max-width: 768px) {
  .home-layout {
    flex-direction: column;
  }
  .form-panel {
    flex: none;
    max-height: 55vh;
    overflow-y: auto;
  }
  .map-panel {
    flex: 1;
    min-height: 45vh;
  }
  .form-row {
    flex-direction: column;
  }
}
</style>
