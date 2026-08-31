"""Symmetric encryption for connector secrets.

`SecretBox` wraps `cryptography.fernet` (AES-128-CBC + HMAC-SHA256, versioned
token format). Key material comes from settings, never from source control:
`NIDARO_CREDENTIAL_KEY` is the primary key, `NIDARO_CREDENTIAL_PREVIOUS_KEYS`
holds comma-separated fallback keys that still decrypt while a rotation is in
flight. Because encryption happens before anything reaches the repository, the
database never sees plaintext — even SQL statement logging carries no secrets.
"""

from collections.abc import Sequence

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from nidaro.config import Settings

KEY_GENERATION_HINT = (
    "credential keys must be 32 url-safe base64-encoded bytes — generate one with: "
    'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
)


class CredentialKeyMissing(RuntimeError):
    """No NIDARO_CREDENTIAL_KEY is configured, so secrets cannot be used."""


class SecretBox:
    """Encrypts with the primary key; decrypts with primary or any fallback."""

    def __init__(self, primary_key: str, previous_keys: Sequence[str] = ()) -> None:
        try:
            self._fernet = MultiFernet([Fernet(key) for key in (primary_key, *previous_keys)])
        except ValueError as error:
            raise ValueError(KEY_GENERATION_HINT) from error

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as error:
            raise ValueError("credential was not encrypted with any configured key") from error

    @classmethod
    def from_settings(cls, settings: Settings) -> "SecretBox | None":
        """Build the box for the configured keys, or None when no key is set.

        None keeps the application bootable without a key; secret-reading and
        -writing calls fail at the service with `CredentialKeyMissing`.
        """
        if not settings.credential_key:
            return None
        previous = [
            key.strip() for key in settings.credential_previous_keys.split(",") if key.strip()
        ]
        return cls(settings.credential_key, previous)
