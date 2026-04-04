"""Coverage heatmap generation service with PNG image output."""

import math
import time
import logging
import io
import base64
import concurrent.futures
import numpy as np
from PIL import Image
from services.terrain import get_terrain_profile
from services.propagation import (
    compute_path_loss,
    haversine_distance,
    bearing_from_coords,
    elevation_angle,
    directional_gain_reduction,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Colormap LUT generation
# ---------------------------------------------------------------------------

def _interpolate_colormap(anchors, n=256):
    """Interpolate RGBA anchors into an n-entry LUT (uint8)."""
    positions = [a[0] for a in anchors]
    colors = np.array([a[1] for a in anchors], dtype=np.float64)
    lut = np.zeros((n, 4), dtype=np.uint8)
    for i in range(n):
        t = i / (n - 1)
        # Find surrounding anchors
        for j in range(len(positions) - 1):
            if positions[j] <= t <= positions[j + 1]:
                seg_t = (t - positions[j]) / (positions[j + 1] - positions[j])
                rgba = colors[j] * (1 - seg_t) + colors[j + 1] * seg_t
                lut[i] = np.clip(rgba, 0, 255).astype(np.uint8)
                break
    return lut


# Precomputed LUTs for supported colormaps
COLORMAP_LUTS = {
    "plasma": _interpolate_colormap([
        (0.0,  (13,  8,   135, 255)),
        (0.25, (126, 3,   168, 255)),
        (0.5,  (204, 71,  120, 255)),
        (0.75, (248, 149, 64,  255)),
        (1.0,  (240, 249, 33,  255)),
    ]),
    "viridis": _interpolate_colormap([
        (0.0,  (68,  1,   84,  255)),
        (0.25, (59,  82,  139, 255)),
        (0.5,  (33,  145, 140, 255)),
        (0.75, (94,  201, 98,  255)),
        (1.0,  (253, 231, 37,  255)),
    ]),
    "inferno": _interpolate_colormap([
        (0.0,  (0,   0,   4,   255)),
        (0.25, (87,  16,  110, 255)),
        (0.5,  (188, 55,  84,  255)),
        (0.75, (249, 142, 9,   255)),
        (1.0,  (252, 255, 164, 255)),
    ]),
    "turbo": _interpolate_colormap([
        (0.0,  (48,  18,  59,  255)),
        (0.25, (30,  150, 242, 255)),
        (0.5,  (115, 224, 76,  255)),
        (0.75, (249, 168, 37,  255)),
        (1.0,  (122, 4,   3,   255)),
    ]),
}


def get_colormap_lut(name: str) -> np.ndarray:
    """Return a (256, 4) uint8 RGBA LUT for the named colormap."""
    return COLORMAP_LUTS.get(name, COLORMAP_LUTS["plasma"])


def power_to_image(grid, min_dbm=-130, max_dbm=-80, colormap="plasma", sensitivity=-130):
    """Convert 2D power grid (rows x cols) to a base64-encoded RGBA PNG."""
    rows, cols = grid.shape

    # Normalize power values to 0..1
    norm = (grid - min_dbm) / (max_dbm - min_dbm)
    norm = np.clip(norm, 0, 1)

    # Map to colormap indices
    indices = (norm * 255).astype(np.uint8)
    lut = get_colormap_lut(colormap)
    rgba = lut[indices]  # shape (rows, cols, 4)

    # Transparent where below sensitivity
    no_signal = grid < sensitivity
    rgba[no_signal, 3] = 0

    img = Image.fromarray(rgba, "RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# Coverage generation
# ---------------------------------------------------------------------------

def _compute_row(
    row_idx, lat, lons, tx_lat, tx_lon, tx_height_m, rx_height_m,
    frequency_mhz, k_factor, rain_rate_mmh, eirp_dbm, rx_gain_dbi,
    radius_m, num_profile_points,
    antenna_azimuth_deg=0.0, antenna_tilt_deg=0.0,
    antenna_h_beamwidth=360.0, antenna_v_beamwidth=90.0,
    antenna_front_to_back_db=0.0,
):
    """Compute received power for every longitude in a single latitude row."""
    row_values = np.full(len(lons), -999.0)
    is_directional = antenna_h_beamwidth < 360
    for col_idx, lon in enumerate(lons):
        dist = haversine_distance(tx_lat, tx_lon, lat, float(lon))
        if dist < 10 or dist > radius_m:
            continue
        profile = get_terrain_profile(
            tx_lat, tx_lon, lat, float(lon), num_profile_points
        )
        path_loss = compute_path_loss(
            profile["distances"],
            profile["elevations"],
            tx_height_m,
            rx_height_m,
            frequency_mhz,
            k_factor,
            rain_rate_mmh=rain_rate_mmh,
        )
        rx_power_dbm = eirp_dbm - path_loss["total_path_loss_db"] + rx_gain_dbi

        # Apply directional antenna gain reduction
        if is_directional:
            az_to_point = bearing_from_coords(tx_lat, tx_lon, lat, float(lon))
            tilt_to_point = elevation_angle(
                dist,
                profile["elevations"][0] + tx_height_m,
                profile["elevations"][-1] + rx_height_m,
            )
            reduction = directional_gain_reduction(
                az_to_point, antenna_azimuth_deg, antenna_tilt_deg,
                tilt_to_point, antenna_h_beamwidth, antenna_v_beamwidth,
                antenna_front_to_back_db,
            )
            rx_power_dbm -= reduction

        row_values[col_idx] = rx_power_dbm
    return row_idx, row_values


def generate_coverage(
    tx_lat: float,
    tx_lon: float,
    tx_height_m: float,
    tx_power_dbm: float,
    tx_gain_dbi: float,
    cable_loss_db: float,
    rx_gain_dbi: float,
    rx_sensitivity_dbm: float,
    frequency_mhz: float = 915.0,
    radius_km: float = 10.0,
    resolution_m: float = 90.0,
    rx_height_m: float = 1.5,
    k_factor: float = 4.0 / 3.0,
    rain_rate_mmh: float = 0.0,
    num_profile_points: int = 50,
    min_dbm: float = -130.0,
    max_dbm: float = -80.0,
    colormap: str = "plasma",
    antenna_azimuth_deg: float = 0.0,
    antenna_tilt_deg: float = 0.0,
    antenna_h_beamwidth: float = 360.0,
    antenna_v_beamwidth: float = 90.0,
    antenna_front_to_back_db: float = 0.0,
) -> dict:
    """Generate coverage as a PNG image overlay.

    Returns base64-encoded PNG, Leaflet-style bounds, and summary stats.
    """
    radius_m = radius_km * 1000.0
    lat_step = resolution_m / 111320.0
    lon_step = resolution_m / (111320.0 * math.cos(math.radians(tx_lat)))

    lat_min = tx_lat - (radius_m / 111320.0)
    lat_max = tx_lat + (radius_m / 111320.0)
    lon_min = tx_lon - (radius_m / (111320.0 * math.cos(math.radians(tx_lat))))
    lon_max = tx_lon + (radius_m / (111320.0 * math.cos(math.radians(tx_lat))))

    # Build coordinate arrays (south→north for image rows flipped later)
    lats = np.arange(lat_min, lat_max, lat_step)
    lons = np.arange(lon_min, lon_max, lon_step)

    eirp_dbm = tx_power_dbm + tx_gain_dbi - cable_loss_db

    num_rows = len(lats)
    num_cols = len(lons)
    grid = np.full((num_rows, num_cols), -999.0)

    t0 = time.time()
    logger.info(
        "Coverage: %d rows x %d cols = %d cells, radius=%.1f km, res=%.0f m",
        num_rows, num_cols, num_rows * num_cols, radius_km, resolution_m,
    )

    # Multi-threaded row computation
    max_workers = min(8, num_rows)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = []
        for row_idx, lat in enumerate(lats):
            futures.append(
                pool.submit(
                    _compute_row,
                    row_idx, float(lat), lons,
                    tx_lat, tx_lon, tx_height_m, rx_height_m,
                    frequency_mhz, k_factor, rain_rate_mmh,
                    eirp_dbm, rx_gain_dbi, radius_m, num_profile_points,
                    antenna_azimuth_deg, antenna_tilt_deg,
                    antenna_h_beamwidth, antenna_v_beamwidth,
                    antenna_front_to_back_db,
                )
            )

        done = 0
        for future in concurrent.futures.as_completed(futures):
            row_idx, row_values = future.result()
            grid[row_idx] = row_values
            done += 1
            if done % max(1, num_rows // 10) == 0:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                remaining = (num_rows - done) / rate if rate > 0 else 0
                logger.info(
                    "  Progress: %d/%d rows (%.0f%%) – %.1fs elapsed, ~%.1fs remaining",
                    done, num_rows, 100 * done / num_rows, elapsed, remaining,
                )

    elapsed = time.time() - t0
    logger.info("Coverage complete in %.1fs", elapsed)

    # Flip grid so row 0 = north (image top = lat_max)
    grid_flipped = grid[::-1]

    # Convert to PNG
    image_base64 = power_to_image(
        grid_flipped,
        min_dbm=min_dbm,
        max_dbm=max_dbm,
        colormap=colormap,
        sensitivity=rx_sensitivity_dbm,
    )

    # Stats
    valid = grid[grid > -999]
    stats = {}
    if len(valid) > 0:
        stats = {
            "min_power_dbm": round(float(np.min(valid)), 1),
            "max_power_dbm": round(float(np.max(valid)), 1),
            "mean_power_dbm": round(float(np.mean(valid)), 1),
            "cells_computed": int(len(valid)),
            "cells_total": int(num_rows * num_cols),
            "elapsed_seconds": round(elapsed, 1),
        }

    return {
        "image_base64": image_base64,
        "bounds": [[float(lat_min), float(lon_min)], [float(lat_max), float(lon_max)]],
        "stats": stats,
        "resolution_m": resolution_m,
        "radius_km": radius_km,
        "eirp_dbm": round(eirp_dbm, 1),
        "tx_lat": tx_lat,
        "tx_lon": tx_lon,
        "min_dbm": min_dbm,
        "max_dbm": max_dbm,
        "colormap": colormap,
    }
