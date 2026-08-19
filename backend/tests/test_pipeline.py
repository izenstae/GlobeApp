from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.models import Event, EventCluster, FirmsHotspot
from app.pipeline.corroborate import corroborate_clusters
from app.pipeline.dedupe import assign_cluster, categories_compatible
from app.pipeline.enrich import extract_weapons
from app.pipeline.normalize import normalize_acled, normalize_gdelt
from app.pipeline.store import upsert_events

NOW = datetime(2026, 8, 15, tzinfo=UTC)


def acled_row(**overrides):
    row = {
        "event_id_cnty": "UKR12345",
        "event_date": "2026-08-15",
        "event_type": "Explosions/Remote violence",
        "sub_event_type": "Air/drone strike",
        "actor1": "Military Forces of Russia (2000-)",
        "actor2": "Military Forces of Ukraine (2019-)",
        "country": "Ukraine",
        "admin1": "Kharkiv",
        "location": "Kharkiv",
        "latitude": "49.9935",
        "longitude": "36.2304",
        "geo_precision": "1",
        "fatalities": "3",
        "notes": "Russian forces launched an Iskander-M missile at Kharkiv.",
        "tags": "",
    }
    row.update(overrides)
    return row


def gdelt_cols(
    event_id="123456789",
    code="195",
    root="19",
    lat="49.99",
    lon="36.23",
    geo_type="4",
    actor1="RUSSIA",
    actor2="UKRAINE",
    url="https://example-news.com/strike",
):
    cols = [""] * 61
    cols[0] = event_id
    cols[1] = "20260815"
    cols[6] = actor1
    cols[16] = actor2
    cols[26] = code
    cols[27] = code[:3]
    cols[28] = root
    cols[51] = geo_type
    cols[52] = "Kharkiv, Kharkivska Oblast, Ukraine"
    cols[53] = "UP"
    cols[56] = lat
    cols[57] = lon
    cols[59] = "20260815120000"
    cols[60] = url
    return cols


# ------------------------------------------------------------------ normalize


def test_normalize_acled_airstrike():
    ev = normalize_acled(acled_row())
    assert ev is not None
    assert ev.category == "airstrike"
    assert ev.geo_precision == "settlement"
    assert ev.geo_radius_m == 5000
    assert ev.fatalities == 3
    assert ev.source == "acled"
    assert ev.raw_payload["event_id_cnty"] == "UKR12345"


def test_normalize_acled_drone_tag():
    ev = normalize_acled(acled_row(tags="drone strike; other"))
    assert ev.category == "drone_strike"


def test_normalize_acled_missing_coords_dropped():
    assert normalize_acled(acled_row(latitude=None)) is None


def test_normalize_gdelt_keeps_19x():
    ev = normalize_gdelt(gdelt_cols())
    assert ev is not None
    assert ev.category == "airstrike"
    assert ev.geo_precision == "settlement"
    assert ev.location_name == "Kharkiv"
    assert ev.country == "Ukraine"
    assert ev.source_urls == ["https://example-news.com/strike"]


def test_normalize_gdelt_filters_noise():
    assert normalize_gdelt(gdelt_cols(code="010", root="01")) is None


def test_normalize_gdelt_riot_code_145():
    ev = normalize_gdelt(gdelt_cols(code="145", root="14"))
    assert ev is not None
    assert ev.category == "riot"


# ------------------------------------------------------------------ enrichment


def test_weapon_extraction_hits_with_evidence():
    hits = extract_weapons("Strike carried out with an Iskander-M ballistic missile.")
    assert len(hits) == 1
    hit = hits[0]
    assert hit["weapon_key"] == "iskander_m"
    assert hit["method"] == "gazetteer"
    assert hit["confidence"] == 0.85
    assert "Iskander-M" in hit["evidence_span"]


def test_weapon_extraction_word_boundary_guard():
    # "Belgrade" must not match the BM-21 "grad" alias.
    assert extract_weapons("Protest reported in Belgrade city center.") == []
    assert extract_weapons("BM-21 Grad rockets hit the village.")[0]["weapon_key"] == "grad"


def test_weapon_extraction_cyrillic_alias():
    hits = extract_weapons("По городу выпущена ракета Искандер утром.")
    assert [h["weapon_key"] for h in hits] == ["iskander_m"]


