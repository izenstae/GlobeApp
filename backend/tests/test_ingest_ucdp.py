import httpx
import pytest
import respx
from sqlalchemy import text

from app.ingest.ucdp import UCDP_BASE_URL, UcdpIngester
from app.pipeline.normalize import normalize_ucdp

API_URL = UCDP_BASE_URL.format(version="25.1")


def ucdp_row(**overrides):
    row = {
        "id": 411001,
        "relid": "UKR-2026-1-411001",
        "date_start": "2026-08-15T00:00:00",
        "date_end": "2026-08-15T00:00:00",
        "latitude": 49.9935,
        "longitude": 36.2304,
        "where_prec": 1,
        "where_coordinates": "Kharkiv city",
        "country": "Ukraine",
        "adm_1": "Kharkiv oblast",
        "type_of_violence": 1,
        "side_a": "Government of Russia",
        "side_b": "Government of Ukraine",
        "best": 3,
        "dyad_name": "Russia - Ukraine",
        "source_headline": "Strikes reported on Kharkiv",
    }
    row.update(overrides)
    return row


# ------------------------------------------------------------------ normalize


def test_normalize_ucdp_state_based():
    ev = normalize_ucdp(ucdp_row())
    assert ev is not None
    assert ev.source == "ucdp"
    assert ev.source_event_id == "411001"
    assert ev.category == "ground_assault"
    assert ev.raw_event_type == "state-based conflict"
    assert ev.geo_precision == "settlement"
    assert ev.fatalities == 3
    assert ev.actor_a == "Government of Russia"
    assert ev.occurred_at.isoformat().startswith("2026-08-15")


def test_normalize_ucdp_one_sided_and_precision():
    ev = normalize_ucdp(ucdp_row(type_of_violence=3, where_prec=6))
    assert ev.category == "other_violence"
    assert ev.raw_event_type == "one-sided violence"
    assert ev.geo_precision == "country"
    assert ev.geo_radius_m == 250_000


def test_normalize_ucdp_missing_coords_dropped():
    assert normalize_ucdp(ucdp_row(latitude=None)) is None
    assert normalize_ucdp(ucdp_row(date_start="not a date")) is None


# ------------------------------------------------------------------- ingester


@pytest.fixture
def mocked_ucdp():
    pages = {
        "0": [ucdp_row(), ucdp_row(id=411002, latitude=48.02, longitude=37.80)],
        "1": [ucdp_row(id=411003, date_start="2026-08-16T00:00:00")],
    }

    def respond(request):
        page = request.url.params.get("page", "0")
        return httpx.Response(
            200,
            json={
                "TotalCount": 3,
                "TotalPages": 2,
                "PreviousPageUrl": "",
                "NextPageUrl": "",
                "Result": pages.get(page, []),
            },
        )

    with respx.mock(assert_all_called=False) as mock:
        mock.get(API_URL).mock(side_effect=respond)
        yield mock


async def test_ucdp_run_once_end_to_end(session_factory, mocked_ucdp):
    async with httpx.AsyncClient() as http:
        ingester = UcdpIngester(session_factory, http, redis=None)
        assert await ingester.run_once() == 3

    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT source_event_id, category, cluster_id FROM events "
                    "WHERE source = 'ucdp' ORDER BY 1"
                )
            )
        ).all()
        assert [r[0] for r in rows] == ["411001", "411002", "411003"]
        assert all(r[2] is not None for r in rows)

        wm = (
            await session.execute(
                text(
                    "SELECT watermark, records_ingested FROM ingest_watermarks WHERE source='ucdp'"
                )
            )
        ).one()
        assert wm.watermark.isoformat().startswith("2026-08-16")
        assert wm.records_ingested == 3


async def test_ucdp_repull_upserts_without_duplicates(session_factory, mocked_ucdp):
    async with httpx.AsyncClient() as http:
        ingester = UcdpIngester(session_factory, http, redis=None)
        assert await ingester.run_once() == 3
        # Second run re-pulls the overlap window; upsert, not duplicate.
        assert await ingester.run_once() == 0

    async with session_factory() as session:
        count = (
            await session.execute(text("SELECT count(*) FROM events WHERE source='ucdp'"))
        ).scalar_one()
        assert count == 3
