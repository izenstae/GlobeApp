import io
import zipfile

import httpx
import pytest
import respx
from sqlalchemy import text

from app.ingest.gdelt import LASTUPDATE_URL, GdeltIngester
from tests.test_pipeline import gdelt_cols

EXPORT_URL = "http://data.gdeltproject.org/gdeltv2/20260815120000.export.CSV.zip"


def make_zip(rows: list[list[str]]) -> bytes:
    buf = io.BytesIO()
    body = "\n".join("\t".join(r) for r in rows)
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("20260815120000.export.CSV", body)
    return buf.getvalue()


@pytest.fixture
def mocked_gdelt():
    rows = [
        gdelt_cols(event_id="900000001", code="195", root="19"),  # airstrike, kept
        gdelt_cols(event_id="900000002", code="010", root="01"),  # noise, dropped
        gdelt_cols(event_id="900000003", code="1831", root="18", lat="31.5", lon="34.46"),
    ]
    with respx.mock(assert_all_called=False) as mock:
        mock.get(LASTUPDATE_URL).respond(
            200,
            text=(
                f"123 abc {EXPORT_URL}\n"
                "456 def http://data.gdeltproject.org/gdeltv2/x.mentions.CSV.zip\n"
            ),
        )
        mock.get(EXPORT_URL).respond(200, content=make_zip(rows))
        yield mock


async def test_gdelt_run_once_end_to_end(session_factory, mocked_gdelt):
    async with httpx.AsyncClient() as http:
        ingester = GdeltIngester(session_factory, http, redis=None)
        new_count = await ingester.run_once()
    assert new_count == 2  # noise row filtered out

    async with session_factory() as session:
        rows = (
            await session.execute(
                text("SELECT source_event_id, category, cluster_id FROM events ORDER BY 1")
            )
        ).all()
        assert [r[0] for r in rows] == ["900000001", "900000003"]
        assert all(r[2] is not None for r in rows)  # every event clustered

        wm = (
            await session.execute(
                text(
                    "SELECT watermark, last_success_at, consecutive_failures, records_ingested "
                    "FROM ingest_watermarks WHERE source='gdelt'"
                )
            )
        ).one()
        assert wm.watermark is not None
        assert wm.last_success_at is not None
        assert wm.consecutive_failures == 0
        assert wm.records_ingested == 2


async def test_gdelt_skips_already_ingested_batch(session_factory, mocked_gdelt):
    async with httpx.AsyncClient() as http:
        ingester = GdeltIngester(session_factory, http, redis=None)
        assert await ingester.run_once() == 2
        assert await ingester.run_once() == 0  # same file timestamp: skipped

    async with session_factory() as session:
        count = (await session.execute(text("SELECT count(*) FROM events"))).scalar_one()
        assert count == 2


async def test_gdelt_failure_surfaces_in_watermark(session_factory):
    with respx.mock:
        respx.get(LASTUPDATE_URL).respond(503)
        async with httpx.AsyncClient() as http:
            ingester = GdeltIngester(session_factory, http, redis=None)
            assert await ingester.run_once() == 0

    async with session_factory() as session:
        wm = (
            await session.execute(
                text(
                    "SELECT last_error, consecutive_failures FROM ingest_watermarks "
                    "WHERE source='gdelt'"
                )
            )
        ).one()
        assert wm.last_error is not None
        assert wm.consecutive_failures == 1
