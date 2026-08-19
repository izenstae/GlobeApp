"""FIRMS thermal corroboration.

A FIRMS hotspot is a heat signature — maybe a strike, maybe a wildfire or gas
flare. Hotspots are NEVER promoted to events. Their one analytic job: if a
hotspot falls within 5km and 6 hours of a reported kinetic event, that event's
cluster gains thermal corroboration and a reliability bump.

ACLED and GDELT date their events to the day (midnight UTC timestamps), so for
those rows the 6-hour rule is applied against the event's reported calendar
day, padded 6 hours each side. Anything tighter would silently disable the
feature for day-granular sources.
"""

import logging

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, EventCluster
from app.pipeline.reliability import score_cluster

logger = logging.getLogger(__name__)

KINETIC_CATEGORIES = (
    "airstrike",
    "artillery",
    "drone_strike",
    "missile_strike",
    "ied",
    "naval",
    "ground_assault",
)

MATCH_RADIUS_M = 5_000
MATCH_WINDOW = "interval '6 hours'"
DAY_WINDOW_PAD = "interval '6 hours'"


async def corroborate_clusters(session: AsyncSession) -> int:
    """Match hotspots against kinetic events; mark and rescore affected clusters.
    Returns the number of newly corroborated clusters."""
    rows = (
        await session.execute(
            text(
                f"""
                SELECT DISTINCT e.cluster_id
                FROM events e
                JOIN event_clusters c ON c.id = e.cluster_id
                JOIN firms_hotspots h
                  ON ST_DWithin(e.geom, h.geom, :radius)
                 AND (
                     CASE WHEN e.occurred_at::time = '00:00'
                          -- day-granular source: match anywhere in the reported day
                          THEN h.acquired_at BETWEEN e.occurred_at - {DAY_WINDOW_PAD}
                               AND e.occurred_at + interval '24 hours' + {DAY_WINDOW_PAD}
                          ELSE h.acquired_at BETWEEN e.occurred_at - {MATCH_WINDOW}
                               AND e.occurred_at + {MATCH_WINDOW}
                     END
                 )
                WHERE e.category IN :categories
                  AND NOT c.thermal_corroborated
                """
            ).bindparams(bindparam("categories", expanding=True)),
            {"radius": MATCH_RADIUS_M, "categories": list(KINETIC_CATEGORIES)},
        )
    ).all()

    count = 0
    for (cluster_id,) in rows:
        cluster = await session.get(EventCluster, cluster_id)
        if cluster is None or cluster.thermal_corroborated:
            continue
        cluster.thermal_corroborated = True
        member_ids = (
            (
                await session.execute(
                    text("SELECT id FROM events WHERE cluster_id = :c"), {"c": cluster_id}
                )
            )
            .scalars()
            .all()
        )
        members = [e for m in member_ids if (e := await session.get(Event, m)) is not None]
        cluster.reliability = await score_cluster(session, cluster, members)
        if cluster.representative is not None:
            rep = await session.get(Event, cluster.representative)
            if rep is not None:
                rep.reliability = cluster.reliability
        count += 1
    if count:
        logger.info("thermal corroboration: %d clusters newly corroborated", count)
    return count
