"""Pure-Python SRTM elevation service using HGT files.

Downloads SRTM HGT tiles from OpenTopography and reads them with numpy.
No C dependencies (no GDAL, no rasterio). Works on Windows/Mac/Linux.
"""

import os
import io
import logging
import zipfile
import math
from pathlib import Path

import numpy as np
import httpx

logger = logging.getLogger(__name__)

SRTM_CACHE_DIR = os.getenv("SRTM_CACHE_DIR", "./srtm_cache")
os.makedirs(SRTM_CACHE_DIR, exist_ok=True)

# SRTM tiles can be 1 arc-second (3601x3601) or 3 arc-second (1201x1201)
# The AWS Terrain Tiles serve 1 arc-second; we auto-detect from file size.
HGT_SAMPLES_1AS = 3601
HGT_SAMPLES_3AS = 1201
HGT_BYTES_1AS = HGT_SAMPLES_1AS * HGT_SAMPLES_1AS * 2
HGT_BYTES_3AS = HGT_SAMPLES_3AS * HGT_SAMPLES_3AS * 2
VOID_VALUE = -32768

# Base URL for SRTM tile downloads (OpenTopography SRTM GL3 mirror)
SRTM_BASE_URLS = [
    "https://s3.amazonaws.com/elevation-tiles-prod/skadi/{hemisphere_lat}/{tile_name}.hgt.gz",
    "https://elevation-tiles-prod.s3.amazonaws.com/skadi/{hemisphere_lat}/{tile_name}.hgt.gz",
]

# In-memory caches
_tile_cache: dict[str, np.ndarray] = {}  # tile_name -> elevation array
_elevation_cache: dict[tuple[float, float], float] = {}  # (lat, lon) -> elevation


def _tile_name(lat: float, lon: float) -> str:
    """Get SRTM tile name for a lat/lon coordinate.

    Tile naming convention: N34W084.hgt for the tile covering
    34°N to 35°N, 84°W to 83°W (SW corner).
    """
    lat_floor = math.floor(lat)
    lon_floor = math.floor(lon)
    ns = "N" if lat_floor >= 0 else "S"
    ew = "E" if lon_floor >= 0 else "W"
    return f"{ns}{abs(lat_floor):02d}{ew}{abs(lon_floor):03d}"


def _hgt_path(tile_name: str) -> Path:
    """Get the local file path for an HGT tile."""
    return Path(SRTM_CACHE_DIR) / f"{tile_name}.hgt"


def _download_tile(tile_name: str) -> bool:
    """Download an SRTM HGT tile if not already cached.

    Tries multiple mirror URLs. The tiles are served as gzipped HGT files
    from the AWS/Mapzen elevation tile service.
    """
    hgt_file = _hgt_path(tile_name)
    if hgt_file.exists() and hgt_file.stat().st_size == HGT_BYTES:
        return True

    hemisphere_lat = tile_name[:3]  # e.g., "N34"

    for base_url in SRTM_BASE_URLS:
        url = base_url.format(hemisphere_lat=hemisphere_lat, tile_name=tile_name)
        try:
            logger.info(f"Downloading SRTM tile {tile_name} from {url}")
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()

            # The response is gzip-compressed HGT data
            import gzip
            data = gzip.decompress(resp.content)
            if len(data) in (HGT_BYTES_1AS, HGT_BYTES_3AS):
                hgt_file.write_bytes(data)
                samples = HGT_SAMPLES_1AS if len(data) == HGT_BYTES_1AS else HGT_SAMPLES_3AS
                logger.info(f"Cached SRTM tile {tile_name} ({len(data)} bytes, {samples}x{samples})")
                return True
            else:
                logger.warning(
                    f"Unexpected tile size for {tile_name}: {len(data)} bytes "
                    f"(expected {HGT_BYTES_1AS} or {HGT_BYTES_3AS})"
                )
        except httpx.HTTPStatusError as e:
            logger.debug(f"HTTP {e.response.status_code} for {url}")
            continue
        except Exception as e:
            logger.debug(f"Failed to download {tile_name} from {url}: {e}")
            continue

    # Try downloading as a zip file (some mirrors serve .zip)
    zip_url = f"https://s3.amazonaws.com/elevation-tiles-prod/skadi/{hemisphere_lat}/{tile_name}.hgt.gz"
    logger.warning(f"Could not download SRTM tile {tile_name} from any mirror")
    return False


