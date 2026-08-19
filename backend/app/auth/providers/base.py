from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx


class ProviderError(Exception):
    """Transient provider failure (network, 5xx). Retryable with backoff."""


class RefreshRejected(ProviderError):
    """The provider rejected the refresh token itself. Not retryable: credential is dead."""


@dataclass
class TokenSet:
    access_token: str
    access_expires_at: datetime | None
    refresh_token: str | None = None  # provider may rotate; always persist when present
    refresh_expires_at: datetime | None = None
    extra: dict[str, Any] | None = None


class RefreshStrategy(ABC):
    """One refresh strategy per provider. Strategies are stateless; state lives in the DB."""

    auth_type: str = "oauth_refresh"

    @abstractmethod
    async def initial(self, http: httpx.AsyncClient, **credentials: Any) -> TokenSet:
        """First-time exchange from user-supplied credentials. Must validate for real."""

    @abstractmethod
    async def refresh(
        self, http: httpx.AsyncClient, refresh_token: str | None, extra: dict[str, Any] | None
    ) -> TokenSet:
        """Exchange the refresh token for a fresh TokenSet."""
