function setStatus(message) {
  const el = document.getElementById("status");
  if (!el) return;
  el.textContent = message;
}


function parsePlaces(raw) {
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

document.addEventListener("DOMContentLoaded", () => {
  const mapEl = document.getElementById("map");
  if (!mapEl) return;

  // London
  const londonLatLng = [51.5074, -0.1278];
  const map = L.map("map").setView(londonLatLng, 12);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  }).addTo(map);

  L.marker(londonLatLng).addTo(map).bindPopup("London").openPopup();

  const form = document.getElementById("places-form");
  const input = document.getElementById("places-input");

  if (form && input) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const places = parsePlaces(input.value);
      if (places.length === 0) {
        setStatus("Please enter at least one place.");
        return;
      }
      setStatus(`You entered ${places.length} place(s). Check the console.`);
      console.log("Places:", places);
    });
  }
});

