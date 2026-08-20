"""Cluster-level reliability score, 0..1. The number is always exposed —
an analyst-grade tool shows its work.
"""

from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, EventCluster

# Source tier: ACLED and UCDP are human-curated; GDELT is machine-coded news.
TIER_BASE = {"acled": 0.70, "ucdp": 0.70, "gdelt": 0.35}
PRECISION_BONUS = {"exact": 0.05, "settlement": 0.05, "admin2": 0.02}
THERMAL_BONUS = 0.15
DOMAIN_BONUS_STEP = 0.05
DOMAIN_BONUS_CAP = 0.15
CONSISTENCY_BONUS = 0.05


def root_domain(url: str) -> str | None:
    """Crude root-domain extraction so three copies of one wire story do not
    count as three sources."""
    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError:
        return None
    if not netloc:
        return None
    netloc = netloc.removeprefix("www.")
    parts = netloc.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else netloc


def distinct_domains(events: list[Event]) -> set[str]:
    domains = set()
    for event in events:
        for url in event.source_urls or []:
            d = root_domain(url)
            if d:
                domains.add(d)
    return domains


def fatalities_consistent(events: list[Event]) -> bool | None:
    """True/False if two or more members report fatalities; None if unknowable."""
    counts = [e.fatalities for e in events if e.fatalities is not None]
    if len(counts) < 2:
        return None
    spread = max(counts) - min(counts)
    return spread <= max(2, int(0.2 * max(counts)))


async def score_cluster(session: AsyncSession, cluster: EventCluster, events: list[Event]) -> float:
    score = max(TIER_BASE.get(e.source, 0.2) for e in events)

    domains = distinct_domains(events)
    if len(domains) > 1:
        score += min(DOMAIN_BONUS_STEP * (len(domains) - 1), DOMAIN_BONUS_CAP)

    best_precision = min(
        events,
        key=lambda e: ["exact", "settlement", "admin2", "admin1", "country"].index(e.geo_precision),
    ).geo_precision
    score += PRECISION_BONUS.get(best_precision, 0.0)

    if cluster.thermal_corroborated:
        score += THERMAL_BONUS

    consistent = fatalities_consistent(events)
    if consistent is True:
        score += CONSISTENCY_BONUS
    elif consistent is False:
        score -= CONSISTENCY_BONUS

    return round(min(max(score, 0.0), 1.0), 3)


def explain_cluster(cluster: EventCluster, events: list[Event]) -> str:
    """Plain-language explanation for the reliability hover."""
    parts = []
    sources = {e.source for e in events}
    if "acled" in sources:
        parts.append("ACLED-curated record")
    if "ucdp" in sources:
        parts.append("UCDP-curated record")
    domains = distinct_domains(events)
    if len(domains) > 1:
        parts.append(f"{len(domains)} independent outlets")
    elif len(events) == 1 and sources == {"gdelt"}:
        parts.append("single GDELT report, uncorroborated")
    if cluster.thermal_corroborated:
        parts.append("thermal signature corroborated")
    consistent = fatalities_consistent(events)
    if consistent is True:
        parts.append("sources agree on fatalities")
    elif consistent is False:
        parts.append("sources disagree on fatalities")
    return "; ".join(parts) if parts else "single source"
