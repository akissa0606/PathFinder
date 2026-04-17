import { animate, createMotionPath } from "animejs";

export function decodePolyline(encoded) {
  const points = [];
  let index = 0,
    lat = 0,
    lng = 0;
  while (index < encoded.length) {
    let b,
      shift = 0,
      result = 0;
    do {
      b = encoded.charCodeAt(index++) - 63;
      result |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    lat += result & 1 ? ~(result >> 1) : result >> 1;
    shift = 0;
    result = 0;
    do {
      b = encoded.charCodeAt(index++) - 63;
      result |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    lng += result & 1 ? ~(result >> 1) : result >> 1;
    points.push([lat / 1e5, lng / 1e5]);
  }
  return points;
}

export function animateDotAlongPolyline(
  polyline,
  durationMs,
  color = "#6366f1",
  onComplete,
) {
  const path = polyline._path;
  if (!path || !path.parentNode) return;

  const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  dot.setAttribute("cx", "0");
  dot.setAttribute("cy", "0");
  dot.setAttribute("r", "7");
  dot.setAttribute("fill", color);
  dot.setAttribute("stroke", "white");
  dot.setAttribute("stroke-width", "2");
  path.parentNode.appendChild(dot);

  animate(dot, {
    ...createMotionPath(path),
    duration: durationMs,
    ease: "inOutSine",
    onComplete() {
      dot.remove();
      onComplete?.();
    },
  });
}
