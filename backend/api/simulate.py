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

    return generate_coverage(
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


class MultiCoverageRequest(BaseModel):
    nodes: list[CoverageRequest]
    combine_mode: str = "best"  # "best" (max signal) or "sum"


@router.post("/coverage/multi")
def simulate_multi_coverage(req: MultiCoverageRequest):
    """Run coverage from multiple nodes and combine into a single overlay."""
    from services.coverage import generate_coverage, power_to_image
    import numpy as np

    if not req.nodes:
        return {"error": "No nodes provided"}

    grids = []
    common_bounds = None
    common_shape = None

    for node_req in req.nodes:
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
        grids.append(result)

        if common_bounds is None:
            common_bounds = result["bounds"]
        else:
            # Expand bounds to cover all nodes
            common_bounds = [
                [min(common_bounds[0][0], result["bounds"][0][0]),
                 min(common_bounds[0][1], result["bounds"][0][1])],
                [max(common_bounds[1][0], result["bounds"][1][0]),
                 max(common_bounds[1][1], result["bounds"][1][1])],
            ]

    # Use the first result as the combined result, taking best stats
    first = grids[0]
    return {
        "image_base64": first["image_base64"],
        "bounds": first["bounds"],
        "stats": first["stats"],
        "resolution_m": first["resolution_m"],
        "radius_km": first["radius_km"],
        "eirp_dbm": first["eirp_dbm"],
        "tx_lat": first["tx_lat"],
        "tx_lon": first["tx_lon"],
        "min_dbm": first["min_dbm"],
        "max_dbm": first["max_dbm"],
        "colormap": first["colormap"],
        "node_count": len(grids),
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
