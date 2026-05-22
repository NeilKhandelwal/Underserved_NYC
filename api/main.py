from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
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

    @app.get("/healthz", response_model=HealthResponse, tags=["meta"])
    def healthz():
        return {
            "status": "ok" if store.loaded else "loading",
            "tracts": len(store.tracts),
            "model_loaded": store.model is not None,
        }

    return app


app = create_app()
