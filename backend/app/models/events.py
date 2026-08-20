from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

GEO_PRECISIONS = ("exact", "settlement", "admin2", "admin1", "country")
EVENT_CATEGORIES = (
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
)

geo_precision_enum = Enum(*GEO_PRECISIONS, name="geo_precision")
event_category_enum = Enum(*EVENT_CATEGORIES, name="event_category")


class EventCluster(Base):
    __tablename__ = "event_clusters"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    representative: Mapped[int | None] = mapped_column(BigInteger)
    first_seen: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    centroid: Mapped[Any | None] = mapped_column(Geography("POINT", srid=4326, spatial_index=False))
    reliability: Mapped[float | None] = mapped_column(Float)
    thermal_corroborated: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=text("false")
    )


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("source", "source_event_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    cluster_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("event_clusters.id"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, index=True
    )
    ingested_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    geom: Mapped[Any] = mapped_column(
        Geography("POINT", srid=4326, spatial_index=False), nullable=False
    )
    geo_precision: Mapped[str] = mapped_column(geo_precision_enum, nullable=False)
    geo_radius_m: Mapped[int | None] = mapped_column(Integer)
    country: Mapped[str | None] = mapped_column(Text)
    admin1: Mapped[str | None] = mapped_column(Text)
    location_name: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(event_category_enum, nullable=False, index=True)
    raw_event_type: Mapped[str | None] = mapped_column(Text)
    actor_a: Mapped[str | None] = mapped_column(Text)
    actor_b: Mapped[str | None] = mapped_column(Text)
    actor_a_canonical: Mapped[str | None] = mapped_column(Text)
    actor_b_canonical: Mapped[str | None] = mapped_column(Text)
    fatalities: Mapped[int | None] = mapped_column(Integer)
    headline: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    source_urls: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reliability: Mapped[float | None] = mapped_column(Float)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Strike origin for cross-border arc rendering (Phase 6). Populated only by
    # a stated derivation with method + confidence — never a guess presented as
    # fact. origin_method='actor_country_inference' means: the source attributed
    # the strike to a named state force whose country differs from the event
    # country; the origin is that country's centroid at country-level precision.
    origin_geom: Mapped[Any | None] = mapped_column(
        Geography("POINT", srid=4326, spatial_index=False)
    )
    origin_precision: Mapped[str | None] = mapped_column(geo_precision_enum)
    origin_country: Mapped[str | None] = mapped_column(Text)
    origin_method: Mapped[str | None] = mapped_column(Text)
    origin_confidence: Mapped[float | None] = mapped_column(Float)

    weapons: Mapped[list["EventWeapon"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", lazy="selectin"
    )


class EventWeapon(Base):
    __tablename__ = "event_weapons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    weapon_key: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)  # source_field|gazetteer|ner
    evidence_span: Mapped[str | None] = mapped_column(Text)

    event: Mapped[Event] = relationship(back_populates="weapons")


class FirmsHotspot(Base):
    """Thermal anomaly detections. Never promoted to events; overlay + corroboration only."""

    __tablename__ = "firms_hotspots"
    __table_args__ = (UniqueConstraint("satellite", "acquired_at", "lat", "lon"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    satellite: Mapped[str] = mapped_column(Text, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, index=True
    )
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    geom: Mapped[Any] = mapped_column(
        Geography("POINT", srid=4326, spatial_index=False), nullable=False
    )
    brightness: Mapped[float | None] = mapped_column(Float)
    frp: Mapped[float | None] = mapped_column(Float)  # fire radiative power, MW
    confidence: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class IngestWatermark(Base):
    """High-water mark per source so restarts resume instead of re-pulling."""

    __tablename__ = "ingest_watermarks"

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    watermark: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_ingested: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
