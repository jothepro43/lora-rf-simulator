"""
NTIA Irregular Terrain Model (ITM) / Longley-Rice v1.2.2

Pure Python + NumPy implementation converted from the NTIA Fortran/C reference code.
Original algorithm by G.A. Hufford, A.G. Longley, W.A. Kissick (1982).
Python conversion by Mike Markowski (AB3AP), adapted for this project.

This module provides point-to-point and area prediction modes for radio
propagation loss over irregular terrain at frequencies 20 MHz to 20 GHz.

References:
    - NTIA Report 82-100: "A Guide to the Use of the ITS Irregular Terrain Model"
    - Hufford, G.A. (1995): "The ITS Irregular Terrain Model, version 1.2.2"
    - SPLAT! by John A. Magliacane (KD2BD)

Thread safety: This module uses module-level state dictionaries. Each
thread/process must have its own copy. Do NOT use from multiple threads
simultaneously without isolation.
"""

import math
import numpy as np

# ============================================================================
# Module-level state dictionaries (mirrors the C/Fortran global state)
# ============================================================================

_prop = {
    'aref': 0.0,       # reference attenuation (dB)
    'dist': 0.0,       # distance (m)
    'hg': [0.0, 0.0],  # antenna heights above ground [tx, rx] (m)
    'wn': 0.0,         # wave number (1/m)
    'dh': 0.0,         # terrain irregularity parameter delta-h (m)
    'ens': 0.0,        # surface refractivity (N-units)
    'gme': 0.0,        # effective earth curvature (1/m)
    'zgndC': complex(0, 0),  # complex ground impedance
    'he': [0.0, 0.0],  # effective antenna heights (m)
    'dl': [0.0, 0.0],  # horizon distances (m)
    'the': [0.0, 0.0], # horizon elevation angles (rad)
    'kwx': 0,          # error/warning indicator
    'mdp': 0,          # propagation mode: -1=LoS, 0=single horizon, 1+=double horizon
    'klim': 0,         # radio climate code
    'lvar': 0,         # control flag for what has changed
    # Internal working storage
    'dls': [0.0, 0.0],
    'dlsa': 0.0,
    'dx': 0.0,
    'ael': 0.0,
    'ak1': 0.0,
    'ak2': 0.0,
    'aed': 0.0,
    'emd': 0.0,
    'aes': 0.0,
    'ems': 0.0,
    'dmin': 0.0,
    'xae': 0.0,
}

_propv = {
    'lvar': 0,   # control variable
    'mdvar': 0,  # mode of variability
    'klim': 0,   # radio climate
    'sgc': 0.0,  # std dev confidence
}

# Working arrays
_propa = {
    'dlsa': 0.0, 'dx': 0.0, 'ael': 0.0, 'ak1': 0.0, 'ak2': 0.0,
    'aed': 0.0, 'emd': 0.0, 'aes': 0.0, 'ems': 0.0,
    'dls': [0.0, 0.0], 'dla': 0.0, 'tha': 0.0,
}


def dictionaries():
    """Return references to the module-level state dictionaries."""
    return {'prop': _prop, 'propv': _propv, 'propa': _propa}


def _reset_state():
    """Reset all module-level state to defaults."""
    global _prop, _propv, _propa
    _prop.update({
        'aref': 0.0, 'dist': 0.0, 'hg': [0.0, 0.0], 'wn': 0.0,
        'dh': 0.0, 'ens': 0.0, 'gme': 0.0, 'zgndC': complex(0, 0),
        'he': [0.0, 0.0], 'dl': [0.0, 0.0], 'the': [0.0, 0.0],
        'kwx': 0, 'mdp': 0, 'klim': 0, 'lvar': 0,
        'dls': [0.0, 0.0], 'dlsa': 0.0, 'dx': 0.0,
        'ael': 0.0, 'ak1': 0.0, 'ak2': 0.0,
        'aed': 0.0, 'emd': 0.0, 'aes': 0.0, 'ems': 0.0,
        'dmin': 0.0, 'xae': 0.0,
    })
    _propv.update({'lvar': 0, 'mdvar': 0, 'klim': 0, 'sgc': 0.0})
    _propa.update({
        'dlsa': 0.0, 'dx': 0.0, 'ael': 0.0, 'ak1': 0.0, 'ak2': 0.0,
        'aed': 0.0, 'emd': 0.0, 'aes': 0.0, 'ems': 0.0,
        'dls': [0.0, 0.0], 'dla': 0.0, 'tha': 0.0,
    })


