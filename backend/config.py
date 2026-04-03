import os

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "info")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/nodes.db")
SRTM_CACHE_DIR = os.getenv("SRTM_CACHE_DIR", "./srtm_cache")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", '["http://localhost:5173","http://localhost:8000"]')
