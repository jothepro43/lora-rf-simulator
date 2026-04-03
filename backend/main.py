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


# Data catalog endpoints
@app.get("/api/data/devices")
def get_devices():
    data_dir = Path(__file__).parent / "data"
    with open(data_dir / "devices.json") as f:
        return json.load(f)


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
