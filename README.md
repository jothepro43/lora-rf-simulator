# LoRa RF Simulator

An open-source, self-hostable LoRa RF propagation simulator focused on **Meshtastic** and **MeshCore** devices. Combines real terrain data (NASA SRTM) with propagation modeling to predict RF coverage, line-of-sight paths, and link budgets.

## Features

- **Interactive Map** — Dark-themed Leaflet map with click-to-place TX/RX nodes
- **Real Terrain Data** — NASA SRTM elevation data, auto-downloaded and cached
- **Propagation Models** — Free Space Path Loss, knife-edge diffraction (Deygout 94), Fresnel zone analysis, earth curvature
- **Line-of-Sight Profiles** — Terrain cross-section between any two points with Fresnel zone visualization
- **Coverage Heatmaps** — Signal strength overlay at configurable resolution
- **Link Budget Calculator** — Full TX-to-RX power analysis with cable loss, antenna gain, and path loss
- **Device Presets** — Pre-configured Meshtastic/MeshCore devices (RAK, LILYGO, Heltec, Station G1, and more)
- **Antenna Catalog** — Real antenna specs (Rokland, ALFA, stock antennas) with gain and beamwidth data
- **Cable Loss Data** — LMR-400, LMR-600, RG-58, and more at 915 MHz
- **Meshtastic Channel Presets** — SF/BW configurations with sensitivity values
- **Node Database** — SQLite storage for placed nodes with full configuration
- **Dark Theme** — Professional dark UI inspired by CloudRF
- **Docker Deployment** — Single `docker-compose up` to run everything

## Quick Start

### Docker (Recommended)

```bash
cp .env.example .env
docker-compose up --build
```

Open http://localhost:8000 in your browser.

### Development

**Backend:**
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend:**
```bash
cd frontend
pnpm install
pnpm dev
```

## Architecture

- **Frontend**: Vue 3 + TypeScript + Vite + Leaflet.js
- **Backend**: Python FastAPI + uvicorn
- **Terrain**: NASA SRTM tiles via srtm4/rasterio (auto-downloaded, cached)
- **Database**: SQLite via SQLAlchemy
- **Deployment**: Docker + docker-compose

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/terrain/elevation` | Single point elevation |
| POST | `/api/terrain/profile` | Terrain profile between two points |
| GET | `/api/nodes` | List all nodes |
| POST | `/api/nodes` | Create a node |
| PUT | `/api/nodes/{id}` | Update a node |
| DELETE | `/api/nodes/{id}` | Delete a node |
| POST | `/api/simulate/coverage` | Generate coverage heatmap |
| POST | `/api/simulate/los` | Line-of-sight analysis |
| POST | `/api/simulate/link-budget` | Full link budget calculation |

## Supported Devices

| Device | TX Power | Radio | RX Sensitivity |
|--------|----------|-------|----------------|
| RAK4631 (WisBlock) | 22 dBm | SX1262 | -148 dBm |
| RAK19003 WisMesh Pocket | 22 dBm | SX1262 | -148 dBm |
| LILYGO T-Beam v1.1 | 22 dBm | SX1276 | -136 dBm |
| LILYGO T-Beam Supreme | 22 dBm | SX1262 | -148 dBm |
| LILYGO T-Echo | 22 dBm | SX1262 | -148 dBm |
| Heltec LoRa V3 | 22 dBm | SX1262 | -136 dBm |
| Heltec LoRa V4 | 28 dBm | SX1262+PA | -136 dBm |
| Station G1 (B&Q) | 35 dBm | SX1262+PA | -148 dBm |
| Luckfox Ultra Hat 1W | 30 dBm | E22-900M30S | -148 dBm |
| Luckfox Ultra Hat 2W | 33 dBm | E22-900M33S | -148 dBm |
| NULLHOP MeshToad V4 | 22 dBm | SX1262 | -148 dBm |
| T1000-E Tracker | 22 dBm | SX1262 | -148 dBm |

## License

MIT
