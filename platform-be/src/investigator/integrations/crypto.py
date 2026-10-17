from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from investigator.integrations.errors import OAuthError


class TokenCipher:
    """Symmetric encryption for stored credentials. The key never leaves the server."""

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            raise ValueError("TOKEN_ENCRYPTION_KEY is not a valid Fernet key.") from exc

    def seal(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def open(self, blob: bytes) -> str:
        try:
            return self._fernet.decrypt(blob).decode()
        except InvalidToken as exc:
            # Wrong key or corrupted row: treat as unusable rather than guessing.
            raise OAuthError(
                "credentials_unreadable", "Stored credentials cannot be decrypted."
            ) from exc
