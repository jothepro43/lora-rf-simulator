"""Full link budget calculator."""

import math
import json
import os


def load_json_catalog(filename: str) -> dict:
    """Load a JSON data catalog file."""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    path = os.path.join(data_dir, filename)
    with open(path) as f:
        return json.load(f)


def compute_cable_loss(cable_type: str, length_m: float, connectors: int = 0) -> float:
    """Compute total cable/feeder loss in dB."""
    cables = load_json_catalog("cables.json")
    cable = cables.get(cable_type, cables.get("ideal", {}))
    loss_per_m = cable.get("loss_db_per_meter", 0.0)
    connector_loss = cable.get("connector_loss_db", 0.5) * connectors
    return loss_per_m * length_m + connector_loss


def compute_link_budget(
    tx_power_dbm: float,
    tx_gain_dbi: float,
    cable_type: str,
    cable_length_m: float,
    connectors: int,
    rx_gain_dbi: float,
    rx_sensitivity_dbm: float,
    path_loss_db: float,
    diffraction_db: float = 0.0,
    weather_db: float = 0.0,
    misc_loss_db: float = 0.0,
) -> dict:
    """Compute full link budget from TX to RX.

    Returns a detailed breakdown of all gains and losses.
    """
    cable_loss = compute_cable_loss(cable_type, cable_length_m, connectors)

    # Effective Radiated Power
    erp_dbm = tx_power_dbm - cable_loss + tx_gain_dbi - 2.15  # ERP relative to dipole
    eirp_dbm = tx_power_dbm - cable_loss + tx_gain_dbi  # EIRP relative to isotropic

    # Total path loss
    total_path_loss = path_loss_db + diffraction_db + weather_db + misc_loss_db

    # Received power
    rx_power_dbm = eirp_dbm - total_path_loss + rx_gain_dbi

    # System margin
    margin_db = rx_power_dbm - rx_sensitivity_dbm

    # Efficiency
    tx_power_w = 10 ** (tx_power_dbm / 10) / 1000
    erp_w = 10 ** (erp_dbm / 10) / 1000
    eirp_w = 10 ** (eirp_dbm / 10) / 1000

    return {
        "tx_power_dbm": round(tx_power_dbm, 1),
        "tx_power_w": round(tx_power_w, 4),
        "cable_loss_db": round(cable_loss, 2),
        "tx_gain_dbi": round(tx_gain_dbi, 1),
        "erp_dbm": round(erp_dbm, 1),
        "erp_w": round(erp_w, 4),
        "eirp_dbm": round(eirp_dbm, 1),
        "eirp_w": round(eirp_w, 4),
        "fspl_db": round(path_loss_db, 1),
        "diffraction_db": round(diffraction_db, 1),
        "weather_db": round(weather_db, 1),
        "misc_loss_db": round(misc_loss_db, 1),
        "total_path_loss_db": round(total_path_loss, 1),
        "rx_gain_dbi": round(rx_gain_dbi, 1),
        "rx_power_dbm": round(rx_power_dbm, 1),
        "rx_sensitivity_dbm": round(rx_sensitivity_dbm, 1),
        "margin_db": round(margin_db, 1),
        "link_viable": margin_db >= 0,
    }
