import io
import zipfile
from datetime import UTC, datetime
from typing import Any

import httpx

from app.ingest.base import BaseIngester
from app.pipeline.normalize import UnifiedEvent, normalize_gdelt

LASTUPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"


class GdeltIngester(BaseIngester):
    """The live firehose: 15-minute machine-coded export files, no key, no quota.

    Quality caveat carried through to the UI: GDELT mixes reliable outlets with
    questionable ones and is prone to duplicate and circular reporting. A
    GDELT-only event with source_count=1 renders visibly lower-confidence.
    """

    source = "gdelt"

    def __init__(self, session_factory, http: httpx.AsyncClient, redis=None) -> None:
        super().__init__(session_factory, redis)
        self._http = http

    async def fetch(self, since: datetime | None) -> tuple[list[Any], datetime | None]:
        resp = await self._http.get(LASTUPDATE_URL, timeout=30)
        resp.raise_for_status()
        export_url = None
        for line in resp.text.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[2].endswith(".export.CSV.zip"):
                export_url = parts[2]
                break
        if export_url is None:
            raise RuntimeError("gdelt lastupdate.txt carried no export file url")

        stamp = export_url.rsplit("/", 1)[-1].split(".")[0]
        file_time = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        if since is not None and file_time <= since:
            return [], None  # already ingested this batch

        zresp = await self._http.get(export_url, timeout=120)
        zresp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(zresp.content)) as zf:
            name = zf.namelist()[0]
            content = zf.read(name).decode("utf-8", errors="replace")
        rows = [line.split("\t") for line in content.splitlines() if line]
        return rows, file_time

    def normalize(self, raw: Any) -> UnifiedEvent | None:
        return normalize_gdelt(raw)
