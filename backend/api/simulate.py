"""Simulation API endpoints."""

import time
import hashlib
import json
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/simulate", tags=["simulate"])

# In-memory cache for pre-computed coverage results
_precompute_cache: dict[str, dict] = {}


class LosRequest(BaseModel):
    tx_lat: float
    tx_lon: float
    tx_height_m: float = 10.0
    rx_lat: float
    rx_lon: float
    rx_height_m: float = 1.5
    frequency_mhz: float = 915.0
    num_points: int = 200
    k_factor: float = 1.333


class CoverageRequest(BaseModel):
    tx_lat: float
    tx_lon: float
    tx_height_m: float = 10.0
    tx_power_dbm: float = 22.0
    tx_gain_dbi: float = 2.0
    cable_loss_db: float = 0.0
    rx_gain_dbi: float = 2.0
    rx_sensitivity_dbm: float = -148.0
    frequency_mhz: float = 915.0
    radius_km: float = 5.0
    resolution_m: float = 180.0
    rx_height_m: float = 1.5
    k_factor: float = 1.333
    rain_rate_mmh: float = 0.0
    min_dbm: float = -130.0
    max_dbm: float = -80.0
    colormap: str = "plasma"
    antenna_azimuth_deg: float = 0.0
    antenna_tilt_deg: float = 0.0
    antenna_h_beamwidth: float = 360.0
    antenna_v_beamwidth: float = 90.0
    antenna_front_to_back_db: float = 0.0
    model: str = "terrain"  # "terrain" (radial sweep) or "fspl" (quick preview)


class LinkBudgetRequest(BaseModel):
    tx_power_dbm: float = 22.0
    tx_gain_dbi: float = 2.0
    cable_type: str = "ideal"
    cable_length_m: float = 0.0
    connectors: int = 0
    rx_gain_dbi: float = 2.0
    rx_sensitivity_dbm: float = -148.0
    # Either provide direct path loss or let us compute from coords
    path_loss_db: Optional[float] = None
    # For auto-computation
    tx_lat: Optional[float] = None
    tx_lon: Optional[float] = None
    tx_height_m: float = 10.0
    rx_lat: Optional[float] = None
    rx_lon: Optional[float] = None
    rx_height_m: float = 1.5
    frequency_mhz: float = 915.0


@router.post("/los")
def simulate_los(req: LosRequest):
    from services.los_profile import compute_los_profile
    from services.propagation import compute_path_loss

    profile = compute_los_profile(
        req.tx_lat, req.tx_lon, req.tx_height_m,
        req.rx_lat, req.rx_lon, req.rx_height_m,
        req.frequency_mhz, req.num_points, req.k_factor,
    )

    # Also compute path loss
    path_loss = compute_path_loss(
        profile["distances"],
        profile["elevations"],
        req.tx_height_m,
        req.rx_height_m,
        req.frequency_mhz,
        req.k_factor,
    )

    return {**profile, "path_loss": path_loss}


@router.post("/coverage")
def simulate_coverage(req: CoverageRequest):
    from services.coverage import generate_coverage

    result = generate_coverage(
        tx_lat=req.tx_lat,
        tx_lon=req.tx_lon,
        tx_height_m=req.tx_height_m,
        tx_power_dbm=req.tx_power_dbm,
        tx_gain_dbi=req.tx_gain_dbi,
        cable_loss_db=req.cable_loss_db,
        rx_gain_dbi=req.rx_gain_dbi,
        rx_sensitivity_dbm=req.rx_sensitivity_dbm,
        frequency_mhz=req.frequency_mhz,
        radius_km=req.radius_km,
        resolution_m=req.resolution_m,
        rx_height_m=req.rx_height_m,
        k_factor=req.k_factor,
        rain_rate_mmh=req.rain_rate_mmh,
        min_dbm=req.min_dbm,
        max_dbm=req.max_dbm,
        colormap=req.colormap,
        antenna_azimuth_deg=req.antenna_azimuth_deg,
        antenna_tilt_deg=req.antenna_tilt_deg,
        antenna_h_beamwidth=req.antenna_h_beamwidth,
        antenna_v_beamwidth=req.antenna_v_beamwidth,
        antenna_front_to_back_db=req.antenna_front_to_back_db,
        model=req.model,
    )
    # Strip internal numpy grid from response
    result.pop("_power_grid", None)
    return result


class MultiCoverageRequest(BaseModel):
    nodes: list[CoverageRequest]
    combine_mode: str = "best"  # "best" (max signal) or "sum"


