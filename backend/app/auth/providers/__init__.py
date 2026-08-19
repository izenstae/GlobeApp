from app.auth.providers.acled import AcledOAuthStrategy
from app.auth.providers.base import ProviderError, RefreshRejected, RefreshStrategy, TokenSet
from app.auth.providers.static import StaticKeyStrategy

REGISTRY: dict[str, RefreshStrategy] = {
    "acled": AcledOAuthStrategy(),
    "firms": StaticKeyStrategy(
        validate_url="https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/",
        key_param="MAP_KEY",
    ),
    # GDELT's 15-minute update files need no credentials at all.
}

__all__ = [
    "REGISTRY",
    "ProviderError",
    "RefreshRejected",
    "RefreshStrategy",
    "TokenSet",
    "AcledOAuthStrategy",
    "StaticKeyStrategy",
]
