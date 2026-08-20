"""UCDP baseline comparison (brief §6.4): a periodic accuracy check of what the
live pipeline produced against what UCDP later curated for the same period.

"Matched" is deliberately mechanical and stated in the response: a UCDP event
counts as matched when at least one non-UCDP pipeline event lies within 25 km
and ±1 day of it. This is coverage, not truth — UCDP and the live feeds have
different inclusion criteria, so the number contextualizes rather than grades.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

router = APIRouter(tags=["analysis"])

MATCH_RADIUS_M = 25_000
MATCH_WINDOW = "1 day"

_MATCH_EXISTS = f"""EXISTS (
    SELECT 1 FROM events p
    WHERE p.source != 'ucdp'
      AND p.occurred_at BETWEEN u.occurred_at - INTERVAL '{MATCH_WINDOW}'
                            AND u.occurred_at + INTERVAL '{MATCH_WINDOW}'
      AND ST_DWithin(p.geom, u.geom, {MATCH_RADIUS_M})
)"""


def _month_bounds(month: str) -> tuple[datetime, datetime]:
    try:
        start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
    except ValueError:
        raise HTTPException(422, "month must be YYYY-MM") from None
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


@router.get("/analysis/ucdp")
async def ucdp_comparison(
    month: str | None = Query(None, description="YYYY-MM; defaults to latest month with UCDP data"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    months = [
        r[0]
        for r in await session.execute(
            text(
                "SELECT DISTINCT to_char(date_trunc('month', occurred_at), 'YYYY-MM') "
                "FROM events WHERE source = 'ucdp' ORDER BY 1"
            )
        )
    ]
    if not months:
        return {
            "available": False,
            "note": "No UCDP baseline data ingested yet. The ucdp feed pulls monthly "
            "candidate releases on its own schedule; see /health/feeds.",
        }
    if month is None:
        month = months[-1]
    start, end = _month_bounds(month)

    ucdp_total = (
        await session.execute(
            text(
                "SELECT count(*) FROM events WHERE source = 'ucdp' "
                "AND occurred_at >= :start AND occurred_at < :end"
            ),
            {"start": start, "end": end},
        )
    ).scalar_one()

    # Distinct pipeline incidents (clusters, or unclustered singletons) that
    # carry at least one non-UCDP member in the month.
    pipeline_total = (
        await session.execute(
            text(
                "SELECT count(DISTINCT COALESCE(cluster_id, -id)) FROM events "
                "WHERE source != 'ucdp' AND occurred_at >= :start AND occurred_at < :end"
            ),
            {"start": start, "end": end},
        )
    ).scalar_one()

    matched = (
        await session.execute(
            text(
                f"SELECT count(*) FROM events u WHERE u.source = 'ucdp' "
                f"AND u.occurred_at >= :start AND u.occurred_at < :end AND {_MATCH_EXISTS}"
            ),
            {"start": start, "end": end},
        )
    ).scalar_one()

    by_country = [
        {
            "country": r[0],
            "ucdp_events": r[1],
            "matched_by_pipeline": r[2],
        }
        for r in await session.execute(
            text(
                f"""
                SELECT COALESCE(u.country, '(unknown)'),
                       count(*),
                       count(*) FILTER (WHERE {_MATCH_EXISTS})
                FROM events u
                WHERE u.source = 'ucdp' AND u.occurred_at >= :start AND u.occurred_at < :end
                GROUP BY 1 ORDER BY 2 DESC LIMIT 30
                """
            ),
            {"start": start, "end": end},
        )
    ]

    return {
        "available": True,
        "month": month,
        "months_with_data": months,
        "criteria": f"UCDP event matched when a non-UCDP pipeline event lies within "
        f"{MATCH_RADIUS_M // 1000} km and ±{MATCH_WINDOW}",
        "ucdp_events": ucdp_total,
        "pipeline_incidents": pipeline_total,
        "ucdp_matched_by_pipeline": matched,
        "match_rate": round(matched / ucdp_total, 3) if ucdp_total else None,
        "by_country": by_country,
        "note": "Coverage comparison, not ground truth: UCDP candidate data lags and "
        "uses different inclusion criteria than the live feeds.",
    }
