from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Credential, IngestWatermark

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    await session.execute(select(1))
    return {"status": "ok", "time": datetime.now(UTC).isoformat()}


@router.get("/health/feeds")
async def health_feeds(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Per-feed ingest health and credential status. Failed feeds surface here,
    never silently."""
    watermarks = (await session.execute(select(IngestWatermark))).scalars().all()
    credentials = (await session.execute(select(Credential))).scalars().all()
    cred_by_provider = {c.provider: c for c in credentials}

    feeds = []
    for wm in watermarks:
        cred = cred_by_provider.get(wm.source)
        feeds.append(
            {
                "source": wm.source,
                "watermark": wm.watermark.isoformat() if wm.watermark else None,
                "last_success_at": wm.last_success_at.isoformat() if wm.last_success_at else None,
                "last_attempt_at": wm.last_attempt_at.isoformat() if wm.last_attempt_at else None,
                "last_error": wm.last_error,
                "consecutive_failures": wm.consecutive_failures,
                "records_ingested": wm.records_ingested,
                "credential_status": cred.status if cred else None,
            }
        )
    # Credentials with no ingest history yet (e.g. just registered) still show up.
    seen = {f["source"] for f in feeds}
    for c in credentials:
        if c.provider not in seen:
            feeds.append(
                {
                    "source": c.provider,
                    "watermark": None,
                    "last_success_at": None,
                    "last_attempt_at": None,
                    "last_error": None,
                    "consecutive_failures": 0,
                    "records_ingested": 0,
                    "credential_status": c.status,
                }
            )
    return {"feeds": feeds}
