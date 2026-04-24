"""Liveness endpoint — exposes Mongo status (§15)."""

from __future__ import annotations

from fastapi import APIRouter, Response

from utils.mongo import ping

router = APIRouter()


@router.get("/health")
async def health(response: Response) -> dict[str, str]:
    """Return process + Mongo liveness. 200 when healthy, 503 if Mongo is down."""
    mongo_ok = await ping()
    if not mongo_ok:
        response.status_code = 503
    return {
        "status": "ok" if mongo_ok else "degraded",
        "mongo": "connected" if mongo_ok else "down",
        "version": "0.1.0",
    }
