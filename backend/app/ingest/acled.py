from datetime import UTC, datetime, timedelta
from typing import Any

from app.auth.http import ProviderClient
from app.config import get_settings
from app.ingest.base import BaseIngester
from app.pipeline.normalize import UnifiedEvent, normalize_acled

API_URL = "https://acleddata.com/api/acled/read"
PAGE_LIMIT = 5000
MAX_PAGES = 40  # hard stop; 200k rows in one window means something is wrong


class AcledIngester(BaseIngester):
    """Curated conflict events. Re-pulls the trailing window and upserts, because
    ACLED revises records after publication. Highest-quality source: its actor
    names are the canonical actor taxonomy.
    """

    source = "acled"

    def __init__(self, session_factory, client: ProviderClient, redis=None) -> None:
        super().__init__(session_factory, redis)
        self._client = client

    async def fetch(self, since: datetime | None) -> tuple[list[Any], datetime | None]:
        now = datetime.now(UTC)
        window_start = (now - timedelta(days=get_settings().acled_window_days)).date()
        rows: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            resp = await self._client.get(
                API_URL,
                params={
                    "_format": "json",
                    "event_date": f"{window_start}|{now.date()}",
                    "event_date_where": "BETWEEN",
                    "limit": PAGE_LIMIT,
                    "page": page,
                },
                timeout=120,
            )
            resp.raise_for_status()
            body = resp.json()
            page_rows = body.get("data", [])
            rows.extend(page_rows)
            if len(page_rows) < PAGE_LIMIT:
                break
        return rows, now

    def normalize(self, raw: Any) -> UnifiedEvent | None:
        return normalize_acled(raw)
