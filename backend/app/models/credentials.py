from datetime import datetime
from typing import Any

from sqlalchemy import TIMESTAMP, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

STATUS_ACTIVE = "active"
STATUS_DEGRADED = "degraded"
STATUS_DEAD = "dead"

AUTH_OAUTH_REFRESH = "oauth_refresh"
AUTH_STATIC_KEY = "static_key"


class Credential(Base):
    __tablename__ = "api_credentials"

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    auth_type: Mapped[str] = mapped_column(Text, nullable=False)
    access_token: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted
    refresh_token: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted
    access_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    refresh_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_refreshed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    refresh_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=STATUS_ACTIVE)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
