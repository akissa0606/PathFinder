export async function createTrip(data) {
  const res = await fetch('/api/trips', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return res.json()
}

export async function getTrip(id) {
  const res = await fetch(`/api/trips/${id}`)
  return res.json()
}

export async function searchPlaces(query, lat, lon) {
  const res = await fetch(
    `/api/search?q=${encodeURIComponent(query)}&lat=${lat}&lon=${lon}`
  )
  return res.json()
}

export async function addPlace(tripId, place) {
  const res = await fetch(`/api/trips/${tripId}/places`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(place),
  })
  return res.json()
}

export async function deletePlace(tripId, placeId) {
  await fetch(`/api/trips/${tripId}/places/${placeId}`, { method: 'DELETE' })
}

export async function updatePlace(tripId, placeId, data) {
  const res = await fetch(`/api/trips/${tripId}/places/${placeId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return res.json()
}

export async function geocode(query) {
  const res = await fetch(`/api/geocode?q=${encodeURIComponent(query)}`)
  return res.json()
}

export async function getFeasibility(tripId, lat, lon) {
  const params = new URLSearchParams()
  if (lat != null && lon != null) {
    params.set('lat', lat)
    params.set('lon', lon)
  }
  const res = await fetch(`/api/trips/${tripId}/feasibility?${params}`)
  return res.json()
}
