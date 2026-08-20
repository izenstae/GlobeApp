"""strike origin columns for arc rendering + country index for filters

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-20

"""

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

geo_precision = postgresql.ENUM(
    "exact", "settlement", "admin2", "admin1", "country", name="geo_precision", create_type=False
)


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("origin_geom", geoalchemy2.Geography("POINT", srid=4326, spatial_index=False)),
    )
    op.add_column("events", sa.Column("origin_precision", geo_precision))
    op.add_column("events", sa.Column("origin_country", sa.Text()))
    op.add_column("events", sa.Column("origin_method", sa.Text()))
    op.add_column("events", sa.Column("origin_confidence", sa.Float()))
    op.create_index("events_country_idx", "events", ["country"])


def downgrade() -> None:
    op.drop_index("events_country_idx", table_name="events")
    op.drop_column("events", "origin_confidence")
    op.drop_column("events", "origin_method")
    op.drop_column("events", "origin_country")
    op.drop_column("events", "origin_precision")
    op.drop_column("events", "origin_geom")
