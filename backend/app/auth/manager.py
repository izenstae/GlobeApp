import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.crypto import TokenCipher
from app.auth.providers import REGISTRY
from app.auth.providers.base import RefreshRejected, RefreshStrategy, TokenSet
from app.models.credentials import (
    AUTH_STATIC_KEY,
    STATUS_ACTIVE,
    STATUS_DEAD,
    STATUS_DEGRADED,
    Credential,
)

logger = logging.getLogger(__name__)

# Refresh this far before actual expiry so an ingester never holds a token
# that dies mid-request.
EXPIRY_SKEW = timedelta(minutes=5)
# Proactive layer refreshes anything expiring within this window.
PROACTIVE_THRESHOLD = timedelta(hours=2)
# Backoff after refresh failures: 30s, 2m, 8m. After the third consecutive
# failure the credential is degraded (still retried on the proactive cadence).
BACKOFF_SECONDS = (30, 120, 480)
DEGRADED_AFTER_FAILURES = 3


class CredentialNotFound(Exception):
    pass


class CredentialDead(Exception):
    """Refresh token rejected or expired. Re-run `python -m app.auth.cli setup`."""


class CredentialManager:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cipher: TokenCipher | None = None,
        http: httpx.AsyncClient | None = None,
        strategies: dict[str, RefreshStrategy] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher or TokenCipher()
        self._http = http or httpx.AsyncClient(timeout=30)
        self._strategies = strategies if strategies is not None else REGISTRY
        self._now = now or (lambda: datetime.now(UTC))

    # ------------------------------------------------------------------ public

    async def get_token(self, provider: str) -> str:
        """Return a valid token, refreshing first if needed. Never returns expired."""
        async with self._session_factory() as session:
            cred = await self._load(session, provider)
            if cred.status == STATUS_DEAD:
                raise CredentialDead(
                    f"{provider}: credential is dead; run "
                    f"`python -m app.auth.cli setup --provider {provider}`"
                )
            if cred.auth_type == AUTH_STATIC_KEY:
                if not cred.access_token:
                    raise CredentialDead(f"{provider}: no key stored")
                return self._cipher.decrypt(cred.access_token)
            if self._is_fresh(cred):
                assert cred.access_token is not None
                return self._cipher.decrypt(cred.access_token)
        return await self._refresh_locked(provider, force=False)

    async def force_refresh(self, provider: str) -> str:
        """Refresh immediately regardless of expiry. Called by the 401 handler."""
        return await self._refresh_locked(provider, force=True)

    async def register(self, provider: str, **initial_credentials: Any) -> None:
        """First-time setup. Performs the initial exchange and persists only on success."""
        strategy = self._strategy(provider)
        tokens = await strategy.initial(self._http, **initial_credentials)
        async with self._session_factory() as session:
            async with session.begin():
                cred = await session.get(Credential, provider)
                if cred is None:
                    cred = Credential(provider=provider, auth_type=strategy.auth_type)
                    session.add(cred)
                cred.auth_type = strategy.auth_type
                self._apply_tokens(cred, tokens)
                cred.refresh_failures = 0
                cred.status = STATUS_ACTIVE

    async def status(self) -> list[Credential]:
        async with self._session_factory() as session:
            result = await session.execute(text("SELECT provider FROM api_credentials ORDER BY 1"))
            providers = [row[0] for row in result]
            return [await self._load(session, p) for p in providers]

    async def proactive_refresh_due(self) -> list[str]:
        """Providers whose access token expires within the proactive threshold."""
        due: list[str] = []
        now = self._now()
        for cred in await self.status():
            if cred.auth_type == AUTH_STATIC_KEY or cred.status == STATUS_DEAD:
                continue
            if cred.access_expires_at is None or (
                cred.access_expires_at - now < PROACTIVE_THRESHOLD
            ):
                due.append(cred.provider)
        return due

    @staticmethod
    def backoff_delay(refresh_failures: int) -> int:
        """Seconds to wait before the next retry, given consecutive failure count."""
        idx = min(refresh_failures, len(BACKOFF_SECONDS)) - 1
        return BACKOFF_SECONDS[max(idx, 0)]

    # ----------------------------------------------------------------- internal

    def _strategy(self, provider: str) -> RefreshStrategy:
        try:
            return self._strategies[provider]
        except KeyError:
            raise CredentialNotFound(f"no refresh strategy registered for {provider!r}") from None

    async def _load(self, session: AsyncSession, provider: str) -> Credential:
        cred = await session.get(Credential, provider)
        if cred is None:
            raise CredentialNotFound(
                f"{provider}: no credential stored; run "
                f"`python -m app.auth.cli setup --provider {provider}`"
            )
        return cred

    def _is_fresh(self, cred: Credential) -> bool:
        return bool(
            cred.access_token
            and cred.access_expires_at is not None
            and cred.access_expires_at > self._now() + EXPIRY_SKEW
        )

    def _apply_tokens(self, cred: Credential, tokens: TokenSet) -> None:
        cred.access_token = self._cipher.encrypt(tokens.access_token)
        cred.access_expires_at = tokens.access_expires_at
        # Refresh token rotation: always persist whatever came back. Never assume
        # the stored refresh token survives a refresh.
        if tokens.refresh_token is not None:
            cred.refresh_token = self._cipher.encrypt(tokens.refresh_token)
        if tokens.refresh_expires_at is not None:
            cred.refresh_expires_at = tokens.refresh_expires_at
        cred.last_refreshed_at = self._now()

    async def _refresh_locked(self, provider: str, force: bool) -> str:
        """Refresh under a Postgres advisory xact lock.

        The re-read inside the lock is the part that matters: without it we would
        serialize the stampede but still perform N redundant refreshes, and if the
        provider rotates refresh tokens, N-1 workers would then hold a dead one.
        """
        strategy = self._strategy(provider)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                        {"key": f"cred_refresh:{provider}"},
                    )
                    cred = await self._load(session, provider)
                    await session.refresh(cred)
                    if cred.status == STATUS_DEAD:
                        raise CredentialDead(
                            f"{provider}: credential is dead; run "
                            f"`python -m app.auth.cli setup --provider {provider}`"
                        )
                    if not force and self._is_fresh(cred):
                        # Another worker refreshed while we waited on the lock.
                        assert cred.access_token is not None
                        return self._cipher.decrypt(cred.access_token)

                    refresh_token = (
                        self._cipher.decrypt(cred.refresh_token) if cred.refresh_token else None
                    )
                    tokens = await strategy.refresh(self._http, refresh_token, cred.extra)
                    self._apply_tokens(cred, tokens)
                    cred.refresh_failures = 0
                    cred.status = STATUS_ACTIVE
                    return tokens.access_token
        except RefreshRejected as exc:
            # Failure bookkeeping happens in its own transaction: an exception
            # inside the locked transaction rolls that transaction back, so any
            # status change made there would be silently lost.
            logger.error("%s: refresh token rejected, credential dead: %s", provider, exc)
            await self._record_failure(provider, dead=True)
            raise CredentialDead(str(exc)) from exc
        except (CredentialDead, CredentialNotFound):
            raise
        except Exception as exc:
            logger.warning("%s: token refresh failed: %s", provider, exc)
            await self._record_failure(provider, dead=False)
            raise

    async def mark_degraded(self, provider: str, reason: str) -> None:
        logger.warning("%s: marked degraded: %s", provider, reason)
        await self._record_failure(provider, dead=False, force_degraded=True)

    async def _record_failure(
        self, provider: str, dead: bool, force_degraded: bool = False
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                cred = await session.get(Credential, provider)
                if cred is None:
                    return
                cred.refresh_failures += 1
                if dead:
                    cred.status = STATUS_DEAD
                elif force_degraded or cred.refresh_failures >= DEGRADED_AFTER_FAILURES:
                    cred.status = STATUS_DEGRADED

    async def aclose(self) -> None:
        await self._http.aclose()
