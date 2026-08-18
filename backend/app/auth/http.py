import logging
from typing import Any

import httpx

from app.auth.manager import CredentialManager

logger = logging.getLogger(__name__)


class ProviderClient:
    """Reactive auth layer: inject the provider's token, and on a 401/403 force
    one refresh and retry the original request exactly once. One retry, never a loop.
    """

    def __init__(
        self,
        provider: str,
        manager: CredentialManager,
        http: httpx.AsyncClient,
        token_style: str = "bearer",  # 'bearer' header or 'query:<param_name>'
    ) -> None:
        self.provider = provider
        self._manager = manager
        self._http = http
        self._token_style = token_style

    def _apply_token(self, token: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        if self._token_style == "bearer":
            headers = dict(kwargs.get("headers") or {})
            headers["Authorization"] = f"Bearer {token}"
            kwargs["headers"] = headers
        elif self._token_style.startswith("query:"):
            param = self._token_style.split(":", 1)[1]
            params = dict(kwargs.get("params") or {})
            params[param] = token
            kwargs["params"] = params
        else:
            raise ValueError(f"unknown token style {self._token_style!r}")
        return kwargs

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        token = await self._manager.get_token(self.provider)
        resp = await self._http.request(method, url, **self._apply_token(token, dict(kwargs)))
        if resp.status_code not in (401, 403):
            return resp

        logger.info(
            "%s: got %d, forcing token refresh and retrying once", self.provider, resp.status_code
        )
        token = await self._manager.force_refresh(self.provider)
        resp = await self._http.request(method, url, **self._apply_token(token, dict(kwargs)))
        if resp.status_code in (401, 403):
            await self._manager.mark_degraded(
                self.provider, f"still {resp.status_code} after forced refresh"
            )
            resp.raise_for_status()
        return resp

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)
