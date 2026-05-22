from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import PROJECT_ROOT, get_settings
from .routers import analytics, predict, tracts, watchlist
from .schemas import HealthResponse
from .store import store

logger = logging.getLogger("underserved.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Loading serving bundle from %s", settings.serving_dir)
    store.load(settings.serving_dir)
    logger.info("Loaded %d tracts; model ready=%s", len(store.tracts), store.model is not None)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.title,
        version=settings.version,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(tracts.router, prefix="/api")
    app.include_router(watchlist.router, prefix="/api")
    app.include_router(analytics.router, prefix="/api")
    app.include_router(predict.router, prefix="/api")

    # Vector tiles (PMTiles) served as static files. StaticFiles handles the
    # HTTP Range requests the pmtiles protocol needs.
    tiles_dir = settings.serving_dir.parent / "tiles"
    if tiles_dir.is_dir():
        app.mount("/tiles", StaticFiles(directory=tiles_dir), name="tiles")
    else:
        logger.warning("tiles dir %s missing — run `make serving-bundle`", tiles_dir)

    @app.get("/healthz", response_model=HealthResponse, tags=["meta"])
    def healthz():
        return {
            "status": "ok" if store.loaded else "loading",
            "tracts": len(store.tracts),
            "model_loaded": store.model is not None,
        }

    # Built SPA (frontend/dist) — mounted LAST so it never shadows /api,
    # /tiles, or /healthz. Absent in dev (run Vite); present in prod images.
    dist_dir = PROJECT_ROOT / "frontend" / "dist"
    if dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")

    return app


app = create_app()