def _load_tile(tile_name: str) -> np.ndarray | None:
    """Load an HGT tile into memory, downloading if necessary."""
    if tile_name in _tile_cache:
        return _tile_cache[tile_name]

    if not _download_tile(tile_name):
        return None

    hgt_file = _hgt_path(tile_name)
    if not hgt_file.exists():
        return None

    try:
        raw = hgt_file.read_bytes()
        file_size = len(raw)
        if file_size == HGT_BYTES_1AS:
            samples = HGT_SAMPLES_1AS
        elif file_size == HGT_BYTES_3AS:
            samples = HGT_SAMPLES_3AS
        else:
            logger.error(f"Unknown HGT file size {file_size} for {tile_name}")
            return None
        data = np.frombuffer(raw, dtype=">i2").reshape((samples, samples))
        _tile_cache[tile_name] = data
        logger.debug(f"Loaded tile {tile_name} ({samples}x{samples}) into memory")
        return data
    except Exception as e:
        logger.error(f"Failed to read HGT file {hgt_file}: {e}")
        return None


def _read_elevation(tile_data: np.ndarray, lat: float, lon: float) -> float:
    """Read elevation from a loaded HGT tile using bilinear interpolation."""
    lat_floor = math.floor(lat)
    lon_floor = math.floor(lon)

    # Auto-detect resolution from tile shape
    samples = tile_data.shape[0]

    # Position within the tile (0.0 to 1.0)
    lat_frac = lat - lat_floor
    lon_frac = lon - lon_floor

    # Convert to row/col (HGT tiles start from the NW corner)
    # Row 0 = north edge, last row = south edge
    row_f = (1.0 - lat_frac) * (samples - 1)
    col_f = lon_frac * (samples - 1)

    row = int(row_f)
    col = int(col_f)

    # Clamp to valid range
    row = max(0, min(row, samples - 2))
    col = max(0, min(col, samples - 2))

    # Bilinear interpolation for smoother results
    dr = row_f - row
    dc = col_f - col

    v00 = int(tile_data[row, col])
    v01 = int(tile_data[row, col + 1])
    v10 = int(tile_data[row + 1, col])
    v11 = int(tile_data[row + 1, col + 1])

    # Handle void values
    values = [v00, v01, v10, v11]
    valid = [v for v in values if v != VOID_VALUE]
    if not valid:
        return 0.0
    if len(valid) < 4:
        return float(sum(valid) / len(valid))

    # Bilinear interpolation
    elev = (
        v00 * (1 - dr) * (1 - dc)
        + v01 * (1 - dr) * dc
        + v10 * dr * (1 - dc)
        + v11 * dr * dc
    )
    return float(elev)


def get_elevation(lat: float, lon: float) -> float:
    """Get elevation in meters for a lat/lon point using SRTM HGT data."""
    key = (round(lat, 5), round(lon, 5))
    if key in _elevation_cache:
        return _elevation_cache[key]

    try:
        name = _tile_name(lat, lon)
        tile_data = _load_tile(name)
        if tile_data is None:
            logger.warning(f"No SRTM tile available for ({lat}, {lon})")
            return 0.0

        elev = _read_elevation(tile_data, lat, lon)
        _elevation_cache[key] = elev
        return elev
    except Exception as e:
        logger.warning(f"SRTM lookup failed for ({lat}, {lon}): {e}")
        return 0.0


def get_elevation_batch(points: list[tuple[float, float]]) -> list[float]:
    """Get elevations for multiple points.

    Optimized to load each tile only once for bulk queries.
    """
    # Group points by tile for efficient loading
    tile_groups: dict[str, list[tuple[int, float, float]]] = {}
    for i, (lat, lon) in enumerate(points):
        name = _tile_name(lat, lon)
        if name not in tile_groups:
            tile_groups[name] = []
        tile_groups[name].append((i, lat, lon))

    results = [0.0] * len(points)
    for name, group in tile_groups.items():
        tile_data = _load_tile(name)
        if tile_data is None:
            continue
        for i, lat, lon in group:
            key = (round(lat, 5), round(lon, 5))
            if key in _elevation_cache:
                results[i] = _elevation_cache[key]
            else:
                elev = _read_elevation(tile_data, lat, lon)
                _elevation_cache[key] = elev
                results[i] = elev

    return results


def get_terrain_profile(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
    num_points: int = 100,
) -> dict:
    """Extract terrain profile between two points.

    Returns dict with:
      - distances: list of distances from start (meters)
      - elevations: list of ground elevations (meters ASL)
      - lats/lons: coordinates of each sample point
      - total_distance_m: total distance between endpoints
    """
    from services.propagation import haversine_distance

    lats = np.linspace(lat1, lat2, num_points)
    lons = np.linspace(lon1, lon2, num_points)

    points = list(zip(lats.tolist(), lons.tolist()))
    elevations = get_elevation_batch(points)

    total_distance = haversine_distance(lat1, lon1, lat2, lon2)
    distances = np.linspace(0, total_distance, num_points).tolist()

    return {
        "distances": distances,
        "elevations": elevations,
        "lats": lats.tolist(),
        "lons": lons.tolist(),
        "total_distance_m": total_distance,
    }