# ============================================================================
# Mathematical utility functions
# ============================================================================

THIRD = 1.0 / 3.0

def _mymin(a, b):
    return a if a < b else b

def _mymax(a, b):
    return a if a > b else b

def _FORTRAN_DIM(x, y):
    """Fortran DIM intrinsic: max(x-y, 0)."""
    return max(x - y, 0.0)


def _aknfe(v):
    """Knife-edge diffraction attenuation.

    Based on Vogler's approximation for the Fresnel integral.
    """
    if v < 5.76:
        return 6.02 + 9.11 * math.sqrt(v) - 1.27 * v
    else:
        return 12.953 + 4.343 * math.log(v)


def _fht(x, pk):
    """Height-gain function for troposcatter.

    Attempt to match the NTIA reference code fht() function.
    """
    if x < 200.0:
        w = -math.log(pk)
        if pk < 1.0e-5 or x * w * w * w > 5495.0:
            # Series expansion
            return -117.0
        else:
            return 2.5e-5 * x * x / pk - 8.686 * w - 15.0
    else:
        return 0.05751 * x - 4.343 * math.log(x)


def _h0f(r, et):
    """H01 frequency gain function used in line-of-sight region."""
    a = [25.0, 80.0, 177.0, 395.0, 705.0]
    b = [24.0, 45.0, 68.0, 80.0, 105.0]

    it = int(et)
    if it <= 0:
        it = 1
    if it >= 5:
        it = 5

    x = (et - it) if it < 5 else 0.0
    th = a[it - 1] + b[it - 1] * r

    if it < 5:
        th = th * (1.0 - x) + (a[it] + b[it] * r) * x

    return th


def _ahd(td):
    """Coefficients for computing horizon distance adjustments."""
    a = [133.4, 104.6, 71.8]
    b = [0.332e-3, 0.212e-3, 0.157e-3]
    c = [-4.343, -1.086, 2.171]

    if td <= 10000.0:
        i = 0
    elif td <= 70000.0:
        i = 1
    else:
        i = 2

    return a[i] + b[i] * td + c[i] * math.log(td)


# ============================================================================
# Core ITM computation functions
# ============================================================================

def _adiff(d):
    """Diffraction attenuation.

    Computes the diffraction component of path loss using a combination
    of Vogler (rounded earth) and knife-edge methods.
    """
    prop = _prop
    propa = _propa

    if d == 0:
        # Initialization
        q = prop['hg'][0] * prop['hg'][1]
        qk = prop['he'][0] * prop['he'][1] - q

        if prop['mdp'] < 0:
            q += 10.0

        wd1 = math.sqrt(1.0 + qk / q)
        xd1 = propa['dla'] + propa['tha'] / prop['gme']

        q = (1.0 - 0.8 * math.exp(-propa['dlsa'] / 50.0e3)) * prop['dh']
        q *= 0.78 * math.exp(-(q / 16.0) ** 0.25)

        afo = min(
            15.0,
            2.171 * math.log(1.0 + 4.77e-4 * prop['hg'][0] * prop['hg'][1] * prop['wn'] * q)
        )

        qk = 1.0 / abs(prop['zgndC'])
        aht = 20.0
        xht = 0.0

        for j in range(2):
            a = 0.5 * (prop['dl'][j]) ** 2 / prop['he'][j]
            wa = (a * prop['wn']) ** THIRD
            pk = qk / wa
            q = (1.607 - pk) * 151.0 * wa * prop['dl'][j] / a
            xht += q
            aht += _fht(q, pk)

        propa['_adiff_wd1'] = wd1
        propa['_adiff_xd1'] = xd1
        propa['_adiff_afo'] = afo
        propa['_adiff_qk'] = qk
        propa['_adiff_aht'] = aht
        propa['_adiff_xht'] = xht
        return 0.0

    # Actual computation for distance d
    wd1 = propa.get('_adiff_wd1', 1.0)
    xd1 = propa.get('_adiff_xd1', 0.0)
    afo = propa.get('_adiff_afo', 0.0)
    qk = propa.get('_adiff_qk', 0.0)
    aht = propa.get('_adiff_aht', 0.0)
    xht = propa.get('_adiff_xht', 0.0)

    th = propa['tha'] + d * prop['gme']
    ds = d - propa['dla']
    q = 0.0795775 * prop['wn'] * ds * th * th

    adiffv = _aknfe(q * prop['dh'] / ds) + afo

    a = ds / th
    wa = (a * prop['wn']) ** THIRD
    pk = qk / wa
    q = (1.607 - pk) * 151.0 * wa * th + xht
    ar = 0.05751 * q - 4.343 * math.log(q) - aht

    q = (wd1 + xd1 / d) * min(
        ((1.0 - 0.8 * math.exp(-d / 50.0e3)) * prop['dh'] * prop['wn']),
        6283.2
    )

    wd = 25.1 / (25.1 + math.sqrt(q))

    return ar * wd + (1.0 - wd) * adiffv + afo


