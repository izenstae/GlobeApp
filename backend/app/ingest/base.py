import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.manager import CredentialDead, CredentialNotFound
from app.models import Event, IngestWatermark
from app.pipeline.dedupe import assign_cluster
from app.pipeline.enrich import enrich_event
from app.pipeline.normalize import UnifiedEvent
from app.pipeline.publish import publish_new_event
from app.pipeline.store import upsert_events

logger = logging.getLogger(__name__)


class BaseIngester(ABC):
    """Fetch -> normalize -> upsert -> enrich -> cluster -> publish, with a
    high-water mark so restarts resume rather than re-pull, and failures that
    surface in /health/feeds rather than vanishing into a log nobody reads.
    """

    source: str

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis

    # ------------------------------------------------------------- overrides

    @abstractmethod
    async def fetch(self, since: datetime | None) -> tuple[list[Any], datetime | None]:
        """Return (raw records, new watermark or None to keep the old one)."""

    @abstractmethod
    def normalize(self, raw: Any) -> UnifiedEvent | None:
        """Map one raw record to the unified schema, or None to drop it."""

    # -------------------------------------------------------------- plumbing

    async def run_once(self) -> int:
        started = datetime.now(UTC)
        since = await self._load_watermark()
        try:
            raws, new_watermark = await self.fetch(since)
        except (CredentialDead, CredentialNotFound) as exc:
            # Credential problems degrade this one feed; the app keeps serving.
            await self._record_failure(started, f"credential: {exc}")
            logger.error("%s: skipped, %s", self.source, exc)
            return 0
        except Exception as exc:
            await self._record_failure(started, str(exc))
            logger.exception("%s: fetch failed", self.source)
            return 0

        try:
            unified = []
            for raw in raws:
                ev = self.normalize(raw)
                if ev is not None:
                    unified.append(ev)
            new_ids = await self._store_and_process(unified)
            await self._record_success(started, new_watermark, len(new_ids))
            logger.info(
                "%s: %d records fetched, %d normalized, %d new",
                self.source,
                len(raws),
                len(unified),
                len(new_ids),
            )
            return len(new_ids)
        except Exception as exc:
            await self._record_failure(started, str(exc))
            logger.exception("%s: pipeline failed", self.source)
            return 0

    async def _store_and_process(self, unified: list[UnifiedEvent]) -> list[int]:
        new_ids: list[int] = []
        async with self._session_factory() as session:
            async with session.begin():
                new_ids = await upsert_events(session, unified)
                for event_id in new_ids:
                    event = await session.get(Event, event_id)
                    assert event is not None
                    await enrich_event(session, event)
                    await assign_cluster(session, event)
            # Publish after commit so subscribers can immediately read the rows.
            for event_id in new_ids:
                await publish_new_event(session, self._redis, event_id)
        return new_ids

    async def _load_watermark(self) -> datetime | None:
        async with self._session_factory() as session:
            wm = await session.get(IngestWatermark, self.source)
            return wm.watermark if wm else None

    async def _get_or_create(self, session: AsyncSession) -> IngestWatermark:
        wm = await session.get(IngestWatermark, self.source)
        if wm is None:
            wm = IngestWatermark(source=self.source, records_ingested=0, consecutive_failures=0)
            session.add(wm)
        return wm

    async def _record_success(
        self, started: datetime, new_watermark: datetime | None, new_count: int
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                wm = await self._get_or_create(session)
                wm.last_attempt_at = started
                wm.last_success_at = datetime.now(UTC)
                wm.last_error = None
                wm.consecutive_failures = 0
                wm.records_ingested += new_count
                if new_watermark is not None:
                    wm.watermark = new_watermark

    async def _record_failure(self, started: datetime, error: str) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                wm = await self._get_or_create(session)
                wm.last_attempt_at = started
                wm.last_error = error[:1000]
                wm.consecutive_failures += 1