@router.post("/coverage/multi")
def simulate_multi_coverage(req: MultiCoverageRequest):
    """Run coverage from multiple nodes and combine into a single overlay."""
    from services.coverage import generate_coverage, power_to_image
    import numpy as np
    import math
    import logging

    logger = logging.getLogger(__name__)

    if not req.nodes:
        return {"error": "No nodes provided"}

    t0 = time.time()

    # Use the first node's display params as reference
    ref = req.nodes[0]
    resolution_m = ref.resolution_m
    min_dbm = ref.min_dbm
    max_dbm = ref.max_dbm
    colormap = ref.colormap
    rx_sensitivity_dbm = ref.rx_sensitivity_dbm

    # Compute common bounds across all nodes
    all_bounds = []
    for node_req in req.nodes:
        radius_km = node_req.radius_km
        cos_lat = math.cos(math.radians(node_req.tx_lat))
        lat_min = node_req.tx_lat - radius_km / 111.0
        lat_max = node_req.tx_lat + radius_km / 111.0
        lon_min = node_req.tx_lon - radius_km / (111.0 * cos_lat)
        lon_max = node_req.tx_lon + radius_km / (111.0 * cos_lat)
        all_bounds.append([[lat_min, lon_min], [lat_max, lon_max]])

    common_bounds = [
        [min(b[0][0] for b in all_bounds), min(b[0][1] for b in all_bounds)],
        [max(b[1][0] for b in all_bounds), max(b[1][1] for b in all_bounds)],
    ]

    lat_range = common_bounds[1][0] - common_bounds[0][0]
    lon_range = common_bounds[1][1] - common_bounds[0][1]
    avg_lat = (common_bounds[0][0] + common_bounds[1][0]) / 2
    cos_avg = math.cos(math.radians(avg_lat))

    grid_rows = max(1, int(lat_range * 111000 / resolution_m))
    grid_cols = max(1, int(lon_range * 111000 * cos_avg / resolution_m))
    combined_grid = np.full((grid_rows, grid_cols), -999.0, dtype=np.float64)

    logger.info("Multi-coverage: %d nodes, common grid %dx%d", len(req.nodes), grid_rows, grid_cols)

    for i, node_req in enumerate(req.nodes):
        result = generate_coverage(
            tx_lat=node_req.tx_lat,
            tx_lon=node_req.tx_lon,
            tx_height_m=node_req.tx_height_m,
            tx_power_dbm=node_req.tx_power_dbm,
            tx_gain_dbi=node_req.tx_gain_dbi,
            cable_loss_db=node_req.cable_loss_db,
            rx_gain_dbi=node_req.rx_gain_dbi,
            rx_sensitivity_dbm=node_req.rx_sensitivity_dbm,
            frequency_mhz=node_req.frequency_mhz,
            radius_km=node_req.radius_km,
            resolution_m=node_req.resolution_m,
            rx_height_m=node_req.rx_height_m,
            k_factor=node_req.k_factor,
            rain_rate_mmh=node_req.rain_rate_mmh,
            min_dbm=node_req.min_dbm,
            max_dbm=node_req.max_dbm,
            colormap=node_req.colormap,
            antenna_azimuth_deg=node_req.antenna_azimuth_deg,
            antenna_tilt_deg=node_req.antenna_tilt_deg,
            antenna_h_beamwidth=node_req.antenna_h_beamwidth,
            antenna_v_beamwidth=node_req.antenna_v_beamwidth,
            antenna_front_to_back_db=node_req.antenna_front_to_back_db,
            model=node_req.model,
        )

        # Use the raw power grid returned by generate_coverage
        node_grid = result.get("_power_grid")
        if node_grid is None:
            logger.warning("Multi-coverage: node %d has no _power_grid", i)
            continue

        node_bounds = result["bounds"]
        node_rows, node_cols = node_grid.shape

        # Map each cell from the node grid onto the common grid (best signal wins)
        for nr in range(node_rows):
            for nc in range(node_cols):
                power = node_grid[nr, nc]
                if power <= -999:
                    continue

                # Lat/lon of this node grid cell (row 0 = north/lat_max)
                cell_lat = node_bounds[1][0] - (nr / node_rows) * (node_bounds[1][0] - node_bounds[0][0])
                cell_lon = node_bounds[0][1] + (nc / node_cols) * (node_bounds[1][1] - node_bounds[0][1])

                # Map to common grid
                cr = int((common_bounds[1][0] - cell_lat) / lat_range * grid_rows)
                cc = int((cell_lon - common_bounds[0][1]) / lon_range * grid_cols)

                if 0 <= cr < grid_rows and 0 <= cc < grid_cols:
                    if req.combine_mode == "best":
                        if power > combined_grid[cr, cc]:
                            combined_grid[cr, cc] = power
                    else:
                        if combined_grid[cr, cc] <= -999:
                            combined_grid[cr, cc] = power
                        else:
                            p1 = 10 ** (combined_grid[cr, cc] / 10)
                            p2 = 10 ** (power / 10)
                            combined_grid[cr, cc] = 10 * np.log10(p1 + p2)

        logger.info("Multi-coverage: node %d/%d processed", i + 1, len(req.nodes))

    combined_image = power_to_image(
        combined_grid, min_dbm=min_dbm, max_dbm=max_dbm,
        colormap=colormap, sensitivity=rx_sensitivity_dbm,
    )

    elapsed = time.time() - t0
    valid = combined_grid[combined_grid > -999]
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
        "image_base64": combined_image,
        "bounds": common_bounds,
        "stats": stats,
        "resolution_m": resolution_m,
        "radius_km": max(n.radius_km for n in req.nodes),
        "eirp_dbm": 0,
        "tx_lat": req.nodes[0].tx_lat,
        "tx_lon": req.nodes[0].tx_lon,
        "min_dbm": min_dbm,
        "max_dbm": max_dbm,
        "colormap": colormap,
        "node_count": len(req.nodes),
    }


