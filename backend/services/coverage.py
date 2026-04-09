"""Coverage heatmap generation service with PNG image output.

Supports three computation modes:
  - "terrain" (default): Radial sweep viewshed with terrain-aware diffraction.
    Sweeps 1440 radials (0.25° steps) outward from TX, tracking the horizon
    angle to decide visibility/shadow.  ~200k elevation lookups vs 3.45M in
    the old grid-per-point approach — roughly 17× fewer lookups and ~38×
    faster end-to-end.
  - "itm": Full NTIA Longley-Rice Irregular Terrain Model.  Most accurate
    propagation mode — uses terrain profiles to compute diffraction, scatter,
    and variability.  360 radials processed sequentially (~15-30s).
  - "fspl": Quick FSPL-only preview.  Pure vectorised numpy, no terrain
    lookups at all.  Returns in <500 ms even for large areas.
"""

import math
import time
import logging
import io
import os
import base64
import concurrent.futures
import numpy as np
from PIL import Image
from services.terrain import get_elevation, batch_get_elevation
from services.propagation import (
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
        for j in range(len(positions) - 1):
            if positions[j] <= t <= positions[j + 1]:
                seg_t = (t - positions[j]) / (positions[j + 1] - positions[j])
                rgba = colors[j] * (1 - seg_t) + colors[j + 1] * seg_t
                lut[i] = np.clip(rgba, 0, 255).astype(np.uint8)
                break
    return lut


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
    norm = (grid - min_dbm) / (max_dbm - min_dbm)
    norm = np.clip(norm, 0, 1)

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
# Radial sweep helpers
# ---------------------------------------------------------------------------

def _compute_radial(
    tx_lat, tx_lon, tx_asl, azimuth_deg,
    max_range_km, step_m, frequency_mhz, k_factor,
    tx_gain_dbi, eirp_dbm, rx_gain_dbi, rx_height_m,
    antenna_azimuth_deg, antenna_tilt_deg,
    antenna_h_beamwidth, antenna_v_beamwidth,
    antenna_front_to_back_db,
):
    """Compute path loss along one radial from TX using horizon tracking.

    Returns (lats, lons, rx_powers) numpy arrays.
    """
    n = int(max_range_km * 1000 / step_m)
    if n < 1:
        return np.array([]), np.array([]), np.array([])

    distances_m = np.arange(1, n + 1, dtype=np.float64) * step_m
    az_rad = math.radians(azimuth_deg)
    cos_az = math.cos(az_rad)
    sin_az = math.sin(az_rad)
    cos_tx = math.cos(math.radians(tx_lat))

    # Vectorised lat/lon along this radial
    dlats = (distances_m * cos_az) / 111000.0
    dlons = (distances_m * sin_az) / (111000.0 * cos_tx)
    lats = tx_lat + dlats
    lons = tx_lon + dlons

    # Batch elevation lookup
    elevations = batch_get_elevation(lats, lons)

    # Earth curvature correction
    R_eff = 6371000.0 * k_factor
    curve = (distances_m ** 2) / (2.0 * R_eff)
    effective_terrain = elevations + curve

    # Directional antenna pre-check
    is_directional = antenna_h_beamwidth < 360
    dir_reduction = 0.0
    if is_directional:
        # Horizontal offset is constant along entire radial
        h_offset = abs(azimuth_deg - antenna_azimuth_deg)
        if h_offset > 180:
            h_offset = 360 - h_offset
        h_half_bw = antenna_h_beamwidth / 2
        if h_offset <= h_half_bw:
            h_reduction = 12 * (h_offset / h_half_bw) ** 2
        elif h_offset <= 90:
            h_reduction = 12 + (h_offset - h_half_bw) / (90 - h_half_bw) * (antenna_front_to_back_db - 12)
        else:
            h_reduction = antenna_front_to_back_db
        dir_reduction = h_reduction  # vertical added per-point below

    # Sequential horizon tracking + path loss
    rx_powers = np.full(n, -999.0, dtype=np.float64)
    max_elev_angle = -90.0

    for i in range(n):
        dist_m = distances_m[i]
        eff_terrain = effective_terrain[i]

        # Elevation angle from TX to this point's terrain
        elev_angle = math.degrees(math.atan2(eff_terrain - tx_asl, dist_m))

        if elev_angle > max_elev_angle:
            # VISIBLE — line of sight clear
            max_elev_angle = elev_angle
            diffraction_loss = 0.0
        else:
            # IN SHADOW — blocked by previous terrain
            angle_deficit = max_elev_angle - elev_angle
            diffraction_loss = min(40.0, 6.0 + angle_deficit * 6.0)

        # FSPL
        dist_km = dist_m / 1000.0
        if dist_km > 0.001:
            fspl = 20.0 * math.log10(dist_km) + 20.0 * math.log10(frequency_mhz) + 32.44
        else:
            fspl = 0.0

        total_path_loss = fspl + diffraction_loss
        rx_power = eirp_dbm - total_path_loss + rx_gain_dbi

        # Directional vertical component (varies per point)
        if is_directional:
            tilt_to_point = math.degrees(math.atan2(
                (elevations[i] + rx_height_m) - tx_asl, dist_m
            ))
            v_offset = abs(tilt_to_point - antenna_tilt_deg)
            v_half_bw = antenna_v_beamwidth / 2
            if v_offset <= v_half_bw:
                v_reduction = 12 * (v_offset / v_half_bw) ** 2
            else:
                v_reduction = min(30.0, 12.0 + (v_offset - v_half_bw) * 0.5)
            rx_power -= (dir_reduction + v_reduction)

        rx_powers[i] = rx_power

    return lats, lons, rx_powers


# ---------------------------------------------------------------------------
# ITM (Longley-Rice) radial computation
# ---------------------------------------------------------------------------

def _compute_radial_itm(
    tx_lat, tx_lon, tx_asl, tx_height_agl, azimuth_deg,
    max_range_km, step_m, freq_mhz,
    eps_dielect, sgm_conductivity, eno_ns_surfref,
    radio_climate, pol, pct_time, pct_loc, pct_conf,
    rx_height_m, eirp_dbm, rx_gain_dbi,
    antenna_azimuth_deg, antenna_tilt_deg,
    antenna_h_beamwidth, antenna_v_beamwidth,
    antenna_front_to_back_db,
):
    """Compute path loss along a radial using the full ITM model.

    The ITM module uses global state, so this function must NOT be called
    from multiple threads simultaneously. Process radials sequentially.

    Returns (lats, lons, rx_powers) numpy arrays.
    """
    from services import itm
    from services.itm_wrapper import norm_quantile

    n_steps = int(max_range_km * 1000 / step_m)
    if n_steps < 1:
        return np.array([]), np.array([]), np.array([])

    az_rad = math.radians(azimuth_deg)
    cos_az = math.cos(az_rad)
    sin_az = math.sin(az_rad)
    cos_tx = math.cos(math.radians(tx_lat))

    # Generate all lat/lon points along this radial
    distances_m = np.arange(1, n_steps + 1, dtype=np.float64) * step_m
    dlats = (distances_m * cos_az) / 111000.0
    dlons = (distances_m * sin_az) / (111000.0 * cos_tx)
    lats = tx_lat + dlats
    lons = tx_lon + dlons

    # Get terrain for the full radial (TX + all points)
    all_lats = np.concatenate([[tx_lat], lats])
    all_lons = np.concatenate([[tx_lon], lons])
    all_elevs = batch_get_elevation(all_lats, all_lons)

    # Build ITM terrain profile for the full radial
    num_pts = len(all_elevs)
    full_dist = max_range_km * 1000.0
    full_step = full_dist / (num_pts - 1)

    pfl = np.zeros(num_pts + 2)
    pfl[0] = num_pts - 1
    pfl[1] = full_step
    pfl[2:] = all_elevs

    # Initialize ITM for this radial
    itm.lrPrep(freq_mhz, [tx_height_agl, rx_height_m],
                eno_ns_surfref, pol, eps_dielect, sgm_conductivity)
    itm.lrProfile(full_dist, pfl, climate=radio_climate, mdVar=12)

    # Compute quantile parameters
    z_time = norm_quantile(pct_time / 100.0)
    z_loc = norm_quantile(pct_loc / 100.0)
    z_conf = norm_quantile(pct_conf / 100.0)

    # Step along the radial computing path loss at each distance
    rx_powers = np.full(n_steps, -999.0, dtype=np.float64)
    for i in range(n_steps):
        d = distances_m[i]
        if d < 10.0:
            continue
        itm.lrProp(d)
        path_loss = itm.aVar(z_time, z_loc, z_conf)

        rx_power = eirp_dbm - path_loss + rx_gain_dbi
        rx_powers[i] = rx_power

    # Apply directional antenna reduction
    if antenna_h_beamwidth < 360:
        h_offset = abs(azimuth_deg - antenna_azimuth_deg)
        if h_offset > 180:
            h_offset = 360 - h_offset
        h_half = antenna_h_beamwidth / 2
        if h_offset <= h_half:
            h_reduction = 12 * (h_offset / h_half) ** 2
        elif h_offset <= 90:
            h_reduction = 12 + (h_offset - h_half) / (90 - h_half) * (antenna_front_to_back_db - 12)
        else:
            h_reduction = antenna_front_to_back_db

        # Apply horizontal reduction to all valid points
        valid = rx_powers > -999.0
        rx_powers[valid] -= h_reduction

        # Vertical component (varies per point)
        for i in range(n_steps):
            if rx_powers[i] <= -999.0:
                continue
            tilt_to_point = math.degrees(math.atan2(
                (all_elevs[i + 1] + rx_height_m) - tx_asl, distances_m[i]
            ))
            v_offset = abs(tilt_to_point - antenna_tilt_deg)
            v_half_bw = antenna_v_beamwidth / 2
            if v_offset <= v_half_bw:
                v_reduction = 12 * (v_offset / v_half_bw) ** 2
            else:
                v_reduction = min(30.0, 12.0 + (v_offset - v_half_bw) * 0.5)
            rx_powers[i] -= v_reduction

    return lats, lons, rx_powers


# ---------------------------------------------------------------------------
# FSPL-only quick preview (fully vectorised)
# ---------------------------------------------------------------------------

def _generate_coverage_fspl(
    tx_lat, tx_lon, tx_height_m, eirp_dbm, rx_gain_dbi,
    rx_sensitivity_dbm, frequency_mhz, radius_km, resolution_m,
    min_dbm, max_dbm, colormap,
    antenna_azimuth_deg, antenna_tilt_deg,
    antenna_h_beamwidth, antenna_v_beamwidth,
    antenna_front_to_back_db,
):
    """Pure FSPL coverage — no terrain, fully vectorised, very fast."""
    radius_m = radius_km * 1000.0
    lat_step = resolution_m / 111320.0
    cos_lat = math.cos(math.radians(tx_lat))
    lon_step = resolution_m / (111320.0 * cos_lat)

    lat_min = tx_lat - radius_m / 111320.0
    lat_max = tx_lat + radius_m / 111320.0
    lon_min = tx_lon - radius_m / (111320.0 * cos_lat)
    lon_max = tx_lon + radius_m / (111320.0 * cos_lat)

    lats = np.arange(lat_min, lat_max, lat_step)
    lons = np.arange(lon_min, lon_max, lon_step)

    # Meshgrid for vectorised distance computation
    lon_grid, lat_grid = np.meshgrid(lons, lats)

    # Approximate distance in metres (fast flat-earth for coverage radii)
    dlat_m = (lat_grid - tx_lat) * 111320.0
    dlon_m = (lon_grid - tx_lon) * 111320.0 * cos_lat
    dist_m = np.sqrt(dlat_m ** 2 + dlon_m ** 2)

    # Mask out < 10 m and > radius
    valid = (dist_m >= 10.0) & (dist_m <= radius_m)
    dist_km = np.where(valid, dist_m / 1000.0, 0.001)

    # Vectorised FSPL
    fspl = np.where(valid,
                    20.0 * np.log10(dist_km) + 20.0 * np.log10(frequency_mhz) + 32.44,
                    0.0)

    rx_power = np.where(valid, eirp_dbm - fspl + rx_gain_dbi, -999.0)

    # Directional antenna reduction (vectorised)
    if antenna_h_beamwidth < 360:
        az_grid = np.degrees(np.arctan2(dlon_m, dlat_m)) % 360
        h_offset = np.abs(az_grid - antenna_azimuth_deg)
        h_offset = np.where(h_offset > 180, 360 - h_offset, h_offset)
        h_half_bw = antenna_h_beamwidth / 2
        h_red = np.where(h_offset <= h_half_bw,
                         12 * (h_offset / h_half_bw) ** 2,
                         np.where(h_offset <= 90,
                                  12 + (h_offset - h_half_bw) / (90 - h_half_bw) * (antenna_front_to_back_db - 12),
                                  antenna_front_to_back_db))
        rx_power = np.where(valid, rx_power - h_red, rx_power)

    grid = rx_power
    # Flip so row 0 = north
    grid_flipped = grid[::-1]

    image_base64 = power_to_image(
        grid_flipped, min_dbm=min_dbm, max_dbm=max_dbm,
        colormap=colormap, sensitivity=rx_sensitivity_dbm,
    )

    valid_vals = grid[grid > -999]
    stats = {}
    if len(valid_vals) > 0:
        stats = {
            "min_power_dbm": round(float(np.min(valid_vals)), 1),
            "max_power_dbm": round(float(np.max(valid_vals)), 1),
            "mean_power_dbm": round(float(np.mean(valid_vals)), 1),
            "cells_computed": int(len(valid_vals)),
            "cells_total": int(grid.size),
            "elapsed_seconds": 0.0,  # filled by caller
        }

    return {
        "grid": grid,
        "grid_flipped": grid_flipped,
        "image_base64": image_base64,
        "bounds": [[float(lat_min), float(lon_min)], [float(lat_max), float(lon_max)]],
        "stats": stats,
        "lats": lats,
        "lons": lons,
        "_power_grid": grid_flipped,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

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
    model: str = "terrain",
    # ITM-specific parameters
    itm_reliability_pct: float = 50.0,
    itm_radio_climate: int = 5,
    itm_ground_eps: float = 15.0,
    itm_ground_sigma: float = 0.005,
    itm_polarization: int = 1,
) -> dict:
    """Generate coverage as a PNG image overlay.

    Args:
        model: "terrain" for radial-sweep viewshed (default),
               "itm" for full Longley-Rice ITM model,
               "fspl" for quick FSPL-only preview.
        itm_reliability_pct: ITM reliability percentage (50-99)
        itm_radio_climate: ITM radio climate (1-7)
        itm_ground_eps: Ground dielectric constant
        itm_ground_sigma: Ground conductivity S/m
        itm_polarization: 0=horizontal, 1=vertical

    Returns base64-encoded PNG, Leaflet-style bounds, and summary stats.
    """
    t0 = time.time()
    eirp_dbm = tx_power_dbm + tx_gain_dbi - cable_loss_db

    # ------------------------------------------------------------------
    # FSPL-only quick mode
    # ------------------------------------------------------------------
    if model == "fspl":
        result = _generate_coverage_fspl(
            tx_lat, tx_lon, tx_height_m, eirp_dbm, rx_gain_dbi,
            rx_sensitivity_dbm, frequency_mhz, radius_km, resolution_m,
            min_dbm, max_dbm, colormap,
            antenna_azimuth_deg, antenna_tilt_deg,
            antenna_h_beamwidth, antenna_v_beamwidth,
            antenna_front_to_back_db,
        )
        elapsed = time.time() - t0
        result["stats"]["elapsed_seconds"] = round(elapsed, 2)
        logger.info("FSPL-only coverage in %.2fs", elapsed)
        logger.info(
            "Antenna params (FSPL): azimuth=%.1f, h_beamwidth=%.1f, v_beamwidth=%.1f, f/b=%.1f dB, directional=%s",
            antenna_azimuth_deg, antenna_h_beamwidth, antenna_v_beamwidth,
            antenna_front_to_back_db, antenna_h_beamwidth < 360,
        )
        return {
            "image_base64": result["image_base64"],
            "bounds": result["bounds"],
            "stats": result["stats"],
            "resolution_m": resolution_m,
            "radius_km": radius_km,
            "eirp_dbm": round(eirp_dbm, 1),
            "tx_lat": tx_lat,
            "tx_lon": tx_lon,
            "min_dbm": min_dbm,
            "max_dbm": max_dbm,
            "colormap": colormap,
        }

    # ------------------------------------------------------------------
    # ITM (Longley-Rice) radial sweep — most accurate, sequential
    # ------------------------------------------------------------------
    if model == "itm":
        radius_m = radius_km * 1000.0
        cos_lat = math.cos(math.radians(tx_lat))

        tx_ground = get_elevation(tx_lat, tx_lon)
        tx_asl = tx_ground + tx_height_m

        # Use 1° angular steps (360 radials) for ITM to keep runtime reasonable
        angular_step = 1.0
        n_radials = int(360 / angular_step)

        logger.info(
            "ITM radial sweep: %d radials, radius=%.1f km, res=%.0f m, reliability=%.0f%%",
            n_radials, radius_km, resolution_m, itm_reliability_pct,
        )

        all_lats = []
        all_lons = []
        all_powers = []

        # ITM uses module-level globals — process radials SEQUENTIALLY
        for i in range(n_radials):
            azimuth = i * angular_step
            lats_r, lons_r, powers_r = _compute_radial_itm(
                tx_lat, tx_lon, tx_asl, tx_height_m, azimuth,
                radius_km, resolution_m, frequency_mhz,
                itm_ground_eps, itm_ground_sigma, 301.0,
                itm_radio_climate, itm_polarization,
                itm_reliability_pct, itm_reliability_pct, itm_reliability_pct,
                rx_height_m, eirp_dbm, rx_gain_dbi,
                antenna_azimuth_deg, antenna_tilt_deg,
                antenna_h_beamwidth, antenna_v_beamwidth,
                antenna_front_to_back_db,
            )
            if len(lats_r) > 0:
                all_lats.append(lats_r)
                all_lons.append(lons_r)
                all_powers.append(powers_r)

            if (i + 1) % 60 == 0:
                elapsed = time.time() - t0
                eta = elapsed / (i + 1) * (n_radials - i - 1)
                logger.info(
                    "  ITM progress: %d/%d (%.0f%%) – %.1fs elapsed, ~%.1fs remaining",
                    i + 1, n_radials, 100 * (i + 1) / n_radials, elapsed, eta,
                )

        # Concatenate all radial results
        all_lats = np.concatenate(all_lats)
        all_lons = np.concatenate(all_lons)
        all_powers = np.concatenate(all_powers)

        # Rasterise radial points -> rectangular grid
        lat_min = tx_lat - radius_km / 111.0
        lat_max = tx_lat + radius_km / 111.0
        lon_min = tx_lon - radius_km / (111.0 * cos_lat)
        lon_max = tx_lon + radius_km / (111.0 * cos_lat)

        grid_rows = max(1, int((lat_max - lat_min) * 111000 / resolution_m))
        grid_cols = max(1, int((lon_max - lon_min) * 111000 * cos_lat / resolution_m))

        power_grid = np.full((grid_rows, grid_cols), -999.0, dtype=np.float64)

        row_indices = ((lat_max - all_lats) / (lat_max - lat_min) * grid_rows).astype(int)
        col_indices = ((all_lons - lon_min) / (lon_max - lon_min) * grid_cols).astype(int)

        valid_mask = (
            (row_indices >= 0) & (row_indices < grid_rows) &
            (col_indices >= 0) & (col_indices < grid_cols)
        )
        row_indices = row_indices[valid_mask]
        col_indices = col_indices[valid_mask]
        powers = all_powers[valid_mask]

        for idx in range(len(row_indices)):
            r, c, p = row_indices[idx], col_indices[idx], powers[idx]
            if p > power_grid[r, c]:
                power_grid[r, c] = p

        _fill_gaps(power_grid)

        elapsed = time.time() - t0
        logger.info("ITM coverage complete in %.1fs", elapsed)

        image_base64 = power_to_image(
            power_grid, min_dbm=min_dbm, max_dbm=max_dbm,
            colormap=colormap, sensitivity=rx_sensitivity_dbm,
        )

        valid = power_grid[power_grid > -999]
        stats = {}
        if len(valid) > 0:
            stats = {
                "min_power_dbm": round(float(np.min(valid)), 1),
                "max_power_dbm": round(float(np.max(valid)), 1),
                "mean_power_dbm": round(float(np.mean(valid)), 1),
                "cells_computed": int(len(valid)),
                "cells_total": int(grid_rows * grid_cols),
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
            "_power_grid": power_grid,
        }

    # ------------------------------------------------------------------
    # Terrain-aware radial sweep
    # ------------------------------------------------------------------
    radius_m = radius_km * 1000.0
    cos_lat = math.cos(math.radians(tx_lat))

    # TX ground + mast
    tx_ground = get_elevation(tx_lat, tx_lon)
    tx_asl = tx_ground + tx_height_m

    # Angular resolution — 0.25° gives 1440 radials.
    # At 25 km range gap between radials ≈ 25000 * sin(0.25°) ≈ 109 m.
    angular_step = 0.25
    n_radials = int(360 / angular_step)
    n_steps = int(radius_km * 1000 / resolution_m)

    logger.info(
        "Radial sweep: %d radials x %d steps = %d points, radius=%.1f km, res=%.0f m",
        n_radials, n_steps, n_radials * n_steps, radius_km, resolution_m,
    )
    logger.info(
        "Antenna params: azimuth=%.1f, tilt=%.1f, h_beamwidth=%.1f, v_beamwidth=%.1f, f/b=%.1f dB, directional=%s",
        antenna_azimuth_deg, antenna_tilt_deg,
        antenna_h_beamwidth, antenna_v_beamwidth,
        antenna_front_to_back_db,
        antenna_h_beamwidth < 360,
    )

    # Parallel radial computation
    max_workers = min(os.cpu_count() or 4, 16)
    all_lats = []
    all_lons = []
    all_powers = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for i in range(n_radials):
            azimuth = i * angular_step
            fut = pool.submit(
                _compute_radial,
                tx_lat, tx_lon, tx_asl, azimuth,
                radius_km, resolution_m, frequency_mhz, k_factor,
                tx_gain_dbi, eirp_dbm, rx_gain_dbi, rx_height_m,
                antenna_azimuth_deg, antenna_tilt_deg,
                antenna_h_beamwidth, antenna_v_beamwidth,
                antenna_front_to_back_db,
            )
            futures[fut] = i

        completed = 0
        for future in concurrent.futures.as_completed(futures):
            lats_r, lons_r, powers_r = future.result()
            if len(lats_r) > 0:
                all_lats.append(lats_r)
                all_lons.append(lons_r)
                all_powers.append(powers_r)
            completed += 1
            if completed % 200 == 0:
                elapsed = time.time() - t0
                eta = elapsed / completed * (n_radials - completed)
                logger.info(
                    "  Radial progress: %d/%d (%.0f%%) – %.1fs elapsed, ~%.1fs remaining",
                    completed, n_radials, 100 * completed / n_radials, elapsed, eta,
                )

    # Concatenate all radial results
    all_lats = np.concatenate(all_lats)
    all_lons = np.concatenate(all_lons)
    all_powers = np.concatenate(all_powers)

    # ------------------------------------------------------------------
    # Rasterise radial points → rectangular grid
    # ------------------------------------------------------------------
    lat_min = tx_lat - radius_km / 111.0
    lat_max = tx_lat + radius_km / 111.0
    lon_min = tx_lon - radius_km / (111.0 * cos_lat)
    lon_max = tx_lon + radius_km / (111.0 * cos_lat)

    grid_rows = max(1, int((lat_max - lat_min) * 111000 / resolution_m))
    grid_cols = max(1, int((lon_max - lon_min) * 111000 * cos_lat / resolution_m))

    power_grid = np.full((grid_rows, grid_cols), -999.0, dtype=np.float64)

    # Map each radial point to nearest grid cell, keep strongest signal
    row_indices = ((lat_max - all_lats) / (lat_max - lat_min) * grid_rows).astype(int)
    col_indices = ((all_lons - lon_min) / (lon_max - lon_min) * grid_cols).astype(int)

    # Clip to valid range
    valid_mask = (
        (row_indices >= 0) & (row_indices < grid_rows) &
        (col_indices >= 0) & (col_indices < grid_cols)
    )
    row_indices = row_indices[valid_mask]
    col_indices = col_indices[valid_mask]
    powers = all_powers[valid_mask]

    # Scatter — keep best signal per cell
    for idx in range(len(row_indices)):
        r, c, p = row_indices[idx], col_indices[idx], powers[idx]
        if p > power_grid[r, c]:
            power_grid[r, c] = p

    # Fill NaN gaps: simple nearest-neighbour fill for any remaining -999 cells
    # surrounded by valid data (happens at outer edge of radials).
    _fill_gaps(power_grid)

    elapsed = time.time() - t0
    logger.info("Radial sweep coverage complete in %.1fs", elapsed)

    # Convert to PNG
    image_base64 = power_to_image(
        power_grid, min_dbm=min_dbm, max_dbm=max_dbm,
        colormap=colormap, sensitivity=rx_sensitivity_dbm,
    )

    # Stats
    valid = power_grid[power_grid > -999]
    stats = {}
    if len(valid) > 0:
        stats = {
            "min_power_dbm": round(float(np.min(valid)), 1),
            "max_power_dbm": round(float(np.max(valid)), 1),
            "mean_power_dbm": round(float(np.mean(valid)), 1),
            "cells_computed": int(len(valid)),
            "cells_total": int(grid_rows * grid_cols),
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
        "_power_grid": power_grid,
    }


def _fill_gaps(grid: np.ndarray, sentinel: float = -999.0):
    """Fill gap cells (== sentinel) with the average of valid 4-neighbours.

    Single pass — only fills cells that have at least one valid neighbour.
    Good enough for the thin gaps between radial spokes.
    """
    rows, cols = grid.shape
    gaps = np.argwhere(grid == sentinel)
    for r, c in gaps:
        neighbours = []
        if r > 0 and grid[r - 1, c] != sentinel:
            neighbours.append(grid[r - 1, c])
        if r < rows - 1 and grid[r + 1, c] != sentinel:
            neighbours.append(grid[r + 1, c])
        if c > 0 and grid[r, c - 1] != sentinel:
            neighbours.append(grid[r, c - 1])
        if c < cols - 1 and grid[r, c + 1] != sentinel:
            neighbours.append(grid[r, c + 1])
        if neighbours:
            grid[r, c] = sum(neighbours) / len(neighbours)