# ------------------------------------------------------------------ dedupe


def test_category_compatibility_matrix():
    assert categories_compatible("airstrike", "missile_strike")
    assert categories_compatible("airstrike", "airstrike")
    assert not categories_compatible("airstrike", "protest")
    assert not categories_compatible("ied", "riot")


async def _ingest_one(session, unified):
    ids = await upsert_events(session, [unified])
    assert len(ids) == 1
    event = await session.get(Event, ids[0])
    from app.pipeline.enrich import enrich_event

    await enrich_event(session, event)
    await assign_cluster(session, event)
    return event


async def test_same_incident_clusters_across_sources(session):
    async with session.begin():
        acled_ev = normalize_acled(acled_row())
        first = await _ingest_one(session, acled_ev)
        gdelt_ev = normalize_gdelt(gdelt_cols())
        second = await _ingest_one(session, gdelt_ev)

        assert first.cluster_id is not None
        assert first.cluster_id == second.cluster_id

        cluster = await session.get(EventCluster, first.cluster_id)
        assert cluster.member_count == 2
        # ACLED outranks GDELT for representative.
        assert cluster.representative == first.id
        rep = await session.get(Event, cluster.representative)
        assert rep.source_count == 2
        assert cluster.reliability is not None and cluster.reliability > 0.7


async def test_incompatible_category_does_not_cluster(session):
    async with session.begin():
        strike = await _ingest_one(session, normalize_acled(acled_row()))
        protest = await _ingest_one(
            session,
            normalize_acled(
                acled_row(
                    event_id_cnty="UKR99999",
                    event_type="Protests",
                    sub_event_type="Peaceful protest",
                    notes="Residents gathered downtown in protest.",
                    actor1="Protesters (Ukraine)",
                    actor2="",
                )
            ),
        )
        assert strike.cluster_id != protest.cluster_id


async def test_distant_event_does_not_cluster(session):
    async with session.begin():
        near = await _ingest_one(session, normalize_acled(acled_row()))
        far = await _ingest_one(
            session,
            normalize_acled(
                acled_row(event_id_cnty="UKR55555", latitude="50.45", longitude="30.52")
            ),
        )  # Kyiv, ~410km away
        assert near.cluster_id != far.cluster_id


async def test_upsert_revision_does_not_duplicate(session):
    async with session.begin():
        first = await _ingest_one(session, normalize_acled(acled_row()))
    async with session.begin():
        revised = normalize_acled(acled_row(fatalities="5"))
        new_ids = await upsert_events(session, [revised])
        assert new_ids == []  # update, not insert
        count = (await session.execute(text("SELECT count(*) FROM events"))).scalar_one()
        assert count == 1
        refreshed = await session.get(Event, first.id)
        await session.refresh(refreshed)
        assert refreshed.fatalities == 5


# ------------------------------------------------------------- corroboration


async def test_thermal_corroboration_marks_cluster(session):
    async with session.begin():
        event = await _ingest_one(session, normalize_acled(acled_row()))
        cluster_id = event.cluster_id
        before = (await session.get(EventCluster, cluster_id)).reliability or 0.0
        session.add(
            FirmsHotspot(
                satellite="N",
                acquired_at=NOW + timedelta(hours=13),  # same reported day
                lat=49.995,
                lon=36.232,
                geom="SRID=4326;POINT(36.232 49.995)",
                frp=12.5,
                confidence="h",
                raw_payload={},
            )
        )
        await session.flush()
        changed = await corroborate_clusters(session)
        assert changed == 1
        cluster = await session.get(EventCluster, cluster_id)
        assert cluster.thermal_corroborated is True
        assert (cluster.reliability or 0.0) > before


async def test_far_hotspot_does_not_corroborate(session):
    async with session.begin():
        event = await _ingest_one(session, normalize_acled(acled_row()))
        session.add(
            FirmsHotspot(
                satellite="N",
                acquired_at=NOW + timedelta(hours=13),
                lat=50.45,
                lon=30.52,  # Kyiv, far away
                geom="SRID=4326;POINT(30.52 50.45)",
                raw_payload={},
            )
        )
        await session.flush()
        assert await corroborate_clusters(session) == 0
        cluster = await session.get(EventCluster, event.cluster_id)
        assert cluster.thermal_corroborated is False
