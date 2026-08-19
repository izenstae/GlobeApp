"""Event serialization and Redis fanout for the SSE stream.

Each published message carries the full event payload so the frontend card can
render without a follow-up fetch.
"""

import json
import logging
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Event, EventCluster
from app.pipeline.reliability import explain_cluster

logger = logging.getLogger(__name__)


async def serialize_event(session: AsyncSession, event_id: int) -> dict[str, Any] | None:
    event = await session.get(Event, event_id)
    if event is None:
        return None
    row = (
        await session.execute(
            text("SELECT ST_Y(geom::geometry), ST_X(geom::geometry) FROM events WHERE id = :id"),
            {"id": event_id},
        )
    ).one()
    lat, lon = row

    cluster: EventCluster | None = None
    members: list[Event] = []
    if event.cluster_id is not None:
        cluster = await session.get(EventCluster, event.cluster_id)
        member_ids = (
            (
                await session.execute(
                    text("SELECT id FROM events WHERE cluster_id = :c"),
                    {"c": event.cluster_id},
                )
            )
            .scalars()
            .all()
        )
        members = [e for m in member_ids if (e := await session.get(Event, m)) is not None]

    source_urls: list[str] = []
    seen = set()
    for member in members or [event]:
        for url in member.source_urls or []:
            if url not in seen:
                seen.add(url)
                source_urls.append(url)

    return {
        "id": event.id,
        "cluster_id": event.cluster_id,
        "source": event.source,
        "sources": sorted({m.source for m in members} | {event.source}),
        "occurred_at": event.occurred_at.isoformat(),
        "ingested_at": event.ingested_at.isoformat() if event.ingested_at else None,
        "lat": lat,
        "lon": lon,
        "geo_precision": event.geo_precision,
        "geo_radius_m": event.geo_radius_m,
        "country": event.country,
        "admin1": event.admin1,
        "location_name": event.location_name,
        "category": event.category,
        "raw_event_type": event.raw_event_type,
        "actor_a": event.actor_a,
        "actor_b": event.actor_b,
        "actor_a_canonical": event.actor_a_canonical,
        "actor_b_canonical": event.actor_b_canonical,
        "fatalities": event.fatalities,
        "headline": event.headline,
        "notes": event.notes,
        "source_urls": source_urls,
        "source_count": (cluster.member_count if cluster else event.source_count),
        "reliability": (cluster.reliability if cluster else event.reliability),
        "reliability_explanation": (
            explain_cluster(cluster, members) if cluster and members else None
        ),
        "thermal_corroborated": bool(cluster.thermal_corroborated) if cluster else False,
        "weapons": [
            {
                "weapon_key": w.weapon_key,
                "display_name": w.display_name,
                "category": w.category,
                "confidence": w.confidence,
                "method": w.method,
                "evidence_span": w.evidence_span,
            }
            for w in event.weapons
        ],
    }


async def publish_new_event(session: AsyncSession, redis: Redis | None, event_id: int) -> None:
    if redis is None:
        return
    payload = await serialize_event(session, event_id)
    if payload is None:
        return
    try:
        await redis.publish(get_settings().sse_redis_channel, json.dumps(payload))
    except Exception:
        # Fanout failure must not fail ingestion; the event is already stored.
        logger.exception("redis publish failed for event %d", event_id)