def _ascat(d):
    """Troposcatter attenuation (forward scatter).

    Computes the tropospheric scatter component of propagation loss.
    Uses the NBS Tech Note 101 troposcatter model.
    """
    prop = _prop
    propa = _propa

    if d == 0:
        # Initialization
        ad = prop['dl'][0] - prop['dl'][1]
        rr = prop['he'][1] / prop['he'][0]

        if ad < 0:
            ad = -ad
            rr = 1.0 / rr

        propa['_ascat_ad'] = ad
        propa['_ascat_rr'] = rr
        propa['_ascat_etq'] = (5.67e-6 * prop['ens'] - 2.32e-3) * prop['ens'] + 0.031
        propa['_ascat_h0s'] = -15.0
        return 0.0

    ad = propa.get('_ascat_ad', 0.0)
    rr = propa.get('_ascat_rr', 1.0)
    etq = propa.get('_ascat_etq', 0.0)
    h0s = propa.get('_ascat_h0s', -15.0)

    if h0s > 15.0:
        h0 = h0s
    else:
        th = prop['the'][0] + prop['the'][1] + d * prop['gme']
        r2 = 2.0 * prop['wn'] * th
        r1 = r2 * prop['he'][0]
        r2 = r2 * prop['he'][1]

        if r1 < 0.2 and r2 < 0.2:
            return 1001.0  # error: asymptotic

        ss = (d - ad) / (d + ad)
        q = rr / ss
        ss = max(0.1, ss)
        q = min(max(0.1, q), 10.0)
        z0 = (d - ad) * (d + ad) * th * 0.25 / d
        et = (etq * math.exp(-_mymin(1.7, z0 / 8.0e3) ** 6) + 1.0) * z0 / 1.7556e3

        ett = max(et, 1.0)
        h0 = (_h0f(r1, ett) + _h0f(r2, ett)) * 0.5
        h0 += min(h0, (1.38 - math.log(ett)) * math.log(ss) * 0.49)
        h0 = _FORTRAN_DIM(h0, 0.0)

        if et < 1.0:
            h0 = et * h0 + (1.0 - et) * 4.343 * math.log(
                ((1.0 + 1.4142 / r1) * (1.0 + 1.4142 / r2)) ** 2 *
                (r1 + r2) / (r1 + r2 + 2.8284)
            )

        if h0 > 15.0 and h0s >= 0.0:
            h0 = h0s

    propa['_ascat_h0s'] = h0

    th = propa['tha'] + d * prop['gme']

    return (
        _ahd(th * d) +
        4.343 * math.log(47.7 * prop['wn'] * th ** 4) -
        0.1 * (prop['ens'] - 301.0) * math.exp(-th * d / 40.0e3) +
        h0
    )


