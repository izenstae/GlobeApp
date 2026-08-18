"""Upsert normalized events. Insert-or-update on (source, source_event_id):
sources revise records after publication, so re-pulling a window and upserting
is the correct behavior.
"""

import logging
from typing import Any

from sqlalchemy import literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event
from app.pipeline.normalize import UnifiedEvent

logger = logging.getLogger(__name__)


def _row(ev: UnifiedEvent) -> dict[str, Any]:
    return {
        "source": ev.source,
        "source_event_id": ev.source_event_id,
        "occurred_at": ev.occurred_at,
        "geom": f"SRID=4326;POINT({ev.lon} {ev.lat})",
        "geo_precision": ev.geo_precision,
        "geo_radius_m": ev.geo_radius_m,
        "country": ev.country,
        "admin1": ev.admin1,
        "location_name": ev.location_name,
        "category": ev.category,
        "raw_event_type": ev.raw_event_type,
        "actor_a": ev.actor_a,
        "actor_b": ev.actor_b,
        "fatalities": ev.fatalities,
        "headline": ev.headline,
        "notes": ev.notes,
        "source_urls": ev.source_urls,
        "raw_payload": ev.raw_payload,
    }


async def upsert_events(session: AsyncSession, events: list[UnifiedEvent]) -> list[int]:
    """Upsert a batch; returns ids of newly inserted (not merely updated) events."""
    new_ids: list[int] = []
    for ev in events:
        stmt = pg_insert(Event).values(**_row(ev))
        update_cols = {
            c: getattr(stmt.excluded, c)
            for c in (
                "occurred_at",
                "geom",
                "geo_precision",
                "geo_radius_m",
                "country",
                "admin1",
                "location_name",
                "category",
                "raw_event_type",
                "actor_a",
                "actor_b",
                "fatalities",
                "headline",
                "notes",
                "source_urls",
                "raw_payload",
            )
        }
        upsert: Any = stmt.on_conflict_do_update(
            index_elements=["source", "source_event_id"], set_=update_cols
        ).returning(Event.id, literal_column("(xmax = 0)").label("inserted"))
        row = (await session.execute(upsert)).one()
        if row.inserted:
            new_ids.append(row.id)
    return new_ids
