import os
import logging
import numpy as np

logger = logging.getLogger(__name__)

SRTM_CACHE_DIR = os.getenv("SRTM_CACHE_DIR", "./srtm_cache")
os.makedirs(SRTM_CACHE_DIR, exist_ok=True)

# In-memory cache for elevation lookups
_elevation_cache: dict[tuple[float, float], float] = {}


def get_elevation(lat: float, lon: float) -> float:
    """Get elevation in meters for a lat/lon point using srtm4."""
    key = (round(lat, 5), round(lon, 5))
    if key in _elevation_cache:
        return _elevation_cache[key]

    try:
        from srtm4 import srtm4
        elev = srtm4(lat, lon)
        if elev is None or np.isnan(elev):
            elev = 0.0
        _elevation_cache[key] = float(elev)
        return float(elev)
    except Exception as e:
        logger.warning(f"SRTM lookup failed for ({lat}, {lon}): {e}")
        return 0.0


def get_elevation_batch(points: list[tuple[float, float]]) -> list[float]:
    """Get elevations for multiple points."""
    return [get_elevation(lat, lon) for lat, lon in points]


def get_terrain_profile(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
    num_points: int = 100
) -> dict:
    """Extract terrain profile between two points.

    Returns dict with:
      - distances: list of distances from start (meters)
      - elevations: list of ground elevations (meters ASL)
      - lats/lons: coordinates of each sample point
    """
    from services.propagation import haversine_distance

    lats = np.linspace(lat1, lat2, num_points)
    lons = np.linspace(lon1, lon2, num_points)

    elevations = []
    for lat, lon in zip(lats, lons):
        elevations.append(get_elevation(float(lat), float(lon)))

    total_distance = haversine_distance(lat1, lon1, lat2, lon2)
    distances = np.linspace(0, total_distance, num_points).tolist()

    return {
        "distances": distances,
        "elevations": elevations,
        "lats": lats.tolist(),
        "lons": lons.tolist(),
        "total_distance_m": total_distance,
    }