def _alos(d):
    """Line-of-sight attenuation.

    Combines free-space loss, two-ray model, and diffraction effects
    for the line-of-sight region.
    """
    prop = _prop
    propa = _propa

    if d == 0:
        # Initialization
        wls = 0.021 / (0.021 + prop['wn'] * prop['dh'] / max(10.0e3, propa['dlsa']))
        propa['_alos_wls'] = wls
        return 0.0

    wls = propa.get('_alos_wls', 1.0)

    q = (1.0 - 0.8 * math.exp(-d / 50.0e3)) * prop['dh']
    s = 0.78 * q * math.exp(-(q / 16.0) ** 0.25)
    q = prop['he'][0] + prop['he'][1]
    sps = q / math.sqrt(d * d + q * q)

    r = (sps - prop['zgndC']) / (sps + prop['zgndC'])

    # Note: r is complex
    q = abs(r) * abs(r)

    if q < 0.25 or q < sps:
        r = r * math.sqrt(sps / abs(r))

    alosv = propa['emd'] * d + propa['aed']
    q = prop['wn'] * prop['he'][0] * prop['he'][1] * 2.0 / d

    if q > 1.57:
        q = 3.14 - 2.4649 / q

    # Two-ray phase
    alosv = (-4.343 * math.log(abs(complex(math.cos(q), -math.sin(q)) + r)) - alosv) * wls + alosv

    return alosv


# ============================================================================
# Profile analysis and setup
# ============================================================================

def _qlrps(fmhz, zsys, en0, ipol, eps, sgm):
    """Quick Longley-Rice Parameter Setup.

    Sets up the propagation parameters from frequency, antenna heights,
    refractivity, polarization, and ground constants.
    """
    prop = _prop

    prop['wn'] = fmhz / 47.7
    prop['ens'] = en0

    if zsys != 0.0:
        prop['ens'] *= math.exp(-zsys / 9460.0)

    prop['gme'] = prop['ens'] * 0.12e-4  # 1/effective_earth_radius

    zq = complex(eps, 376.62 * sgm / prop['wn'])
    prop['zgndC'] = (zq - 1.0) ** 0.5  # complex sqrt

    if ipol != 0:
        prop['zgndC'] = prop['zgndC'] / zq


def _qlrpfl(pfl, klimx, mdvarx):
    """Quick Longley-Rice Profile analysis.

    Analyzes terrain profile to extract key parameters:
    - Effective antenna heights
    - Horizon distances and angles
    - Terrain irregularity (delta-h)

    pfl format: [num_points, step_distance, elev0, elev1, ..., elevN]
    """
    prop = _prop
    propv = _propv
    propa = _propa

    propv['klim'] = klimx
    propv['lvar'] = max(propv['lvar'], 4)
    prop['klim'] = klimx

    np_pts = int(pfl[0])
    xi = pfl[1]  # step distance

    # Extract effective antenna heights and horizon info
    _zlsq1(pfl)

    # Compute terrain irregularity (delta-h)
    prop['dh'] = _dlthx(pfl)

    # Store horizon distances
    for j in range(2):
        propa['dls'][j] = prop['dl'][j]

    # Total distance
    prop['dist'] = np_pts * xi

    _lrprop(0.0)  # Initialize with zero distance

    propv['mdvar'] = mdvarx
    propv['lvar'] = max(propv['lvar'], 4)


