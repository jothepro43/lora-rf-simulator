"""Unit tests for RF propagation primitives and `compute_path_loss` modes."""

import math

import pytest

from services.propagation import (
    SUPPORTED_PATH_LOSS_MODELS,
    compute_path_loss,
    fspl,
    fresnel_radius,
    haversine_distance,
)


def _flat_profile(distance_m: float, n: int = 32) -> tuple[list[float], list[float]]:
    distances = [i * (distance_m / (n - 1)) for i in range(n)]
    elevations = [100.0] * n  # flat terrain at 100m ASL
    return distances, elevations


def test_fspl_zero_distance_is_zero():
    assert fspl(0.0, 915.0) == 0.0


def test_fspl_doubles_with_decade_distance():
    """FSPL adds 20 dB per decade of distance."""
    a = fspl(1_000.0, 915.0)
    b = fspl(10_000.0, 915.0)
    assert pytest.approx(b - a, abs=0.05) == 20.0


def test_haversine_short_distance_matches_planar():
    """Within a few meters the haversine result should match a flat-earth approximation."""
    # ~111 m per deg of lat at equator
    d = haversine_distance(0.0, 0.0, 0.001, 0.0)
    assert 110.0 < d < 112.0


def test_fresnel_radius_positive_at_midpoint():
    r = fresnel_radius(1, 10_000.0, 5_000.0, 915.0)
    assert r > 0
    # Outside the path should clamp to zero.
    assert fresnel_radius(1, 10_000.0, 0.0, 915.0) == 0.0


def test_compute_path_loss_rejects_unknown_model():
    distances, elevations = _flat_profile(5_000.0)
    with pytest.raises(ValueError):
        compute_path_loss(distances, elevations, 10.0, 1.5, model="bogus")


def test_compute_path_loss_fspl_only_has_no_diffraction_or_weather():
    distances, elevations = _flat_profile(5_000.0)
    out = compute_path_loss(
        distances, elevations, 10.0, 1.5, model="fspl"
    )
    assert out["diffraction_db"] == 0.0
    assert out["weather_db"] == 0.0
    assert out["clutter_db"] == 0.0
    assert out["model"] == "fspl"


def test_compute_path_loss_fspl_diffraction_keeps_weather_off():
    distances, elevations = _flat_profile(5_000.0)
    out = compute_path_loss(
        distances, elevations, 10.0, 1.5,
        model="fspl_diffraction",
        rain_rate_mmh=200.0,
    )
    assert out["weather_db"] == 0.0


def test_compute_path_loss_fspl_weather_skips_diffraction():
    distances, elevations = _flat_profile(5_000.0)
    out = compute_path_loss(
        distances, elevations, 10.0, 1.5,
        model="fspl_weather",
        rain_rate_mmh=50.0,
    )
    assert out["diffraction_db"] == 0.0


def test_compute_path_loss_full_with_clutter_increases_loss():
    distances, elevations = _flat_profile(10_000.0)
    base = compute_path_loss(
        distances, elevations, 10.0, 1.5, model="full"
    )
    forested = compute_path_loss(
        distances, elevations, 10.0, 1.5,
        model="full",
        clutter_profile="dense_forest",
    )
    assert forested["clutter_db"] > 0
    assert forested["total_path_loss_db"] >= base["total_path_loss_db"]


def test_compute_path_loss_open_clutter_adds_zero():
    distances, elevations = _flat_profile(5_000.0)
    out = compute_path_loss(
        distances, elevations, 10.0, 1.5,
        model="full",
        clutter_profile="open",
    )
    assert out["clutter_db"] == 0.0


def test_compute_path_loss_monotonic_with_distance():
    """Doubling the path length must not decrease total loss in flat-terrain FSPL."""
    short_d, short_e = _flat_profile(1_000.0)
    long_d, long_e = _flat_profile(2_000.0)
    short = compute_path_loss(short_d, short_e, 10.0, 1.5, model="fspl")
    long_ = compute_path_loss(long_d, long_e, 10.0, 1.5, model="fspl")
    assert long_["total_path_loss_db"] > short["total_path_loss_db"]


def test_supported_models_includes_full():
    assert "full" in SUPPORTED_PATH_LOSS_MODELS
    assert "fspl" in SUPPORTED_PATH_LOSS_MODELS
