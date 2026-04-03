"""Terrain query API endpoints."""

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/terrain", tags=["terrain"])


class ProfileRequest(BaseModel):
    lat1: float
    lon1: float
    lat2: float
    lon2: float
    num_points: int = 100


@router.get("/elevation")
def get_elevation(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    from services.terrain import get_elevation
    elev = get_elevation(lat, lon)
    return {"lat": lat, "lon": lon, "elevation_m": elev}


@router.post("/profile")
def get_profile(req: ProfileRequest):
    from services.terrain import get_terrain_profile
    return get_terrain_profile(req.lat1, req.lon1, req.lat2, req.lon2, req.num_points)


@router.get("/tile-status")
def tile_status():
    import os
    cache_dir = os.getenv("SRTM_CACHE_DIR", "./srtm_cache")
    if not os.path.exists(cache_dir):
        return {"cached_tiles": 0, "cache_dir": cache_dir, "tiles": []}
    tiles = [f for f in os.listdir(cache_dir) if f.endswith((".tif", ".hgt"))]
    return {
        "cached_tiles": len(tiles),
        "cache_dir": cache_dir,
        "tiles": tiles,
    }