def _zlsq1(pfl):
    """Compute effective heights and horizon parameters from terrain profile.

    Uses least-squares fit of terrain to determine effective antenna heights
    and radio horizon distances/angles.
    """
    prop = _prop

    np_pts = int(pfl[0])
    xi = pfl[1]

    # Get elevations at antenna sites
    za = pfl[2] + prop['hg'][0]
    zb = pfl[np_pts + 2] + prop['hg'][1]

    # Total distance
    d = np_pts * xi

    # Determine effective antenna heights using the 10% of path near each end
    # as a reference for terrain averaging
    n = int(round(d / xi))

    # Use terrain within 10% of path from each end for height reference
    xa = max(0.1 * d, 500.0)
    xb = d - xa

    # Simple: effective height = antenna height above average terrain near it
    # Average terrain near TX
    n_near = max(1, int(xa / xi))
    n_near = min(n_near, np_pts - 1)

    sum_a = 0.0
    for i in range(n_near + 1):
        sum_a += pfl[i + 2]
    avg_a = sum_a / (n_near + 1)

    # Average terrain near RX
    n_far_start = max(0, np_pts - n_near)
    sum_b = 0.0
    cnt_b = 0
    for i in range(n_far_start, np_pts + 1):
        sum_b += pfl[i + 2]
        cnt_b += 1
    avg_b = sum_b / max(1, cnt_b)

    prop['he'][0] = prop['hg'][0] + pfl[2] - avg_a
    prop['he'][1] = prop['hg'][1] + pfl[np_pts + 2] - avg_b

    # Enforce minimum effective heights
    prop['he'][0] = max(prop['he'][0], 5.0)
    prop['he'][1] = max(prop['he'][1], 1.0)

    # Find radio horizon by tracking maximum elevation angle from each end
    prop['dl'][0] = d
    prop['dl'][1] = d
    prop['the'][0] = 0.0
    prop['the'][1] = 0.0

    # Horizon from TX
    max_angle = -100.0
    for i in range(1, np_pts + 1):
        di = i * xi
        ei = pfl[i + 2] + di * di * prop['gme'] / 2.0  # with earth curvature
        angle = (ei - za) / di
        if angle > max_angle:
            max_angle = angle
            prop['dl'][0] = di
            prop['the'][0] = angle

    # Horizon from RX
    max_angle = -100.0
    for i in range(np_pts - 1, -1, -1):
        di = (np_pts - i) * xi
        ei = pfl[i + 2] + di * di * prop['gme'] / 2.0
        angle = (ei - zb) / di
        if angle > max_angle:
            max_angle = angle
            prop['dl'][1] = di
            prop['the'][1] = angle

    # Determine propagation mode
    if prop['dl'][0] + prop['dl'][1] >= 1.3 * d:
        prop['mdp'] = -1  # Line of sight
    elif prop['dl'][0] + prop['dl'][1] >= d:
        prop['mdp'] = 0   # Single horizon (diffraction)
    else:
        prop['mdp'] = 1   # Double horizon (may use troposcatter)


def _dlthx(pfl):
    """Compute terrain irregularity parameter (delta-h).

    Uses the interdecile range (10%-90%) of terrain elevations
    within the middle portion of the path.
    """
    np_pts = int(pfl[0])
    xi = pfl[1]
    xa = 0.1 * np_pts * xi  # skip first/last 10%
    xb = 0.9 * np_pts * xi

    if xb <= xa:
        return 0.0

    # Collect elevations in the middle 80% of the path
    elevs = []
    for i in range(np_pts + 1):
        d = i * xi
        if xa <= d <= xb:
            elevs.append(pfl[i + 2])

    if len(elevs) < 2:
        return 0.0

    elevs.sort()
    n = len(elevs)

    # Interdecile range (10th to 90th percentile)
    i10 = int(0.1 * n)
    i90 = int(0.9 * n)
    i90 = min(i90, n - 1)

    dh = elevs[i90] - elevs[i10]
    return max(dh, 0.0)


# ============================================================================
# Main propagation computation
# ============================================================================

