"""APScheduler wiring: ingest cadences, proactive credential refresh with
30s/2m/8m backoff retries, and nothing hidden — every failure lands in
ingest_watermarks or api_credentials where /health/feeds can see it.
"""

import logging
from datetime import UTC, datetime, timedelta

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from redis.asyncio import Redis

from app.auth.http import ProviderClient
from app.auth.manager import CredentialDead, CredentialManager, CredentialNotFound
from app.config import get_settings
from app.db import get_session_factory
from app.ingest.acled import AcledIngester
from app.ingest.firms import FirmsIngester
from app.ingest.gdelt import GdeltIngester
from app.ingest.ucdp import UcdpIngester

logger = logging.getLogger(__name__)


async def build_scheduler() -> AsyncIOScheduler:
    settings = get_settings()
    session_factory = get_session_factory()
    redis = Redis.from_url(settings.redis_url)
    http = httpx.AsyncClient(timeout=120, follow_redirects=True)
    manager = CredentialManager(session_factory)

    acled = AcledIngester(session_factory, ProviderClient("acled", manager, http), redis)
    gdelt = GdeltIngester(session_factory, http, redis)
    firms = FirmsIngester(session_factory, manager, http, redis)
    ucdp = UcdpIngester(session_factory, http, redis)

    scheduler = AsyncIOScheduler(timezone=UTC)

    async def refresh_credentials() -> None:
        for provider in await manager.proactive_refresh_due():
            try:
                await manager.force_refresh(provider)
                logger.info("%s: proactive token refresh ok", provider)
            except (CredentialDead, CredentialNotFound) as exc:
                logger.error("%s: not refreshable: %s", provider, exc)
            except Exception:
                # Transient failure: schedule a one-shot retry on the 30s/2m/8m
                # ladder. After three consecutive failures the manager marks the
                # credential degraded and the 15-minute cadence keeps trying.
                creds = {c.provider: c for c in await manager.status()}
                failures = creds[provider].refresh_failures if provider in creds else 1
                if failures <= 3:
                    delay = CredentialManager.backoff_delay(failures)
                    scheduler.add_job(
                        refresh_credentials,
                        "date",
                        run_date=datetime.now(UTC) + timedelta(seconds=delay),
                        id=f"cred_retry_{provider}_{failures}",
                        replace_existing=True,
                    )
                    logger.warning("%s: refresh failed, retrying in %ds", provider, delay)

    scheduler.add_job(
        refresh_credentials,
        "interval",
        seconds=settings.credential_refresh_interval,
        id="credential_refresh",
    )
    scheduler.add_job(
        acled.run_once,
        "interval",
        seconds=settings.acled_interval,
        id="ingest_acled",
        next_run_time=datetime.now(UTC) + timedelta(seconds=5),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        gdelt.run_once,
        "interval",
        seconds=settings.gdelt_interval,
        id="ingest_gdelt",
        next_run_time=datetime.now(UTC) + timedelta(seconds=10),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        firms.run_once,
        "interval",
        seconds=settings.firms_interval,
        id="ingest_firms",
        next_run_time=datetime.now(UTC) + timedelta(seconds=20),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        ucdp.run_once,
        "interval",
        seconds=settings.ucdp_interval,
        id="ingest_ucdp",
        next_run_time=datetime.now(UTC) + timedelta(seconds=40),
        max_instances=1,
        coalesce=True,
    )
    return scheduler
