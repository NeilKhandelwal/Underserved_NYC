# ── Stage 1: Build frontend ──────────────────────────────────────────────────
FROM node:22-slim AS frontend

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# ── Stage 2: Build serving bundle ─────────────
FROM python:3.13-slim AS bundle

RUN apt-get update && \
    apt-get install -y --no-install-recommends tippecanoe && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY scripts/ ./scripts/
COPY output/ ./output/
RUN python scripts/build_serving_bundle.py


# ── Stage 3: Production image ────────────────────────────────────────────────
FROM python:3.13-slim AS production

WORKDIR /app

COPY requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements-api.txt

COPY api/ ./api/
COPY --from=frontend /app/frontend/dist ./frontend/dist
COPY --from=bundle /app/serving/ ./serving/

EXPOSE 8080

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