@router.post("/link-budget")
def simulate_link_budget(req: LinkBudgetRequest):
    from services.link_budget import compute_link_budget

    path_loss = req.path_loss_db or 0.0
    diffraction = 0.0

    # If coordinates provided, compute path loss from terrain
    if req.tx_lat is not None and req.rx_lat is not None:
        from services.los_profile import compute_los_profile
        from services.propagation import compute_path_loss

        profile = compute_los_profile(
            req.tx_lat, req.tx_lon, req.tx_height_m,
            req.rx_lat, req.rx_lon, req.rx_height_m,
            req.frequency_mhz,
        )
        pl = compute_path_loss(
            profile["distances"],
            profile["elevations"],
            req.tx_height_m,
            req.rx_height_m,
            req.frequency_mhz,
        )
        path_loss = pl["fspl_db"]
        diffraction = pl["diffraction_db"]

    return compute_link_budget(
        tx_power_dbm=req.tx_power_dbm,
        tx_gain_dbi=req.tx_gain_dbi,
        cable_type=req.cable_type,
        cable_length_m=req.cable_length_m,
        connectors=req.connectors,
        rx_gain_dbi=req.rx_gain_dbi,
        rx_sensitivity_dbm=req.rx_sensitivity_dbm,
        path_loss_db=path_loss,
        diffraction_db=diffraction,
    )


# ---------------------------------------------------------------------------
# Pre-compute system
# ---------------------------------------------------------------------------

class PrecomputeRequest(BaseModel):
    name: str
    coverage: CoverageRequest


@router.post("/precompute")
def precompute_coverage(req: PrecomputeRequest):
    """Pre-compute and cache a coverage result for later retrieval."""
    from services.coverage import generate_coverage

    t0 = time.time()
    result = generate_coverage(
        tx_lat=req.coverage.tx_lat,
        tx_lon=req.coverage.tx_lon,
        tx_height_m=req.coverage.tx_height_m,
        tx_power_dbm=req.coverage.tx_power_dbm,
        tx_gain_dbi=req.coverage.tx_gain_dbi,
        cable_loss_db=req.coverage.cable_loss_db,
        rx_gain_dbi=req.coverage.rx_gain_dbi,
        rx_sensitivity_dbm=req.coverage.rx_sensitivity_dbm,
        frequency_mhz=req.coverage.frequency_mhz,
        radius_km=req.coverage.radius_km,
        resolution_m=req.coverage.resolution_m,
        rx_height_m=req.coverage.rx_height_m,
        k_factor=req.coverage.k_factor,
        rain_rate_mmh=req.coverage.rain_rate_mmh,
        min_dbm=req.coverage.min_dbm,
        max_dbm=req.coverage.max_dbm,
        colormap=req.coverage.colormap,
        antenna_azimuth_deg=req.coverage.antenna_azimuth_deg,
        antenna_tilt_deg=req.coverage.antenna_tilt_deg,
        antenna_h_beamwidth=req.coverage.antenna_h_beamwidth,
        antenna_v_beamwidth=req.coverage.antenna_v_beamwidth,
        antenna_front_to_back_db=req.coverage.antenna_front_to_back_db,
        model=req.coverage.model,
    )

    # Strip internal numpy grid before caching
    result.pop("_power_grid", None)

    cache_key = req.name
    _precompute_cache[cache_key] = {
        "name": req.name,
        "result": result,
        "created_at": time.time(),
        "compute_time_s": round(time.time() - t0, 1),
    }

    return {
        "name": req.name,
        "status": "completed",
        "compute_time_s": _precompute_cache[cache_key]["compute_time_s"],
        "stats": result.get("stats", {}),
    }


@router.get("/precompute")
def list_precomputed():
    """List all pre-computed coverage results."""
    items = []
    for key, entry in _precompute_cache.items():
        items.append({
            "name": entry["name"],
            "created_at": entry["created_at"],
            "compute_time_s": entry["compute_time_s"],
            "stats": entry["result"].get("stats", {}),
            "tx_lat": entry["result"].get("tx_lat"),
            "tx_lon": entry["result"].get("tx_lon"),
        })
    return items


@router.get("/precompute/{name}")
def get_precomputed(name: str):
    """Retrieve a pre-computed coverage result by name."""
    entry = _precompute_cache.get(name)
    if not entry:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Pre-computed result '{name}' not found")
    return entry["result"]


@router.delete("/precompute/{name}")
def delete_precomputed(name: str):
    """Delete a pre-computed coverage result."""
    if name in _precompute_cache:
        del _precompute_cache[name]
        return {"detail": f"Deleted pre-computed result '{name}'"}
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Pre-computed result '{name}' not found")
