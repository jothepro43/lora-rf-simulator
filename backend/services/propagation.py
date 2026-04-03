"""RF propagation models for LoRa at 915 MHz."""

import math
import numpy as np

# Constants
SPEED_OF_LIGHT = 299792458.0  # m/s
EARTH_RADIUS = 6371000.0  # meters
DEFAULT_K_FACTOR = 4.0 / 3.0  # standard atmosphere


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters between two points."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS * math.asin(math.sqrt(a))


def fspl(distance_m: float, frequency_mhz: float) -> float:
    """Free Space Path Loss in dB.

    FSPL(dB) = 20*log10(d) + 20*log10(f) + 32.44
    where d is in km and f is in MHz.
    """
    if distance_m <= 0:
        return 0.0
    distance_km = distance_m / 1000.0
    return 20 * math.log10(distance_km) + 20 * math.log10(frequency_mhz) + 32.44


def fresnel_radius(n: int, distance_m: float, d1_m: float, frequency_mhz: float) -> float:
    """Fresnel zone radius at a point along the path.

    Args:
        n: Fresnel zone number (1 = first zone)
        distance_m: Total path length
        d1_m: Distance from transmitter to the point
        frequency_mhz: Frequency in MHz

    Returns:
        Fresnel zone radius in meters
    """
    d2_m = distance_m - d1_m
    if d1_m <= 0 or d2_m <= 0 or distance_m <= 0:
        return 0.0
    wavelength = SPEED_OF_LIGHT / (frequency_mhz * 1e6)
    return math.sqrt(n * wavelength * d1_m * d2_m / distance_m)


def earth_curvature(distance_m: float, d1_m: float, k_factor: float = DEFAULT_K_FACTOR) -> float:
    """Earth curvature correction in meters at a point along the path.

    The effective earth radius is k * R_earth.
    Bulge height = d1 * d2 / (2 * k * R_earth)
    """
    d2_m = distance_m - d1_m
    effective_radius = k_factor * EARTH_RADIUS
    return (d1_m * d2_m) / (2.0 * effective_radius)


def knife_edge_diffraction_loss(v: float) -> float:
    """Single knife-edge diffraction loss in dB.

    Uses the ITU-R P.526 approximation.
    v = Fresnel-Kirchhoff diffraction parameter.
    """
    if v < -0.78:
        return 0.0
    return 6.9 + 20 * math.log10(math.sqrt((v - 0.1) ** 2 + 1) + v - 0.1)


def diffraction_parameter(h: float, d1_m: float, d2_m: float, frequency_mhz: float) -> float:
    """Compute Fresnel-Kirchhoff diffraction parameter v.

    Args:
        h: Obstruction height above LoS line (meters, positive = blocked)
        d1_m: Distance from TX to obstruction
        d2_m: Distance from obstruction to RX
        frequency_mhz: Frequency
    """
    wavelength = SPEED_OF_LIGHT / (frequency_mhz * 1e6)
    if d1_m <= 0 or d2_m <= 0:
        return 0.0
    return h * math.sqrt(2.0 / (wavelength * d1_m * d2_m / (d1_m + d2_m)))


def deygout_diffraction_loss(
    distances: list[float],
    elevations: list[float],
    tx_height_m: float,
    rx_height_m: float,
    frequency_mhz: float,
    k_factor: float = DEFAULT_K_FACTOR,
) -> float:
    """Deygout 94 method for multiple knife-edge diffraction.

    Finds the dominant obstacle, computes its diffraction loss, then
    recursively handles sub-paths.
    """
    if len(distances) < 3:
        return 0.0

    total_dist = distances[-1] - distances[0]
    if total_dist <= 0:
        return 0.0

    # TX and RX heights above sea level
    tx_asl = elevations[0] + tx_height_m
    rx_asl = elevations[-1] + rx_height_m

    # Find the dominant obstacle (maximum diffraction parameter)
    max_v = -999.0
    max_idx = -1

    for i in range(1, len(distances) - 1):
        d1 = distances[i] - distances[0]
        d2 = distances[-1] - distances[i]
        if d1 <= 0 or d2 <= 0:
            continue

        # LoS height at this point
        los_height = tx_asl + (rx_asl - tx_asl) * d1 / total_dist

        # Terrain + earth curvature
        terrain_height = elevations[i] + earth_curvature(total_dist, d1, k_factor)

        # Height above LoS (positive = obstruction)
        h = terrain_height - los_height

        v = diffraction_parameter(h, d1, d2, frequency_mhz)
        if v > max_v:
            max_v = v
            max_idx = i

    if max_idx < 0 or max_v < -0.78:
        return 0.0

    # Main obstacle loss
    loss = knife_edge_diffraction_loss(max_v)

    # Recursively handle sub-paths (TX to obstacle, obstacle to RX)
    if max_idx > 1:
        sub_loss = deygout_diffraction_loss(
            distances[: max_idx + 1],
            elevations[: max_idx + 1],
            tx_height_m,
            elevations[max_idx] - elevations[0],  # obstacle as new RX
            frequency_mhz,
            k_factor,
        )
        loss += max(0, sub_loss)

    if max_idx < len(distances) - 2:
        sub_loss = deygout_diffraction_loss(
            distances[max_idx:],
            elevations[max_idx:],
            elevations[max_idx] - elevations[max_idx],  # obstacle as new TX (height 0 relative)
            rx_height_m,
            frequency_mhz,
            k_factor,
        )
        loss += max(0, sub_loss)

    return loss


