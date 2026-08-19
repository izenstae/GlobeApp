import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.auth.crypto import TokenCipher
from app.auth.http import ProviderClient
from app.auth.manager import (
    PROACTIVE_THRESHOLD,
    CredentialDead,
    CredentialManager,
)
from app.auth.providers.base import ProviderError, RefreshRejected, RefreshStrategy, TokenSet
from app.models.credentials import (
    AUTH_OAUTH_REFRESH,
    STATUS_ACTIVE,
    STATUS_DEAD,
    STATUS_DEGRADED,
    Credential,
)


def now() -> datetime:
    return datetime.now(UTC)


class FakeStrategy(RefreshStrategy):
    """Counts provider calls; configurable rotation, latency, and failure mode."""

    auth_type = AUTH_OAUTH_REFRESH

    def __init__(
        self,
        rotate_to: str | None = None,
        delay: float = 0.0,
        fail_with: Exception | None = None,
    ) -> None:
        self.refresh_calls = 0
        self.initial_calls = 0
        self.rotate_to = rotate_to
        self.delay = delay
        self.fail_with = fail_with
        self.seen_refresh_tokens: list[str | None] = []

    async def initial(self, http: httpx.AsyncClient, **credentials: Any) -> TokenSet:
        self.initial_calls += 1
        return TokenSet(
            access_token="access-0",
            access_expires_at=now() + timedelta(hours=24),
            refresh_token="refresh-0",
        )

    async def refresh(
        self, http: httpx.AsyncClient, refresh_token: str | None, extra: dict[str, Any] | None
    ) -> TokenSet:
        self.refresh_calls += 1
        self.seen_refresh_tokens.append(refresh_token)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_with is not None:
            raise self.fail_with
        return TokenSet(
            access_token=f"access-{self.refresh_calls}",
            access_expires_at=now() + timedelta(hours=24),
            refresh_token=self.rotate_to,
        )


