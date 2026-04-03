"""Simulation API endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/simulate", tags=["simulate"])


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
    )


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
