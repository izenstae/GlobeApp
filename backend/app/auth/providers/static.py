from typing import Any

import httpx

from app.auth.providers.base import ProviderError, RefreshRejected, RefreshStrategy, TokenSet


class StaticKeyStrategy(RefreshStrategy):
    """Providers with a non-rotating API key (e.g. NASA FIRMS).

    The key is stored encrypted in access_token with no expiry; refresh is a no-op.
    Initial setup validates the key against a cheap endpoint so we never store
    credentials we have not seen work.
    """

    auth_type = "static_key"

    def __init__(self, validate_url: str | None = None, key_param: str = "key") -> None:
        self.validate_url = validate_url
        self.key_param = key_param

    async def initial(self, http: httpx.AsyncClient, **credentials: Any) -> TokenSet:
        key = credentials["api_key"]
        if self.validate_url:
            try:
                resp = await http.get(self.validate_url, params={self.key_param: key})
            except httpx.HTTPError as exc:
                raise ProviderError(f"key validation endpoint unreachable: {exc}") from exc
            if resp.status_code in (401, 403):
                raise RefreshRejected(f"provider rejected the API key: {resp.status_code}")
            if resp.status_code >= 500:
                raise ProviderError(f"key validation endpoint returned {resp.status_code}")
        return TokenSet(access_token=key, access_expires_at=None)

    async def refresh(
        self, http: httpx.AsyncClient, refresh_token: str | None, extra: dict[str, Any] | None
    ) -> TokenSet:
        raise RefreshRejected("static keys cannot be refreshed; re-run setup with a new key")