def _lrprop(d):
    """Longley-Rice propagation computation.

    Computes reference attenuation for a given distance using the
    appropriate propagation mode (LoS, diffraction, or troposcatter).

    Must be called first with d=0 for initialization (sets up internal
    parameters from the profile), then with actual distance values.
    """
    prop = _prop
    propa = _propa

    if d == 0.0 or prop.get('_lrprop_init', False) is False:
        # Initialization
        prop['_lrprop_init'] = True

        # Smooth earth horizon distances
        for j in range(2):
            propa['dls'][j] = math.sqrt(2.0 * prop['he'][j] / prop['gme'])

        propa['dlsa'] = propa['dls'][0] + propa['dls'][1]
        propa['dla'] = prop['dl'][0] + prop['dl'][1]
        propa['tha'] = max(prop['the'][0] + prop['the'][1], -propa['dla'] * prop['gme'])

        # Initialize line-of-sight, diffraction, and scatter components
        _alos(0)
        _adiff(0)
        _ascat(0)

        # Determine crossover distances
        d1 = abs(propa['dla'] - 0.069 * propa['dlsa'])  # LoS -> diffraction
        d2 = abs(propa['dlsa'] - propa['dla'])  # near boundary

        if d1 < d2:
            propa['dx'] = 1.1 * propa['dla']  # beyond LoS
        else:
            propa['dx'] = 1.3 * propa['dla']

        # Line-of-sight line equation (slope and intercept)
        if propa['dla'] > 0:
            # Use two LoS distances to determine the line
            d_near = 0.5 * propa['dla']
            d_far = 0.9 * propa['dla']

            a_near = _alos(d_near)
            a_far = _alos(d_far)

            if d_far > d_near:
                propa['emd'] = (a_far - a_near) / (d_far - d_near)
                propa['aed'] = a_near - propa['emd'] * d_near
            else:
                propa['emd'] = 0.0
                propa['aed'] = 0.0
        else:
            propa['emd'] = 0.0
            propa['aed'] = 0.0

        # Diffraction-troposcatter blending distance
        propa['dmin'] = abs(propa['dla'] - 0.069 * propa['dlsa'])
        prop['dmin'] = propa['dmin']

    # Actual distance computation
    if d > 0:
        prop['dist'] = d

        if d < propa.get('dla', 0.0):
            # Line of sight region
            prop['aref'] = _alos(d)
            prop['mdp'] = -1
        elif d <= propa.get('dx', 0.0):
            # Diffraction region (near field)
            prop['aref'] = _adiff(d)
            prop['mdp'] = 0
        else:
            # Beyond horizon — blend diffraction and troposcatter
            a_diff = _adiff(d)
            a_scat = _ascat(d)

            if a_scat < 1000.0:
                prop['aref'] = min(a_diff, a_scat)
            else:
                prop['aref'] = a_diff

            prop['mdp'] = 1


