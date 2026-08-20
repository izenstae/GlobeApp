"""UCDP GED ingester (brief §6.4): the historical baseline layer.

Uppsala's Georeferenced Event Dataset — the highest-precision curated source,
released monthly (candidate events), not live. Two jobs: (a) a baseline layer
that clusters against the live pipeline's output, and (b) the accuracy check
served by /analysis/ucdp comparing what this pipeline produced for a period
against what UCDP later curated for the same period.

Public REST API, no key. UCDP revises candidate records, so like ACLED the
fetch re-pulls a trailing window and upserts rather than trusting one pass.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.config import get_settings
from app.ingest.base import BaseIngester
from app.pipeline.normalize import UnifiedEvent, normalize_ucdp

UCDP_BASE_URL = "https://ucdpapi.pcr.uu.se/api/gedevents/{version}"
PAGE_SIZE = 1000
MAX_PAGES = 200  # hard stop: 200k rows in one run means the window is wrong
REPULL_OVERLAP_DAYS = 45  # candidate records are revised for weeks after release


class UcdpIngester(BaseIngester):
    source = "ucdp"

    def __init__(self, session_factory, http: httpx.AsyncClient, redis=None) -> None:
        super().__init__(session_factory, redis)
        self._http = http

    async def fetch(self, since: datetime | None) -> tuple[list[Any], datetime | None]:
        settings = get_settings()
        if since is None:
            start = datetime.now(UTC) - timedelta(days=settings.ucdp_window_days)
        else:
            start = since - timedelta(days=REPULL_OVERLAP_DAYS)

        url = UCDP_BASE_URL.format(version=settings.ucdp_api_version)
        params: dict[str, Any] = {
            "pagesize": PAGE_SIZE,
            "page": 0,
            "StartDate": start.date().isoformat(),
        }
        rows: list[dict[str, Any]] = []
        newest: datetime | None = None
        for page in range(MAX_PAGES):
            params["page"] = page
            resp = await self._http.get(url, params=params, timeout=120)
            resp.raise_for_status()
            body = resp.json()
            batch = body.get("Result") or []
            rows.extend(batch)
            for row in batch:
                stamp = str(row.get("date_start", ""))[:10]
                try:
                    seen = datetime.strptime(stamp, "%Y-%m-%d").replace(tzinfo=UTC)
                except ValueError:
                    continue
                if newest is None or seen > newest:
                    newest = seen
            total_pages = int(body.get("TotalPages") or 0)
            if page + 1 >= total_pages or not batch:
                break
        else:
            raise RuntimeError(
                f"ucdp: exceeded {MAX_PAGES} pages from StartDate={params['StartDate']}; "
                "narrow ucdp_window_days instead of truncating silently"
            )
        return rows, newest

    def normalize(self, raw: Any) -> UnifiedEvent | None:
        return normalize_ucdp(raw)
