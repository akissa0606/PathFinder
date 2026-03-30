"""Search endpoint — POI discovery via Overpass API."""

import logging
import re

import httpx
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


@router.get("/search")
async def search_pois(
    q: str = Query(..., min_length=1, description="Search query"),
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    radius: int = Query(2000, description="Search radius in meters"),
) -> list[dict]:
    """Search OSM via Overpass for POIs matching query near location."""
    # Sanitize query for Overpass regex (escape special chars)
    safe_q = re.escape(q)

    query = (
        f"[out:json][timeout:10];"
        f"("
        f'node(around:{radius},{lat},{lon})["name"~"{safe_q}",i]["tourism"];'
        f'node(around:{radius},{lat},{lon})["name"~"{safe_q}",i]["amenity"];'
        f'node(around:{radius},{lat},{lon})["name"~"{safe_q}",i]["leisure"];'
        f'node(around:{radius},{lat},{lon})["name"~"{safe_q}",i]["historic"];'
        f'node(around:{radius},{lat},{lon})["name"~"{safe_q}",i]["shop"];'
        f'way(around:{radius},{lat},{lon})["name"~"{safe_q}",i]["tourism"];'
        f'way(around:{radius},{lat},{lon})["name"~"{safe_q}",i]["amenity"];'
        f'way(around:{radius},{lat},{lon})["name"~"{safe_q}",i]["leisure"];'
        f'way(around:{radius},{lat},{lon})["name"~"{safe_q}",i]["historic"];'
        f'way(around:{radius},{lat},{lon})["name"~"{safe_q}",i]["shop"];'
        f");"
        f"out center tags 10;"
    )

    async with httpx.AsyncClient(timeout=15.0) as client:
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                resp = await client.post(endpoint, data={"data": query})
                if resp.status_code != 200:
                    continue
                data = resp.json()
                elements = data.get("elements", [])
                return _format_results(elements)
            except Exception:
                logger.exception("Overpass endpoint %s failed", endpoint)
                continue

    raise HTTPException(status_code=502, detail="All Overpass endpoints failed")


def _format_results(elements: list[dict]) -> list[dict]:
    """Convert Overpass elements to a clean response format."""
    results = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue

        # Get coordinates — nodes have lat/lon directly, ways use center
        el_lat = el.get("lat") or (el.get("center", {}).get("lat"))
        el_lon = el.get("lon") or (el.get("center", {}).get("lon"))
        if el_lat is None or el_lon is None:
            continue

        # Determine category from tags
        category = None
        for key in ("tourism", "amenity", "leisure", "historic", "shop"):
            if key in tags:
                category = f"{key}:{tags[key]}"
                break

        results.append({
            "name": name,
            "lat": el_lat,
            "lon": el_lon,
            "category": category,
            "opening_hours": tags.get("opening_hours"),
        })
    return results
