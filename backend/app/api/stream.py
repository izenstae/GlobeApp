"""Server-Sent Events endpoint. One-directional flow, free reconnects.

The backend publishes to a Redis channel when a new cluster is created or an
existing cluster grows materially; this endpoint fans that channel out to
browsers. Each message carries the full event payload."""

import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from redis.asyncio import Redis
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stream"])

HEARTBEAT_SECONDS = 15


@router.get("/stream/events")
async def stream_events(request: Request) -> EventSourceResponse:
    async def generator() -> AsyncIterator[dict[str, Any]]:
        redis = Redis.from_url(get_settings().redis_url)
        pubsub = redis.pubsub()
        await pubsub.subscribe(get_settings().sse_redis_channel)
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=HEARTBEAT_SECONDS
                )
                if message is None:
                    yield {"event": "heartbeat", "data": ""}
                    continue
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                yield {"event": "conflict_event", "data": data}
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()
            await redis.aclose()

    return EventSourceResponse(generator())
