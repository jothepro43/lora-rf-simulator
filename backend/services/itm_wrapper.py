"""
Wrapper to integrate the NTIA ITM (Longley-Rice) model with our terrain service.
"""
import numpy as np
import math
import logging
from services.terrain import get_elevation, batch_get_elevation

logger = logging.getLogger(__name__)

# ITM parameters for 915 MHz LoRa in Georgia
DEFAULT_ITM_PARAMS = {
    'eps_dielect': 15.0,       # Earth dielectric constant (farmland/forest)
    'sgm_conductivity': 0.005, # Earth conductivity S/m (average ground)
    'eno_ns_surfref': 301.0,   # Surface refractivity N-units (continental temperate)
    'frq_mhz': 915.0,         # Frequency MHz
    'radio_climate': 5,        # Continental temperate
    'pol': 1,                  # Vertical polarization (LoRa)
    'pctTime': 50,             # % time (50 = median)
    'pctLoc': 50,              # % locations (50 = median)
    'pctConf': 50,             # % confidence
}

# Ground type presets: (eps_dielect, sgm_conductivity)
GROUND_PRESETS = {
    'average':     (15.0,  0.005),
    'poor':        (4.0,   0.001),
    'good':        (25.0,  0.020),
    'fresh_water': (81.0,  0.010),
    'sea_water':   (81.0,  5.000),
    'farmland':    (15.0,  0.005),
    'city':        (5.0,   0.001),
    'forest':      (13.0,  0.005),
    'mountain':    (13.0,  0.002),
    'sand':        (10.0,  0.002),
}


def norm_quantile(p):
    """Inverse normal CDF (quantile function) - approximation."""
    if p <= 0:
        return -5.0
    if p >= 1:
        return 5.0
    if p == 0.5:
        return 0.0

    # Rational approximation (Abramowitz and Stegun 26.2.23)
    if p < 0.5:
        t = math.sqrt(-2 * math.log(p))
    else:
        t = math.sqrt(-2 * math.log(1 - p))

    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308

    result = t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t)

    if p < 0.5:
        return -result
    return result


def compute_itm_path_loss(tx_lat, tx_lon, tx_height_m, rx_lat, rx_lon, rx_height_m,
                          freq_mhz=915.0, num_profile_points=600,
                          eps_dielect=15.0, sgm_conductivity=0.005,
                          eno_ns_surfref=301.0, radio_climate=5, pol=1,
                          pct_time=50, pct_loc=50, pct_conf=50):
    """
    Compute path loss between two points using the full ITM model.

    Returns dict with: path_loss_db, mode (LoS/diffraction/troposcatter),
    delta_h (terrain roughness), etc.
    """
    from services import itm

    # Calculate distance
    dlat = math.radians(rx_lat - tx_lat)
    dlon = math.radians(rx_lon - tx_lon)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(tx_lat)) * math.cos(math.radians(rx_lat)) *
         math.sin(dlon / 2) ** 2)
    dist_m = 6371000 * 2 * math.asin(math.sqrt(a))

    if dist_m < 10:
        return {'path_loss_db': 0, 'mode': 'near-field', 'distance_m': dist_m}

    # Build terrain profile
    profile_lats = np.linspace(tx_lat, rx_lat, num_profile_points)
    profile_lons = np.linspace(tx_lon, rx_lon, num_profile_points)
    elevations = batch_get_elevation(profile_lats, profile_lons)

    step_m = dist_m / (num_profile_points - 1)

    # ITM profile format: [num_points-1, step_distance, elev0, ..., elevN]
    pfl = np.zeros(num_profile_points + 2)
    pfl[0] = num_profile_points - 1
    pfl[1] = step_m
    pfl[2:] = elevations

    result = itm.point_to_point(
        pfl, [tx_height_m, rx_height_m],
        fmhz=freq_mhz, ens=eno_ns_surfref, pol=pol,
        eps=eps_dielect, sgm=sgm_conductivity,
        climate=radio_climate, mdvar=12,
        pct_time=pct_time, pct_loc=pct_loc, pct_conf=pct_conf,
    )

    # Free space path loss for reference
    dist_km = dist_m / 1000.0
    fspl = 20.0 * math.log10(dist_km) + 20.0 * math.log10(freq_mhz) + 32.44

    return {
        'path_loss_db': result['path_loss_db'],
        'fspl_db': round(fspl, 1),
        'excess_loss_db': round(result['path_loss_db'] - fspl, 1),
        'delta_h': result['delta_h'],
        'mode': result['mode'],
        'distance_m': round(dist_m, 1),
        'distance_km': round(dist_m / 1000, 2),
    }
