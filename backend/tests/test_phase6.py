"""Phase 6: strike-origin inference (arcs), the actor/weapon/country filters,
and the UCDP baseline comparison."""

from app.api.analysis import ucdp_comparison
from app.api.events import filter_metadata, list_events
from app.pipeline.normalize import normalize_acled, normalize_gdelt, normalize_ucdp
from app.pipeline.origin import state_actor_country
from tests.test_ingest_ucdp import ucdp_row
from tests.test_pipeline import _ingest_one, acled_row, gdelt_cols

# ------------------------------------------------------------ origin inference


def test_state_actor_country_parsing():
    assert state_actor_country("Military Forces of Russia (2000-)") == "russia"
    assert state_actor_country("Military Forces of Russia (2000-) Air Force") == "russia"
    assert state_actor_country("Military Forces of the United States") == "united states"
    assert state_actor_country("Police Forces of Iran (1979-)") == "iran"
    assert state_actor_country("Wagner Group") is None
    assert state_actor_country("Military Forces of Atlantis") is None  # not in centroid table
    assert state_actor_country(None) is None


async def test_cross_border_airstrike_gets_inferred_origin(session):
    async with session.begin():
        event = await _ingest_one(session, normalize_acled(acled_row()))
        assert event.origin_country == "Russia"
        assert event.origin_precision == "country"
        assert event.origin_method == "actor_country_inference"
        assert event.origin_confidence == 0.5
        assert event.origin_geom is not None


async def test_domestic_and_nonstrike_events_get_no_origin(session):
    async with session.begin():
        # Same-country actor: no arc, whatever the category.
        domestic = await _ingest_one(
            session,
            normalize_acled(
                acled_row(
                    event_id_cnty="UKR20001",
                    actor1="Military Forces of Ukraine (2019-)",
                    notes="Ukrainian air defense engaged targets over the city.",
                )
            ),
        )
        assert domestic.origin_country is None
        # Cross-border actor but a non-remote category: no arc.
        clash = await _ingest_one(
            session,
            normalize_acled(
                acled_row(
                    event_id_cnty="UKR20002",
                    event_type="Battles",
                    sub_event_type="Armed clash",
                    notes="Ground fighting near the border settlement.",
                )
            ),
        )
        assert clash.category == "ground_assault"
        assert clash.origin_country is None


# ------------------------------------------------------------------ filters


async def _seed_two_countries(session):
    kharkiv = await _ingest_one(session, normalize_acled(acled_row()))
    gaza = await _ingest_one(
        session,
        normalize_acled(
            acled_row(
                event_id_cnty="PSE00001",
                country="Palestine",
                admin1="Gaza Strip",
                location="Gaza",
                latitude="31.5",
                longitude="34.46",
                actor1="Military Forces of Israel (2022-)",
                actor2="Hamas Movement",
                notes="Airstrike reported in Gaza city.",
            )
        ),
    )
    return kharkiv, gaza


async def _list(session, **kwargs):
    args = dict(
        bbox=None,
        since=None,
        until=None,
        category=None,
        country=None,
        actor=None,
        weapon=None,
        min_reliability=None,
        limit=2000,
        session=session,
    )
    args.update(kwargs)
    body = await list_events(**args)
    return body["events"]


async def test_country_filter(session):
    async with session.begin():
        await _seed_two_countries(session)
    rows = await _list(session, country=["ukraine"])
    assert [r["country"] for r in rows] == ["Ukraine"]
    rows = await _list(session, country=["Ukraine", "Palestine"])
    assert len(rows) == 2


async def test_actor_filter_matches_raw_and_canonical(session):
    async with session.begin():
        await _seed_two_countries(session)
    rows = await _list(session, actor="Hamas")
    assert len(rows) == 1
    assert rows[0]["country"] == "Palestine"
    rows = await _list(session, actor="military forces")
    assert len(rows) == 2


async def test_weapon_filter_matches_cluster_members(session):
    async with session.begin():
        kharkiv, _ = await _seed_two_countries(session)
        # A GDELT member of the same cluster carries no weapon text; the
        # representative's gazetteer hit must still satisfy the filter.
        gdelt_member = await _ingest_one(session, normalize_gdelt(gdelt_cols()))
        assert gdelt_member.cluster_id == kharkiv.cluster_id
    rows = await _list(session, weapon=["iskander_m"])
    assert len(rows) == 1
    assert rows[0]["cluster_id"] == kharkiv.cluster_id
    assert await _list(session, weapon=["shahed_136"]) == []


async def test_events_rows_carry_origin_fields(session):
    async with session.begin():
        await _seed_two_countries(session)
    rows = await _list(session, country=["Ukraine"])
    assert rows[0]["origin_country"] == "Russia"
    assert rows[0]["origin_lat"] is not None
    assert rows[0]["origin_method"] == "actor_country_inference"


async def test_filter_metadata_lists_only_ingested_vocabulary(session):
    async with session.begin():
        await _seed_two_countries(session)
    meta = await filter_metadata(session=session)
    assert set(meta["countries"]) == {"Ukraine", "Palestine"}
    assert "Hamas Movement" in meta["actors"]
    keys = [w["weapon_key"] for w in meta["weapons"]]
    assert "iskander_m" in keys
    assert all(w["event_count"] >= 1 for w in meta["weapons"])


# ------------------------------------------------------------- UCDP baseline


async def test_ucdp_comparison_empty_state(session):
    body = await ucdp_comparison(month=None, session=session)
    assert body["available"] is False


async def test_ucdp_comparison_counts_matches(session):
    async with session.begin():
        # Pipeline event and a UCDP baseline event ~300 m and same day apart.
        await _ingest_one(session, normalize_acled(acled_row()))
        await _ingest_one(session, normalize_ucdp(ucdp_row()))
        # A UCDP event nothing in the pipeline saw (far away).
        await _ingest_one(
            session,
            normalize_ucdp(ucdp_row(id=411099, latitude=12.0, longitude=15.0, country="Chad")),
        )
    body = await ucdp_comparison(month="2026-08", session=session)
    assert body["available"] is True
    assert body["ucdp_events"] == 2
    assert body["ucdp_matched_by_pipeline"] == 1
    assert body["match_rate"] == 0.5
    assert body["pipeline_incidents"] == 1
    by_country = {r["country"]: r for r in body["by_country"]}
    assert by_country["Ukraine"]["matched_by_pipeline"] == 1
