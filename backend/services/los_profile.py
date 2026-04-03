"""Line-of-sight profile analysis between two points."""

import math
from services.terrain import get_terrain_profile
from services.propagation import (
    earth_curvature,
    fresnel_radius,
    haversine_distance,
    DEFAULT_K_FACTOR,
)


def compute_los_profile(
    lat1: float,
    lon1: float,
    tx_height_m: float,
    lat2: float,
    lon2: float,
    rx_height_m: float,
    frequency_mhz: float = 915.0,
    num_points: int = 200,
    k_factor: float = DEFAULT_K_FACTOR,
) -> dict:
    """Compute full LoS profile between TX and RX.

    Returns terrain profile with LoS line, Fresnel zones, and obstruction data.
    """
    profile = get_terrain_profile(lat1, lon1, lat2, lon2, num_points)
    distances = profile["distances"]
    elevations = profile["elevations"]
    total_dist = profile["total_distance_m"]

    if total_dist <= 0:
        return {
            **profile,
            "los_heights": elevations,
            "fresnel_60pct": [],
            "fresnel_top": [],
            "fresnel_bottom": [],
            "earth_curvature": [],
            "obstructions": [],
            "clearance_pct": 100.0,
            "is_los": True,
            "tx_height_asl": elevations[0] + tx_height_m,
            "rx_height_asl": elevations[-1] + rx_height_m,
        }

    tx_asl = elevations[0] + tx_height_m
    rx_asl = elevations[-1] + rx_height_m

    los_heights = []
    fresnel_60pct_top = []
    fresnel_60pct_bottom = []
    earth_curve = []
    obstructions = []
    min_clearance_ratio = float("inf")

    for i, d in enumerate(distances):
        # LoS line height
        if total_dist > 0:
            los_h = tx_asl + (rx_asl - tx_asl) * d / total_dist
        else:
            los_h = tx_asl
        los_heights.append(round(los_h, 2))

        # Earth curvature at this point
        ec = earth_curvature(total_dist, d, k_factor)
        earth_curve.append(round(ec, 2))

        # Effective terrain height with earth curvature
        effective_terrain = elevations[i] + ec

        # Fresnel zone radius (60% of first Fresnel zone)
        if i > 0 and i < len(distances) - 1:
            f1_radius = fresnel_radius(1, total_dist, d, frequency_mhz)
            f60 = 0.6 * f1_radius
        else:
            f1_radius = 0.0
            f60 = 0.0

        fresnel_60pct_top.append(round(los_h + f60, 2))
        fresnel_60pct_bottom.append(round(los_h - f60, 2))

        # Check clearance
        if i > 0 and i < len(distances) - 1 and f1_radius > 0:
            clearance = los_h - effective_terrain
            clearance_ratio = clearance / f1_radius if f1_radius > 0 else float("inf")

            if clearance_ratio < min_clearance_ratio:
                min_clearance_ratio = clearance_ratio

            if clearance < 0:
                obstructions.append({
                    "index": i,
                    "distance_m": round(d, 1),
                    "elevation_m": round(elevations[i], 1),
                    "effective_elevation_m": round(effective_terrain, 1),
                    "los_height_m": round(los_h, 1),
                    "obstruction_m": round(-clearance, 1),
                    "lat": profile["lats"][i],
                    "lon": profile["lons"][i],
                })

    is_los = len(obstructions) == 0
    clearance_pct = max(0, min(100, min_clearance_ratio * 100)) if min_clearance_ratio != float("inf") else 100.0

    return {
        **profile,
        "los_heights": los_heights,
        "fresnel_60pct_top": fresnel_60pct_top,
        "fresnel_60pct_bottom": fresnel_60pct_bottom,
        "earth_curvature": earth_curve,
        "obstructions": obstructions,
        "clearance_pct": round(clearance_pct, 1),
        "is_los": is_los,
        "tx_height_asl": round(tx_asl, 2),
        "rx_height_asl": round(rx_asl, 2),
        "tx_height_agl": tx_height_m,
        "rx_height_agl": rx_height_m,
        "frequency_mhz": frequency_mhz,
        "k_factor": k_factor,
    }
