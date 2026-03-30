<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { createTrip } from '../api.js'

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

function useMyLocation() {
  if (!navigator.geolocation) {
    error.value = 'Geolocation not supported'
    return
  }
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      startLat.value = pos.coords.latitude.toFixed(6)
      startLon.value = pos.coords.longitude.toFixed(6)
      if (sameAsStart.value) {
        endLat.value = startLat.value
        endLon.value = startLon.value
      }
    },
    (err) => {
      error.value = `Location error: ${err.message}`
    }
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
</script>

<template>
  <div class="home">
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
        <div class="form-row">
          <div class="form-group">
            <label for="start-lat">Latitude</label>
            <input id="start-lat" v-model="startLat" type="number" step="any" placeholder="47.4979" required />
          </div>
          <div class="form-group">
            <label for="start-lon">Longitude</label>
            <input id="start-lon" v-model="startLon" type="number" step="any" placeholder="19.0402" required />
          </div>
          <button type="button" class="btn btn-secondary" @click="useMyLocation">Use my location</button>
        </div>
      </fieldset>

      <fieldset>
        <legend>End location</legend>
        <label class="checkbox-label">
          <input type="checkbox" v-model="sameAsStart" />
          Same as start
        </label>
        <div v-if="!sameAsStart" class="form-row">
          <div class="form-group">
            <label for="end-lat">Latitude</label>
            <input id="end-lat" v-model="endLat" type="number" step="any" placeholder="47.4979" />
          </div>
          <div class="form-group">
            <label for="end-lon">Longitude</label>
            <input id="end-lon" v-model="endLon" type="number" step="any" placeholder="19.0402" />
          </div>
        </div>
      </fieldset>

      <p v-if="error" class="error">{{ error }}</p>

      <button type="submit" class="btn btn-primary" :disabled="loading">
        {{ loading ? 'Creating...' : 'Create Trip' }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.home {
  max-width: 600px;
  margin: 0 auto;
  padding: 40px 20px;
}

h1 {
  text-align: center;
  margin-bottom: 4px;
}

.subtitle {
  text-align: center;
  margin-bottom: 32px;
  color: var(--text);
}

.trip-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.form-row {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

fieldset {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
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
  font-size: 16px;
}

input:focus, select:focus {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

.error {
  color: #ef4444;
  font-size: 14px;
}

@media (max-width: 600px) {
  .form-row {
    flex-direction: column;
  }
}
</style>
