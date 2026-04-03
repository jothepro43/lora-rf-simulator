# Stage 1: Build frontend
FROM node:20-slim AS frontend-build
RUN corepack enable && corepack prepare pnpm@9 --activate
WORKDIR /app/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN pnpm install --no-frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# Stage 2: Backend + serve frontend
FROM python:3.12-slim

# Install system dependencies for rasterio/GDAL
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./

# Copy built frontend to static dir
COPY --from=frontend-build /app/frontend/dist ./static

# Create directories
RUN mkdir -p srtm_cache data

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
