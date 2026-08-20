from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.events import EVENT_CATEGORIES
from app.pipeline.publish import serialize_event

router = APIRouter(tags=["events"])


def _parse_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    if not bbox:
        return None
    try:
        min_lon, min_lat, max_lon, max_lat = (float(p) for p in bbox.split(","))
    except ValueError:
        raise HTTPException(422, "bbox must be 'minLon,minLat,maxLon,maxLat'") from None
    return (min_lon, min_lat, max_lon, max_lat)


# Filters that must hold if ANY member of the cluster satisfies them: weapons
# and actors usually live on non-representative members (a GDELT article names
# the weapon, ACLED names the actors), so matching only the representative row
# would silently drop corroborated events.
_MEMBER_SCOPE = "(m.id = e.id OR (e.cluster_id IS NOT NULL AND m.cluster_id = e.cluster_id))"


@router.get("/events")
async def list_events(
    bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat"),
    since: datetime | None = None,
    until: datetime | None = None,
    category: list[str] | None = Query(None),
    country: list[str] | None = Query(None, description="exact country names, case-insensitive"),
    actor: str | None = Query(None, min_length=2, description="substring, raw or canonical"),
    weapon: list[str] | None = Query(None, description="canonical weapon keys"),
    min_reliability: float | None = Query(None, ge=0, le=1),
    limit: int = Query(2000, le=10000),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Clusters by default: one row per cluster (its representative event),
    plus any not-yet-clustered events. Individual members come via drill-down."""
    if category:
        unknown = set(category) - set(EVENT_CATEGORIES)
        if unknown:
            raise HTTPException(422, f"unknown categories: {sorted(unknown)}")
    if since is None:
        since = datetime.now(UTC) - timedelta(days=14)

    clauses = [
        "(e.id IN (SELECT representative FROM event_clusters) OR e.cluster_id IS NULL)",
        "e.occurred_at >= :since",
    ]
    params: dict[str, Any] = {"since": since, "limit": limit}
    expanding: list[str] = []
    if until is not None:
        clauses.append("e.occurred_at <= :until")
        params["until"] = until
    if category:
        clauses.append("e.category IN :categories")
        params["categories"] = category
        expanding.append("categories")
    if country:
        clauses.append("lower(e.country) IN :countries")
        params["countries"] = [c.strip().lower() for c in country]
        expanding.append("countries")
    if actor:
        clauses.append(
            f"""EXISTS (
                SELECT 1 FROM events m WHERE {_MEMBER_SCOPE}
                AND (m.actor_a ILIKE :actor_pat OR m.actor_b ILIKE :actor_pat
                     OR m.actor_a_canonical ILIKE :actor_pat
                     OR m.actor_b_canonical ILIKE :actor_pat)
            )"""
        )
        params["actor_pat"] = f"%{actor.strip()}%"
    if weapon:
        clauses.append(
            f"""EXISTS (
                SELECT 1 FROM event_weapons w JOIN events m ON m.id = w.event_id
                WHERE {_MEMBER_SCOPE} AND w.weapon_key IN :weapon_keys
            )"""
        )
        params["weapon_keys"] = weapon
        expanding.append("weapon_keys")
    if min_reliability is not None:
        clauses.append("COALESCE(e.reliability, 0) >= :min_reliability")
        params["min_reliability"] = min_reliability
    box = _parse_bbox(bbox)
    if box is not None:
        clauses.append(
            "ST_Intersects(e.geom, ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326))"
        )
        params.update({"min_lon": box[0], "min_lat": box[1], "max_lon": box[2], "max_lat": box[3]})

    stmt = text(
        f"""
        SELECT e.id, e.cluster_id, e.source, e.occurred_at, e.category,
               e.geo_precision, e.geo_radius_m, e.country, e.location_name,
               e.fatalities, e.reliability, e.headline,
               COALESCE(c.member_count, 1) AS source_count,
               COALESCE(c.thermal_corroborated, false) AS thermal_corroborated,
               ST_Y(e.geom::geometry) AS lat, ST_X(e.geom::geometry) AS lon,
               ST_Y(e.origin_geom::geometry) AS origin_lat,
               ST_X(e.origin_geom::geometry) AS origin_lon,
               e.origin_country, e.origin_precision, e.origin_method, e.origin_confidence
        FROM events e
        LEFT JOIN event_clusters c ON c.id = e.cluster_id
        WHERE {" AND ".join(clauses)}
        ORDER BY e.occurred_at DESC
        LIMIT :limit
        """
    )
    for name in expanding:
        stmt = stmt.bindparams(bindparam(name, expanding=True))
    rows = (await session.execute(stmt, params)).mappings().all()
    return {"events": [dict(r) for r in rows], "count": len(rows)}


@router.get("/meta/filters")
async def filter_metadata(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Vocabulary the filter panel offers: only values that actually occur in
    the ingested data — the UI never presents options the data cannot satisfy."""
    countries = [
        r[0]
        for r in await session.execute(
            text(
                "SELECT country FROM events WHERE country IS NOT NULL "
                "GROUP BY country ORDER BY count(*) DESC, country LIMIT 300"
            )
        )
    ]
    actors = [
        r[0]
        for r in await session.execute(
            text(
                "SELECT actor FROM ("
                "  SELECT COALESCE(actor_a_canonical, actor_a) AS actor FROM events"
                "  UNION ALL SELECT COALESCE(actor_b_canonical, actor_b) FROM events"
                ") t WHERE actor IS NOT NULL "
                "GROUP BY actor ORDER BY count(*) DESC, actor LIMIT 300"
            )
        )
    ]
    weapons = [
        {"weapon_key": r[0], "display_name": r[1], "event_count": r[2]}
        for r in await session.execute(
            text(
                "SELECT weapon_key, min(display_name), count(DISTINCT event_id) "
                "FROM event_weapons GROUP BY weapon_key ORDER BY 3 DESC, 1"
            )
        )
    ]
    return {"countries": countries, "actors": actors, "weapons": weapons}


@router.get("/events/{event_id}")
async def get_event(event_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    payload = await serialize_event(session, event_id)
    if payload is None:
        raise HTTPException(404, "event not found")
    if payload["cluster_id"] is not None:
        members = (
            await session.execute(
                text(
                    """
                    SELECT id, source, source_event_id, occurred_at, category,
                           actor_a, actor_b, fatalities, headline, source_urls
                    FROM events WHERE cluster_id = :c ORDER BY occurred_at
                    """
                ),
                {"c": payload["cluster_id"]},
            )
        ).mappings()
        payload["members"] = [dict(m) for m in members]
    return payload


@router.get("/hotspots")
async def list_hotspots(
    bbox: str | None = Query(None),
    since: datetime | None = None,
    limit: int = Query(5000, le=20000),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """FIRMS thermal anomaly overlay. Not conflict events — heat signatures."""
    if since is None:
        since = datetime.now(UTC) - timedelta(days=1)
    clauses = ["acquired_at >= :since"]
    params: dict[str, Any] = {"since": since, "limit": limit}
    box = _parse_bbox(bbox)
    if box is not None:
        clauses.append(
            "ST_Intersects(geom, ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326))"
        )
        params.update({"min_lon": box[0], "min_lat": box[1], "max_lon": box[2], "max_lat": box[3]})
    rows = (
        await session.execute(
            text(
                f"""
                SELECT id, satellite, acquired_at, lat, lon, brightness, frp, confidence
                FROM firms_hotspots
                WHERE {" AND ".join(clauses)}
                ORDER BY acquired_at DESC
                LIMIT :limit
                """
            ),
            params,
        )
    ).mappings()
    hotspots = [dict(r) for r in rows]
    return {"hotspots": hotspots, "count": len(hotspots)}
