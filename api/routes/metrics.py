"""Prometheus scrape endpoint (§15).

Uses the default registry so later phases (Phase 5 deploys_total,
Phase 10 llm_tokens_total, etc.) register counters against the same one.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter()


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
