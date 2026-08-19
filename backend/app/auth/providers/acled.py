from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.auth.providers.base import ProviderError, RefreshRejected, RefreshStrategy, TokenSet

TOKEN_URL = "https://acleddata.com/oauth/token"
CLIENT_ID = "acled"


class AcledOAuthStrategy(RefreshStrategy):
    """ACLED OAuth: password grant for initial exchange, refresh_token grant thereafter.

    Access tokens last 24 hours; refresh tokens are longer-lived and may be
    rotated on every refresh (the returned refresh_token must always be persisted).
    """

    auth_type = "oauth_refresh"

    async def initial(self, http: httpx.AsyncClient, **credentials: Any) -> TokenSet:
        username = credentials["username"]
        password = credentials["password"]
        return await self._exchange(
            http,
            {
                "grant_type": "password",
                "username": username,
                "password": password,
                "client_id": CLIENT_ID,
            },
        )

    async def refresh(
        self, http: httpx.AsyncClient, refresh_token: str | None, extra: dict[str, Any] | None
    ) -> TokenSet:
        if not refresh_token:
            raise RefreshRejected("acled: no refresh token stored")
        return await self._exchange(
            http,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLIENT_ID,
            },
        )

    async def _exchange(self, http: httpx.AsyncClient, form: dict[str, str]) -> TokenSet:
        try:
            resp = await http.post(TOKEN_URL, data=form)
        except httpx.HTTPError as exc:
            raise ProviderError(f"acled token endpoint unreachable: {exc}") from exc
        if resp.status_code in (400, 401, 403):
            raise RefreshRejected(
                f"acled rejected credentials: {resp.status_code} {resp.text[:200]}"
            )
        if resp.status_code != 200:
            raise ProviderError(f"acled token endpoint returned {resp.status_code}")
        body = resp.json()
        expires_in = int(body.get("expires_in", 24 * 3600))
        now = datetime.now(UTC)
        return TokenSet(
            access_token=body["access_token"],
            access_expires_at=now + timedelta(seconds=expires_in),
            refresh_token=body.get("refresh_token"),
            # ACLED does not advertise refresh expiry; leave unset rather than guess.
            refresh_expires_at=None,
        )
