"""initial schema: extensions, credentials, events, clusters, weapons, hotspots, watermarks

Revision ID: 0001
Revises:
Create Date: 2026-08-18

"""

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

geo_precision = postgresql.ENUM(
    "exact", "settlement", "admin2", "admin1", "country", name="geo_precision", create_type=False
)
event_category = postgresql.ENUM(
    "airstrike",
    "artillery",
    "drone_strike",
    "missile_strike",
    "ied",
    "small_arms",
    "naval",
    "ground_assault",
    "protest",
    "riot",
    "abduction",
    "other_violence",
    "non_kinetic",
    name="event_category",
    create_type=False,
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "api_credentials",
        sa.Column("provider", sa.Text(), primary_key=True),
        sa.Column("auth_type", sa.Text(), nullable=False),
        sa.Column("access_token", sa.Text()),
        sa.Column("refresh_token", sa.Text()),
        sa.Column("access_expires_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("refresh_expires_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_refreshed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("refresh_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("extra", postgresql.JSONB()),
    )

    op.create_table(
        "event_clusters",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("representative", sa.BigInteger()),
        sa.Column("first_seen", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_seen", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "centroid",
            geoalchemy2.Geography("POINT", srid=4326, spatial_index=False),
        ),
        sa.Column("reliability", sa.Float()),
        sa.Column(
            "thermal_corroborated", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )

    geo_precision.create(op.get_bind(), checkfirst=True)
    event_category.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_event_id", sa.Text(), nullable=False),
        sa.Column("cluster_id", sa.BigInteger(), sa.ForeignKey("event_clusters.id")),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "geom", geoalchemy2.Geography("POINT", srid=4326, spatial_index=False), nullable=False
        ),
        sa.Column("geo_precision", geo_precision, nullable=False),
        sa.Column("geo_radius_m", sa.Integer()),
        sa.Column("country", sa.Text()),
        sa.Column("admin1", sa.Text()),
        sa.Column("location_name", sa.Text()),
        sa.Column("category", event_category, nullable=False),
        sa.Column("raw_event_type", sa.Text()),
        sa.Column("actor_a", sa.Text()),
        sa.Column("actor_b", sa.Text()),
        sa.Column("actor_a_canonical", sa.Text()),
        sa.Column("actor_b_canonical", sa.Text()),
        sa.Column("fatalities", sa.Integer()),
        sa.Column("headline", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("source_urls", postgresql.ARRAY(sa.Text())),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reliability", sa.Float()),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("source", "source_event_id"),
    )
    op.create_index("events_geom_idx", "events", ["geom"], postgresql_using="gist")
    op.create_index(
        "events_occurred_idx", "events", [sa.text("occurred_at DESC")], postgresql_using="btree"
    )
    op.create_index("events_cluster_idx", "events", ["cluster_id"])
    op.create_index("events_category_idx", "events", ["category"])

    op.create_table(
        "event_weapons",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("weapon_key", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text()),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("evidence_span", sa.Text()),
    )
    op.create_index("event_weapons_event_idx", "event_weapons", ["event_id"])

    op.create_table(
        "firms_hotspots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("satellite", sa.Text(), nullable=False),
        sa.Column("acquired_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column(
            "geom", geoalchemy2.Geography("POINT", srid=4326, spatial_index=False), nullable=False
        ),
        sa.Column("brightness", sa.Float()),
        sa.Column("frp", sa.Float()),
        sa.Column("confidence", sa.Text()),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("satellite", "acquired_at", "lat", "lon"),
    )
    op.create_index("firms_geom_idx", "firms_hotspots", ["geom"], postgresql_using="gist")
    op.create_index("firms_acquired_idx", "firms_hotspots", ["acquired_at"])

    op.create_table(
        "ingest_watermarks",
        sa.Column("source", sa.Text(), primary_key=True),
        sa.Column("watermark", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_success_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_attempt_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_ingested", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("ingest_watermarks")
    op.drop_table("firms_hotspots")
    op.drop_table("event_weapons")
    op.drop_table("events")
    op.drop_table("event_clusters")
    op.drop_table("api_credentials")
    event_category.drop(op.get_bind(), checkfirst=True)
    geo_precision.drop(op.get_bind(), checkfirst=True)