async def seed_credential(
    session_factory,
    cipher: TokenCipher,
    provider: str = "test",
    access_token: str = "old-access",
    refresh_token: str = "old-refresh",
    expires_in: timedelta = timedelta(hours=-1),
    status: str = STATUS_ACTIVE,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(
                Credential(
                    provider=provider,
                    auth_type=AUTH_OAUTH_REFRESH,
                    access_token=cipher.encrypt(access_token),
                    refresh_token=cipher.encrypt(refresh_token),
                    access_expires_at=now() + expires_in,
                    refresh_failures=0,
                    status=status,
                )
            )


def make_manager(
    session_factory, strategy: RefreshStrategy
) -> tuple[CredentialManager, TokenCipher]:
    cipher = TokenCipher()
    manager = CredentialManager(session_factory, cipher=cipher, strategies={"test": strategy})
    return manager, cipher


async def load_credential(session_factory, provider: str = "test") -> Credential:
    async with session_factory() as session:
        cred = await session.get(Credential, provider)
        assert cred is not None
        return cred


# ---------------------------------------------------------------- proactive


async def test_proactive_refresh_fires_at_threshold(session_factory):
    strategy = FakeStrategy()
    manager, cipher = make_manager(session_factory, strategy)

    # Comfortably outside the 2h threshold: not due.
    await seed_credential(
        session_factory, cipher, expires_in=PROACTIVE_THRESHOLD + timedelta(minutes=30)
    )
    assert await manager.proactive_refresh_due() == []

    # Inside the threshold: due.
    async with session_factory() as session:
        async with session.begin():
            cred = await session.get(Credential, "test")
            cred.access_expires_at = now() + PROACTIVE_THRESHOLD - timedelta(minutes=30)
    assert await manager.proactive_refresh_due() == ["test"]

    await manager.force_refresh("test")
    assert strategy.refresh_calls == 1
    assert await manager.proactive_refresh_due() == []
    await manager.aclose()


# ---------------------------------------------------------------- reactive 401


async def test_401_triggers_exactly_one_retry(session_factory):
    strategy = FakeStrategy(rotate_to="rt-next")
    manager, cipher = make_manager(session_factory, strategy)
    await seed_credential(session_factory, cipher, expires_in=timedelta(hours=12))

    api_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls
        api_calls += 1
        auth = request.headers.get("Authorization", "")
        if auth == "Bearer access-1":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(401)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = ProviderClient("test", manager, http)

    resp = await client.get("https://api.example.test/data")
    assert resp.status_code == 200
    assert api_calls == 2  # original + exactly one retry
    assert strategy.refresh_calls == 1
    await http.aclose()
    await manager.aclose()


async def test_401_after_retry_marks_degraded_and_raises(session_factory):
    strategy = FakeStrategy()
    manager, cipher = make_manager(session_factory, strategy)
    await seed_credential(session_factory, cipher, expires_in=timedelta(hours=12))

    api_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls
        api_calls += 1
        return httpx.Response(401)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = ProviderClient("test", manager, http)

    with pytest.raises(httpx.HTTPStatusError):
        await client.get("https://api.example.test/data")
    assert api_calls == 2  # never a loop
    assert strategy.refresh_calls == 1
    cred = await load_credential(session_factory)
    assert cred.status == STATUS_DEGRADED
    await http.aclose()
    await manager.aclose()


# ---------------------------------------------------------------- concurrency


async def test_concurrent_refreshes_make_one_provider_call(session_factory):
    strategy = FakeStrategy(rotate_to="rt-rotated", delay=0.2)
    manager, cipher = make_manager(session_factory, strategy)
    await seed_credential(session_factory, cipher, expires_in=timedelta(minutes=-5))

    tokens = await asyncio.gather(*(manager.get_token("test") for _ in range(4)))

    assert strategy.refresh_calls == 1
    assert set(tokens) == {"access-1"}
    await manager.aclose()


# ---------------------------------------------------------------- rotation


async def test_rotated_refresh_token_is_persisted(session_factory):
    strategy = FakeStrategy(rotate_to="rt-rotated")
    manager, cipher = make_manager(session_factory, strategy)
    await seed_credential(session_factory, cipher, refresh_token="rt-original")

    await manager.get_token("test")

    cred = await load_credential(session_factory)
    assert cipher.decrypt(cred.refresh_token) == "rt-rotated"
    # And the next refresh presents the rotated token, not the original.
    await manager.force_refresh("test")
    assert strategy.seen_refresh_tokens == ["rt-original", "rt-rotated"]
    await manager.aclose()


async def test_refresh_without_rotation_keeps_stored_token(session_factory):
    strategy = FakeStrategy(rotate_to=None)  # provider returns no refresh_token
    manager, cipher = make_manager(session_factory, strategy)
    await seed_credential(session_factory, cipher, refresh_token="rt-original")

    await manager.get_token("test")

    cred = await load_credential(session_factory)
    assert cipher.decrypt(cred.refresh_token) == "rt-original"
    await manager.aclose()


# ---------------------------------------------------------------- failure paths


async def test_dead_credential_degrades_without_crashing(session_factory):
    strategy = FakeStrategy(fail_with=RefreshRejected("refresh token expired"))
    manager, cipher = make_manager(session_factory, strategy)
    await seed_credential(session_factory, cipher)

    with pytest.raises(CredentialDead):
        await manager.get_token("test")

    cred = await load_credential(session_factory)
    assert cred.status == STATUS_DEAD

    # Dead credential short-circuits: no further provider calls, no crash.
    with pytest.raises(CredentialDead):
        await manager.get_token("test")
    assert strategy.refresh_calls == 1

    # The rest of the credential store keeps serving.
    statuses = await manager.status()
    assert [c.status for c in statuses] == [STATUS_DEAD]
    await manager.aclose()


async def test_transient_failures_escalate_to_degraded(session_factory):
    strategy = FakeStrategy(fail_with=ProviderError("boom"))
    manager, cipher = make_manager(session_factory, strategy)
    await seed_credential(session_factory, cipher)

    for expected_failures in (1, 2, 3):
        with pytest.raises(ProviderError):
            await manager.get_token("test")
        cred = await load_credential(session_factory)
        assert cred.refresh_failures == expected_failures

    assert cred.status == STATUS_DEGRADED

    # Recovery resets the counter and reactivates.
    strategy.fail_with = None
    token = await manager.get_token("test")
    assert token == "access-4"
    cred = await load_credential(session_factory)
    assert cred.status == STATUS_ACTIVE
    assert cred.refresh_failures == 0
    await manager.aclose()


def test_backoff_schedule():
    assert CredentialManager.backoff_delay(1) == 30
    assert CredentialManager.backoff_delay(2) == 120
    assert CredentialManager.backoff_delay(3) == 480
    assert CredentialManager.backoff_delay(7) == 480