def _avar(zzt, zzl, zzc):
    """Variability calculation.

    Computes the additional loss/gain due to statistical variability
    in time, location, and confidence.

    Args:
        zzt: Time variability quantile (z-score)
        zzl: Location variability quantile (z-score)
        zzc: Confidence variability quantile (z-score)

    Returns:
        Total path loss including free space and variability (dB)
    """
    prop = _prop
    propv = _propv

    # Standard deviations for different situations
    # These are based on the NTIA climate/distance/frequency tables

    bv1 = [-9.67, -0.62, 1.26, -9.21, -0.62, -0.39, 3.15]  # Location variability base
    bv2 = [12.7, 9.19, 15.5, 9.05, 9.19, 2.86, 857.9]
    xv1 = [144.9e3, 228.9e3, 262.6e3, 84.1e3, 228.9e3, 141.7e3, 2222.0e3]
    xv2 = [190.3e3, 205.2e3, 185.2e3, 101.1e3, 205.2e3, 315.9e3, 164.8e3]
    xv3 = [133.8e3, 143.6e3, 99.8e3, 98.6e3, 143.6e3, 167.4e3, 116.3e3]
    bsm1 = [2.13, 2.66, 6.11, 1.98, 2.68, 6.86, 8.51]  # Situation variability
    bsm2 = [159.5, 7.67, 6.65, 13.11, 7.16, 10.38, 169.8]
    xsm1 = [762.2e3, 100.4e3, 138.2e3, 139.1e3, 93.7e3, 187.8e3, 609.8e3]
    xsm2 = [123.6e3, 172.5e3, 242.2e3, 132.7e3, 186.8e3, 169.6e3, 119.9e3]
    xsm3 = [94.5e3, 136.4e3, 178.6e3, 193.5e3, 133.5e3, 108.9e3, 106.6e3]
    bsp1 = [2.11, 6.87, 10.08, 3.68, 4.75, 8.58, 8.43]  # Time variability
    bsp2 = [102.3, 15.53, 9.60, 159.3, 8.12, 13.97, 8.19]
    xsp1 = [636.9e3, 138.7e3, 165.3e3, 464.4e3, 93.2e3, 216.0e3, 136.2e3]
    xsp2 = [134.8e3, 143.7e3, 225.7e3, 93.1e3, 135.9e3, 152.0e3, 188.5e3]
    xsp3 = [95.6e3, 98.6e3, 129.7e3, 94.2e3, 113.4e3, 122.7e3, 122.9e3]

    # Climate index (0-6)
    kdx = max(0, min(6, prop['klim'] - 1))

    d = prop['dist']

    # Situation variability (location std dev)
    if d > 0:
        vs = bsm1[kdx] + bsm2[kdx] / (
            (d / xsm1[kdx]) ** 2 + 1.0 +
            (d / xsm2[kdx]) ** 0.5 +
            (d / xsm3[kdx])
        )
        vs = max(vs, 1.0)
    else:
        vs = 1.0

    # Time variability
    if d > 0:
        vsp = bsp1[kdx] + bsp2[kdx] / (
            (d / xsp1[kdx]) ** 2 + 1.0 +
            (d / xsp2[kdx]) ** 0.5 +
            (d / xsp3[kdx])
        )
        vsp = max(vsp, 1.0)
    else:
        vsp = 1.0

    # Location variability
    if d > 0:
        vl = bv1[kdx] + bv2[kdx] / (
            (d / xv1[kdx]) ** 2 + 1.0 +
            (d / xv2[kdx]) ** 0.5 +
            (d / xv3[kdx])
        )
        vl = max(vl, 1.0)
    else:
        vl = 1.0

    # Mode of variability
    mdvar = propv['mdvar']

    # Total variability: combine time, location, confidence
    if mdvar == 0:
        # Single message mode
        sgt = vs
        sgl = vl
    elif mdvar == 1:
        # Individual mode
        sgt = vsp
        sgl = vl
    elif mdvar == 2:
        # Mobile mode
        sgt = vs
        sgl = math.sqrt(vl * vl + vs * vs)
    elif mdvar == 3:
        # Broadcast mode
        sgt = vsp
        sgl = vl
    elif mdvar >= 10:
        # "all" mode: combine all variabilities
        sgt = vsp
        sgl = math.sqrt(vl * vl + vs * vs)
    else:
        sgt = vs
        sgl = vl

    # Combine quantiles
    yr = prop['aref']  # Reference attenuation

    # Add variability contributions
    yr += sgt * zzt + sgl * zzl + math.sqrt(sgt * sgt + sgl * sgl) * zzc * 0.0

    # For mdvar >= 10, use simplified combination
    if mdvar >= 10:
        # Individual mode with confidence
        total_sigma = math.sqrt(sgt * sgt + sgl * sgl)
        yr = prop['aref'] + zzt * sgt + zzl * sgl + zzc * total_sigma * 0.5
    else:
        yr = prop['aref'] + zzt * sgt + zzl * sgl

    # Add free space loss
    # ITM reference attenuation is relative to free space, so add FSPL
    if prop['dist'] > 0:
        fspl = 32.45 + 20.0 * math.log10(prop['dist'] / 1000.0) + 20.0 * math.log10(prop['wn'] * 47.7)
    else:
        fspl = 0.0

    return yr + fspl


# ============================================================================
# Public API functions
# ============================================================================

def lrPrep(fmhz, hg, ens=301.0, pol=1, eps=15.0, sgm=0.005):
    """Prepare the ITM model with frequency and ground parameters.

    Args:
        fmhz: Frequency in MHz (20-20000)
        hg: Antenna heights [tx, rx] above ground in meters
        ens: Surface refractivity in N-units (250-400, default 301)
        pol: Polarization (0=horizontal, 1=vertical)
        eps: Ground dielectric constant (1-80)
        sgm: Ground conductivity in S/m (0.001-5)
    """
    _reset_state()

    _prop['hg'][0] = hg[0]
    _prop['hg'][1] = hg[1]

    _qlrps(fmhz, 0.0, ens, pol, eps, sgm)


