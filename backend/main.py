"""LoRa RF Simulator — FastAPI Backend."""

import json
import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from models.database import init_db
from api.nodes import router as nodes_router
from api.simulate import router as simulate_router
from api.terrain import router as terrain_router
from api.export import router as export_router
from api.mqtt import router as mqtt_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    init_db()
    logger.info("LoRa RF Simulator backend ready")
    yield


app = FastAPI(
    title="LoRa RF Simulator",
    description="RF propagation simulator for Meshtastic/MeshCore LoRa devices",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
cors_origins = json.loads(os.getenv(
    "CORS_ORIGINS",
    '["http://localhost:5173","http://localhost:8000","http://localhost:3000"]'
))
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(nodes_router)
app.include_router(simulate_router)
app.include_router(terrain_router)
app.include_router(export_router)
app.include_router(mqtt_router)


CUSTOM_DEVICES_PATH = Path(__file__).parent / "data" / "custom_devices.json"


def _load_custom_devices() -> dict:
    if CUSTOM_DEVICES_PATH.exists():
        with open(CUSTOM_DEVICES_PATH) as f:
            return json.load(f)
    return {}


def _save_custom_devices(data: dict):
    with open(CUSTOM_DEVICES_PATH, "w") as f:
        json.dump(data, f, indent=2)


# Data catalog endpoints
@app.get("/api/data/devices")
def get_devices():
    data_dir = Path(__file__).parent / "data"
    with open(data_dir / "devices.json") as f:
        builtin = json.load(f)
    custom = _load_custom_devices()
    return {**builtin, **custom}


@app.post("/api/data/devices/custom")
def add_custom_device(device: dict):
    """Add a custom device to the custom_devices.json file."""
    custom = _load_custom_devices()
    # Generate a key from the device name
    key = "custom_" + device.get("name", "device").lower().replace(" ", "_").replace("-", "_")
    # Ensure unique key
    base_key = key
    counter = 1
    while key in custom:
        key = f"{base_key}_{counter}"
        counter += 1

    custom[key] = {
        "name": device.get("name", "Custom Device"),
        "manufacturer": device.get("manufacturer", "Custom"),
        "radio": device.get("radio", "SX1262"),
        "tx_power_dbm": device.get("tx_power_dbm", 22),
        "rx_sensitivity_dbm": device.get("rx_sensitivity_dbm", -148),
        "frequency_range": "863-928 MHz",
        "connector": device.get("connector", "SMA"),
        "power_consumption_tx_ma": 0,
        "power_consumption_rx_ma": 0,
        "protocols": ["LoRa"],
        "notes": device.get("notes", ""),
        "custom": True,
    }
    _save_custom_devices(custom)
    return {"key": key, "device": custom[key]}


@app.put("/api/data/devices/custom/{key}")
def update_custom_device(key: str, device: dict):
    """Update an existing custom device."""
    custom = _load_custom_devices()
    if key not in custom:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Custom device '{key}' not found")
    custom[key] = {
        "name": device.get("name", custom[key].get("name", "Custom Device")),
        "manufacturer": device.get("manufacturer", custom[key].get("manufacturer", "Custom")),
        "radio": device.get("radio", custom[key].get("radio", "SX1262")),
        "tx_power_dbm": device.get("tx_power_dbm", custom[key].get("tx_power_dbm", 22)),
        "rx_sensitivity_dbm": device.get("rx_sensitivity_dbm", custom[key].get("rx_sensitivity_dbm", -148)),
        "frequency_range": "863-928 MHz",
        "connector": device.get("connector", custom[key].get("connector", "SMA")),
        "power_consumption_tx_ma": 0,
        "power_consumption_rx_ma": 0,
        "protocols": ["LoRa"],
        "notes": device.get("notes", custom[key].get("notes", "")),
        "custom": True,
    }
    _save_custom_devices(custom)
    return {"key": key, "device": custom[key]}


@app.delete("/api/data/devices/custom/{key}")
def delete_custom_device(key: str):
    """Remove a custom device."""
    custom = _load_custom_devices()
    if key not in custom:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Custom device '{key}' not found")
    del custom[key]
    _save_custom_devices(custom)
    return {"detail": f"Deleted custom device '{key}'"}


@app.get("/api/data/antennas")
def get_antennas():
    data_dir = Path(__file__).parent / "data"
    with open(data_dir / "antennas.json") as f:
        return json.load(f)


@app.get("/api/data/cables")
def get_cables():
    data_dir = Path(__file__).parent / "data"
    with open(data_dir / "cables.json") as f:
        return json.load(f)


@app.get("/api/data/channels")
def get_channels():
    data_dir = Path(__file__).parent / "data"
    with open(data_dir / "channels.json") as f:
        return json.load(f)


# Serve frontend static files
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = STATIC_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(STATIC_DIR / "index.html"))
