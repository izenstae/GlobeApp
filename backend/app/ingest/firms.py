import csv
import io
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.auth.manager import CredentialManager
from app.ingest.base import BaseIngester
from app.models import FirmsHotspot
from app.pipeline.corroborate import corroborate_clusters
from app.pipeline.normalize import UnifiedEvent

logger = logging.getLogger(__name__)

AREA_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{dataset}/world/1"
DATASETS = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT")


class FirmsIngester(BaseIngester):
    """Satellite thermal anomalies: an independent physical-evidence layer, not a
    conflict feed. Hotspots are stored for (a) a toggleable overlay and (b)
    corroboration of reported kinetic events. They are never promoted to events.
    """

    source = "firms"

    def __init__(
        self,
        session_factory,
        manager: CredentialManager,
        http: httpx.AsyncClient,
        redis=None,
    ) -> None:
        super().__init__(session_factory, redis)
        self._manager = manager
        self._http = http

    async def fetch(self, since: datetime | None) -> tuple[list[Any], datetime | None]:
        key = await self._manager.get_token("firms")
        rows: list[dict[str, Any]] = []
        for dataset in DATASETS:
            resp = await self._http.get(AREA_URL.format(key=key, dataset=dataset), timeout=300)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            rows.extend(reader)
        return rows, datetime.now(UTC)

    def normalize(self, raw: Any) -> UnifiedEvent | None:
        return None  # hotspots are not events, by design

    async def _store_and_process(self, unified: list[UnifiedEvent]) -> list[int]:
        return []  # unused; run_once is overridden

    async def run_once(self) -> int:
        started = datetime.now(UTC)
        since = await self._load_watermark()
        try:
            rows, new_watermark = await self.fetch(since)
        except Exception as exc:
            await self._record_failure(started, str(exc))
            logger.exception("firms: fetch failed")
            return 0

        try:
            stored = await self._store_hotspots(rows)
            async with self._session_factory() as session:
                async with session.begin():
                    await corroborate_clusters(session)
            await self._record_success(started, new_watermark, stored)
            logger.info("firms: %d rows fetched, %d new hotspots", len(rows), stored)
            return stored
        except Exception as exc:
            await self._record_failure(started, str(exc))
            logger.exception("firms: pipeline failed")
            return 0

    async def _store_hotspots(self, rows: list[dict[str, Any]]) -> int:
        stored = 0
        async with self._session_factory() as session:
            async with session.begin():
                for row in rows:
                    hotspot = self._parse(row)
                    if hotspot is None:
                        continue
                    stmt = (
                        pg_insert(FirmsHotspot)
                        .values(**hotspot)
                        .on_conflict_do_nothing(
                            index_elements=["satellite", "acquired_at", "lat", "lon"]
                        )
                    )
                    result = await session.execute(stmt)
                    stored += result.rowcount or 0  # type: ignore[attr-defined]
        return stored

    @staticmethod
    def _parse(row: dict[str, Any]) -> dict[str, Any] | None:
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
            acq_date = row["acq_date"]
            acq_time = str(row.get("acq_time", "0")).zfill(4)
            acquired = datetime.strptime(f"{acq_date} {acq_time}", "%Y-%m-%d %H%M").replace(
                tzinfo=UTC
            )
        except (KeyError, ValueError):
            return None
        frp = None
        brightness = None
        try:
            frp = float(row["frp"])
        except (KeyError, TypeError, ValueError):
            pass
        raw_brightness = row.get("bright_ti4") or row.get("brightness")
        if raw_brightness is not None:
            try:
                brightness = float(raw_brightness)
            except (TypeError, ValueError):
                pass
        return {
            "satellite": row.get("satellite", "unknown"),
            "acquired_at": acquired,
            "lat": lat,
            "lon": lon,
            "geom": f"SRID=4326;POINT({lon} {lat})",
            "brightness": brightness,
            "frp": frp,
            "confidence": row.get("confidence"),
            "raw_payload": dict(row),
        }