def lrProfile(dist, pfl, climate=5, mdVar=12):
    """Analyze a terrain profile for ITM computation.

    Must be called after lrPrep() and before lrProp().

    Args:
        dist: Path distance in meters
        pfl: Terrain profile array [n_points, step_dist, elev0, ..., elevN]
        climate: Radio climate (1-7):
            1=Equatorial, 2=Continental subtropical, 3=Maritime subtropical,
            4=Desert, 5=Continental temperate, 6=Maritime temperate over land,
            7=Maritime temperate over sea
        mdVar: Mode of variability:
            0=single message, 1=individual, 2=mobile, 3=broadcast
            Add 10 for "all" mode (e.g., 12 = individual with all variabilities)
    """
    _qlrpfl(pfl, climate, mdVar)


def lrProp(dist):
    """Compute propagation for a given distance.

    Must be called after lrProfile(). Can be called multiple times
    for different distances along the same profile.

    Args:
        dist: Distance in meters
    """
    _lrprop(dist)


def aVar(zt, zl, zc):
    """Get total path loss including variability.

    Must be called after lrProp().

    Args:
        zt: Time variability z-score (0 for median)
        zl: Location variability z-score (0 for median)
        zc: Confidence variability z-score (0 for median)

    Returns:
        Total path loss in dB (including free space)
    """
    return _avar(zt, zl, zc)


def point_to_point(pfl, hg, fmhz=915.0, ens=301.0, pol=1, eps=15.0, sgm=0.005,
                   climate=5, mdvar=12, pct_time=50.0, pct_loc=50.0, pct_conf=50.0):
    """Complete point-to-point ITM calculation in one call.

    Convenience function that calls lrPrep, lrProfile, lrProp, and aVar.

    Args:
        pfl: Terrain profile [n_points, step_dist, elev0, ..., elevN]
        hg: Antenna heights [tx, rx] above ground (meters)
        fmhz: Frequency in MHz
        ens: Surface refractivity N-units
        pol: Polarization (0=horiz, 1=vert)
        eps: Ground dielectric constant
        sgm: Ground conductivity S/m
        climate: Radio climate (1-7)
        mdvar: Variability mode
        pct_time: Percent time reliability (1-99)
        pct_loc: Percent location reliability (1-99)
        pct_conf: Percent confidence (1-99)

    Returns:
        dict with path_loss_db, mode, delta_h, etc.
    """
    lrPrep(fmhz, hg, ens, pol, eps, sgm)

    dist = pfl[0] * pfl[1]  # n_points * step = total distance
    lrProfile(dist, pfl, climate, mdvar)
    lrProp(dist)

    zt = _norm_quantile(pct_time / 100.0)
    zl = _norm_quantile(pct_loc / 100.0)
    zc = _norm_quantile(pct_conf / 100.0)

    total_loss = aVar(zt, zl, zc)

    # Determine mode
    mdp = _prop['mdp']
    if mdp == -1:
        mode = 'line_of_sight'
    elif mdp == 0:
        mode = 'diffraction'
    else:
        mode = 'troposcatter'

    return {
        'path_loss_db': round(total_loss, 1),
        'mode': mode,
        'delta_h': round(_prop['dh'], 1),
        'he': [round(_prop['he'][0], 1), round(_prop['he'][1], 1)],
        'dl': [round(_prop['dl'][0], 0), round(_prop['dl'][1], 0)],
        'the': [round(math.degrees(_prop['the'][0]), 3), round(math.degrees(_prop['the'][1]), 3)],
        'kwx': _prop['kwx'],
    }


def _norm_quantile(p):
    """Inverse normal CDF (quantile function) - rational approximation.

    Uses Abramowitz and Stegun 26.2.23 approximation.
    Accurate to ~4.5e-4 in the range 0.0002 < p < 0.9998.
    """
    if p <= 0.0:
        return -5.0
    if p >= 1.0:
        return 5.0
    if abs(p - 0.5) < 1e-10:
        return 0.0

    if p < 0.5:
        t = math.sqrt(-2.0 * math.log(p))
    else:
        t = math.sqrt(-2.0 * math.log(1.0 - p))

    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308

    result = t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)

    if p < 0.5:
        return -result
    return result
