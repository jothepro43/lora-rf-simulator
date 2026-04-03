"""Coverage heatmap generation service."""

import math
import logging
import numpy as np
from services.terrain import get_terrain_profile
from services.propagation import (
    compute_path_loss,
    haversine_distance,
)

logger = logging.getLogger(__name__)


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
) -> dict:
    """Generate coverage heatmap data.

    Returns a grid of received power levels around the TX point.
    """
    # Calculate grid parameters
    radius_m = radius_km * 1000.0
    # Convert resolution to approximate degrees
    lat_step = resolution_m / 111320.0  # meters per degree latitude
    lon_step = resolution_m / (111320.0 * math.cos(math.radians(tx_lat)))

    # Grid bounds
    lat_min = tx_lat - (radius_m / 111320.0)
    lat_max = tx_lat + (radius_m / 111320.0)
    lon_min = tx_lon - (radius_m / (111320.0 * math.cos(math.radians(tx_lat))))
    lon_max = tx_lon + (radius_m / (111320.0 * math.cos(math.radians(tx_lat))))

    lats = np.arange(lat_min, lat_max, lat_step)
    lons = np.arange(lon_min, lon_max, lon_step)

    # EIRP
    eirp_dbm = tx_power_dbm + tx_gain_dbi - cable_loss_db

    points = []

    for lat in lats:
        for lon in lons:
            dist = haversine_distance(tx_lat, tx_lon, lat, lon)
            if dist < 10 or dist > radius_m:
                continue

            # Get terrain profile
            profile = get_terrain_profile(
                tx_lat, tx_lon, float(lat), float(lon), num_profile_points
            )

            # Compute path loss
            path_loss = compute_path_loss(
                profile["distances"],
                profile["elevations"],
                tx_height_m,
                rx_height_m,
                frequency_mhz,
                k_factor,
                rain_rate_mmh=rain_rate_mmh,
            )

            # Received power
            rx_power_dbm = eirp_dbm - path_loss["total_path_loss_db"] + rx_gain_dbi

            points.append({
                "lat": round(float(lat), 6),
                "lon": round(float(lon), 6),
                "rx_power_dbm": round(rx_power_dbm, 1),
                "path_loss_db": path_loss["total_path_loss_db"],
                "distance_m": round(dist, 0),
            })

    # Determine signal levels for coloring
    for p in points:
        rx = p["rx_power_dbm"]
        if rx >= rx_sensitivity_dbm + 20:
            p["level"] = "excellent"
        elif rx >= rx_sensitivity_dbm + 10:
            p["level"] = "good"
        elif rx >= rx_sensitivity_dbm + 3:
            p["level"] = "marginal"
        elif rx >= rx_sensitivity_dbm:
            p["level"] = "weak"
        else:
            p["level"] = "none"

    return {
        "points": points,
        "bounds": {
            "lat_min": float(lat_min),
            "lat_max": float(lat_max),
            "lon_min": float(lon_min),
            "lon_max": float(lon_max),
        },
        "resolution_m": resolution_m,
        "radius_km": radius_km,
        "eirp_dbm": round(eirp_dbm, 1),
        "tx_lat": tx_lat,
        "tx_lon": tx_lon,
        "total_points": len(points),
    }