def weather_fade(
    distance_km: float,
    frequency_mhz: float = 915.0,
    rain_rate_mmh: float = 0.0,
    wet_foliage: bool = False,
    ice: bool = False,
) -> float:
    """Weather-related fade in dB based on ITU-R P.838 for rain.

    At 915 MHz, rain attenuation is very small but non-zero for heavy rain.
    """
    fade = 0.0

    # Rain attenuation (ITU-R P.838-3 specific attenuation)
    # At 915 MHz, coefficients are very small
    if rain_rate_mmh > 0:
        # Approximate specific attenuation at 915 MHz
        # k and alpha from ITU-R P.838 for vertical polarization near 1 GHz
        k = 0.0000387
        alpha = 0.912
        gamma_r = k * (rain_rate_mmh ** alpha)  # dB/km
        fade += gamma_r * distance_km

    # Wet foliage - empirical addition
    if wet_foliage:
        fade += 0.3 * distance_km  # ~0.3 dB/km additional

    # Ice loading on antennas/cables
    if ice:
        fade += 1.5  # flat additional loss

    return fade


def itm_approximation(
    distance_m: float,
    frequency_mhz: float,
    tx_height_m: float,
    rx_height_m: float,
    terrain_variability_m: float = 90.0,
    climate: str = "temperate",
    reliability_pct: float = 50.0,
) -> float:
    """Simplified ITM/Longley-Rice approximation.

    This is a parametric approximation, not the full ITM model.
    Uses FSPL + terrain irregularity correction + climate correction.
    """
    # Base FSPL
    loss = fspl(distance_m, frequency_mhz)

    # Terrain irregularity factor (dh = terrain variability)
    if terrain_variability_m > 0 and distance_m > 1000:
        dh_factor = 6.0 * math.log10(terrain_variability_m / 50.0)
        loss += max(0, dh_factor)

    # Climate correction
    climate_corrections = {
        "tropical": 2.0,
        "subtropical": 1.0,
        "temperate": 0.0,
        "desert": -1.0,
        "maritime": 1.5,
    }
    loss += climate_corrections.get(climate, 0.0)

    # Reliability correction (log-normal fading margin)
    if reliability_pct > 50:
        # Standard deviation ~8 dB for mixed terrain
        sigma = 8.0
        from scipy.stats import norm
        z = norm.ppf(reliability_pct / 100.0)
        loss += z * sigma

    return loss


def compute_path_loss(
    distances: list[float],
    elevations: list[float],
    tx_height_m: float,
    rx_height_m: float,
    frequency_mhz: float = 915.0,
    k_factor: float = DEFAULT_K_FACTOR,
    model: str = "fspl_diffraction",
    rain_rate_mmh: float = 0.0,
    wet_foliage: bool = False,
    ice: bool = False,
) -> dict:
    """Compute total path loss using selected model.

    Returns dict with breakdown of loss components.
    """
    total_distance = distances[-1] if distances else 0.0

    # Free space path loss
    fspl_loss = fspl(total_distance, frequency_mhz)

    # Diffraction loss (Deygout 94)
    diff_loss = deygout_diffraction_loss(
        distances, elevations, tx_height_m, rx_height_m, frequency_mhz, k_factor
    )

    # Weather
    weather_loss = weather_fade(
        total_distance / 1000.0, frequency_mhz, rain_rate_mmh, wet_foliage, ice
    )

    total_loss = fspl_loss + diff_loss + weather_loss

    return {
        "total_path_loss_db": round(total_loss, 2),
        "fspl_db": round(fspl_loss, 2),
        "diffraction_db": round(diff_loss, 2),
        "weather_db": round(weather_loss, 2),
        "distance_m": round(total_distance, 1),
        "model": model,
    }
