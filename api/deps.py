from __future__ import annotations

from fastapi import HTTPException

from .store import DataStore, store


def get_store() -> DataStore:
    if not store.loaded:
        raise HTTPException(status_code=503, detail="data store not loaded")
    return store
