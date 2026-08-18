from cryptography.fernet import Fernet

from app.config import get_settings


class TokenCipher:
    """Fernet encryption for tokens at rest, keyed by CREDENTIAL_ENCRYPTION_KEY."""

    def __init__(self, key: str | None = None) -> None:
        key = key or get_settings().credential_encryption_key
        if not key or key == "CHANGE_ME_FERNET_KEY":
            raise RuntimeError(
                "CREDENTIAL_ENCRYPTION_KEY is not set. Generate one with:\n"
                '  python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"\n'
                "and put it in .env (never commit it)."
            )
        self._fernet = Fernet(key.encode())

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode()).decode()
