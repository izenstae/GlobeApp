"""Spatial-temporal-textual clustering at ingest, not at query time.

Two events join the same cluster when ALL of:
  1. great-circle distance < max(10km, geo_radius_m of the less precise event)
  2. occurred_at within 6 hours
  3. categories compatible (compatibility matrix, not string equality)
  4. token-set text similarity of headline+notes > 0.55, OR both actor pairs
     match after canonicalization
"""

import logging
from datetime import timedelta

from rapidfuzz import fuzz
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, EventCluster

logger = logging.getLogger(__name__)

TIME_WINDOW = timedelta(hours=6)
BASE_RADIUS_M = 10_000
TEXT_SIMILARITY_THRESHOLD = 55.0  # rapidfuzz token_set_ratio is 0..100

# Compatibility groups: membership in a shared group makes two categories
# compatible. A category may appear in several groups.
_COMPAT_GROUPS: list[set[str]] = [
    {"airstrike", "drone_strike", "missile_strike", "artillery"},  # remote strikes
    {"ied", "other_violence"},
    {"ground_assault", "small_arms", "other_violence"},
    {"protest", "riot"},
    {"abduction", "other_violence"},
    {"naval", "missile_strike"},
]


def categories_compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    return any(a in group and b in group for group in _COMPAT_GROUPS)


def _actor_pair(event: Event) -> frozenset[str] | None:
    names = []
    for raw, canonical in (
        (event.actor_a, event.actor_a_canonical),
        (event.actor_b, event.actor_b_canonical),
    ):
        name = (canonical or raw or "").strip().lower()
        if name:
            names.append(name)
    if not names:
        return None
    return frozenset(names)


def _event_text(event: Event) -> str:
    return " ".join(part for part in (event.headline, event.notes) if part).strip()


def events_match(a: Event, b: Event, distance_m: float) -> bool:
    """Conditions 1, 3, 4 (2 is enforced by the candidate query)."""
    radius_limit = max(BASE_RADIUS_M, max(a.geo_radius_m or 0, b.geo_radius_m or 0))
    if distance_m > radius_limit:
        return False
    if not categories_compatible(a.category, b.category):
        return False

    text_a, text_b = _event_text(a), _event_text(b)
    if text_a and text_b:
        if fuzz.token_set_ratio(text_a.lower(), text_b.lower()) > TEXT_SIMILARITY_THRESHOLD:
            return True
    pair_a, pair_b = _actor_pair(a), _actor_pair(b)
    return pair_a is not None and pair_a == pair_b


# Source tier for representative selection; ACLED is the curated source and
# stays canonical (its actor names are the vocabulary); UCDP just below it.
SOURCE_TIER = {"acled": 1.0, "ucdp": 0.9, "gdelt": 0.4, "firms": 0.0}


def _member_rank(member: Event) -> tuple[float, float]:
    tier = SOURCE_TIER.get(member.source, 0.2)
    # Higher tier first, then earliest report.
    return (tier, -member.occurred_at.timestamp())


async def assign_cluster(session: AsyncSession, event: Event) -> int:
    """Attach `event` to a matching cluster or create a singleton. Returns cluster id."""
    candidates = (
        await session.execute(
            text(
                """
                SELECT id,
                       ST_Distance(geom, (SELECT geom FROM events WHERE id = :event_id)) AS dist_m
                FROM events
                WHERE id != :event_id
                  AND cluster_id IS NOT NULL
                  AND occurred_at BETWEEN :t_from AND :t_to
                  AND ST_DWithin(
                        geom,
                        (SELECT geom FROM events WHERE id = :event_id),
                        GREATEST(:base_radius, COALESCE(geo_radius_m, 0), :event_radius)
                      )
                ORDER BY dist_m
                LIMIT 50
                """
            ),
            {
                "event_id": event.id,
                "t_from": event.occurred_at - TIME_WINDOW,
                "t_to": event.occurred_at + TIME_WINDOW,
                "base_radius": BASE_RADIUS_M,
                "event_radius": event.geo_radius_m or 0,
            },
        )
    ).all()

    for candidate_id, dist_m in candidates:
        candidate = await session.get(Event, candidate_id)
        if candidate is None or candidate.cluster_id is None:
            continue
        if events_match(event, candidate, dist_m):
            event.cluster_id = candidate.cluster_id
            await _refresh_cluster(session, candidate.cluster_id)
            return candidate.cluster_id

    cluster = EventCluster(
        representative=event.id,
        first_seen=event.occurred_at,
        last_seen=event.occurred_at,
        member_count=1,
        centroid=f"SRID=4326;POINT({await _lon(session, event)} {await _lat(session, event)})",
    )
    session.add(cluster)
    await session.flush()
    event.cluster_id = cluster.id
    return cluster.id


async def _lat(session: AsyncSession, event: Event) -> float:
    return (
        await session.execute(
            text("SELECT ST_Y(geom::geometry) FROM events WHERE id = :id"), {"id": event.id}
        )
    ).scalar_one()


async def _lon(session: AsyncSession, event: Event) -> float:
    return (
        await session.execute(
            text("SELECT ST_X(geom::geometry) FROM events WHERE id = :id"), {"id": event.id}
        )
    ).scalar_one()


async def _refresh_cluster(session: AsyncSession, cluster_id: int) -> None:
    """Recompute membership stats, centroid, and representative after a join."""
    cluster = await session.get(EventCluster, cluster_id)
    if cluster is None:
        return
    members = (
        (
            await session.execute(
                text("SELECT id FROM events WHERE cluster_id = :c"), {"c": cluster_id}
            )
        )
        .scalars()
        .all()
    )
    events = [e for m in members if (e := await session.get(Event, m)) is not None]
    if not events:
        return
    cluster.member_count = len(events)
    cluster.first_seen = min(e.occurred_at for e in events)
    cluster.last_seen = max(e.occurred_at for e in events)
    representative = max(events, key=_member_rank)
    cluster.representative = representative.id
    representative.source_count = len(events)
    row = (
        await session.execute(
            text(
                "SELECT ST_X(ST_Centroid(ST_Collect(geom::geometry))), "
                "ST_Y(ST_Centroid(ST_Collect(geom::geometry))) "
                "FROM events WHERE cluster_id = :c"
            ),
            {"c": cluster_id},
        )
    ).one()
    cluster.centroid = f"SRID=4326;POINT({row[0]} {row[1]})"

    from app.pipeline.reliability import score_cluster

    cluster.reliability = await score_cluster(session, cluster, events)
    representative.reliability = cluster.reliability
