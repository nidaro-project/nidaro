from typing import Protocol
from uuid import UUID

from nidaro.connectors.base import StaleCursorError
from nidaro.connectors.crypto import CredentialKeyMissing, SecretBox
from nidaro.connectors.models import (
    ConnectorContext,
    ConnectorCredential,
    ConnectorCursor,
    SyncResult,
)
from nidaro.connectors.registry import ConnectorRegistry


class ConnectorCursorRepositoryProtocol(Protocol):
    async def get(self, household_id: UUID, connector: str) -> str | None: ...

    async def save(self, household_id: UUID, connector: str, cursor: str) -> ConnectorCursor: ...

    async def clear(self, household_id: UUID, connector: str) -> bool: ...


class ConnectorService:
    def __init__(
        self, registry: ConnectorRegistry, cursors: ConnectorCursorRepositoryProtocol
    ) -> None:
        self.registry = registry
        self.cursors = cursors

    async def sync(
        self, name: str, context: ConnectorContext, cursor: str | None = None
    ) -> SyncResult:
        """Run one connector sync for a household, persisting its high-water mark.

        With `cursor=None` the stored cursor for (household, connector) is used,
        so callers do not track cursors across runs or service restarts. An
        explicit `cursor` argument overrides the stored one. A connector that
        rejects the stored cursor raises `StaleCursorError`; the stored cursor
        is cleared before the error propagates, making the next sync start
        fresh. A run without a `next_cursor` leaves the stored cursor as-is.
        """
        household_id = UUID(context.household_id)
        effective = cursor if cursor is not None else await self.cursors.get(household_id, name)
        try:
            result = await self.registry.get(name).sync(context, effective)
        except StaleCursorError:
            await self.cursors.clear(household_id, name)
            raise
        if result.next_cursor is not None:
            await self.cursors.save(household_id, name, result.next_cursor)
        return result


class ConnectorCredentialRepositoryProtocol(Protocol):
    async def get_ciphertext(self, household_id: UUID, connector: str, name: str) -> str | None: ...

    async def save_ciphertext(
        self, household_id: UUID, connector: str, name: str, ciphertext: str
    ) -> ConnectorCredential: ...

    async def delete(self, household_id: UUID, connector: str, name: str) -> bool: ...

    async def names(self, household_id: UUID, connector: str) -> list[str]: ...

    async def all(self) -> list[ConnectorCredential]: ...


class ConnectorCredentialService:
    """Connector secrets, encrypted at rest.

    The repository only ever sees ciphertext: plaintext exists in method
    arguments and return values, never in a table column, log line, or
    migration. Key material comes from settings (`NIDARO_CREDENTIAL_KEY`,
    `NIDARO_CREDENTIAL_PREVIOUS_KEYS`); without a key, every call that reads
    or writes a secret raises `CredentialKeyMissing` while metadata calls
    (`delete`, `names`) keep working.
    """

    def __init__(
        self, repository: ConnectorCredentialRepositoryProtocol, box: SecretBox | None
    ) -> None:
        self.repository = repository
        self.box = box

    async def set(
        self, household_id: UUID, connector: str, name: str, secret: str
    ) -> ConnectorCredential:
        """Encrypt and store (or overwrite) one secret; returns the stored row."""
        box = self._require_box()
        return await self.repository.save_ciphertext(
            household_id, connector, name, box.encrypt(secret)
        )

    async def get(self, household_id: UUID, connector: str, name: str) -> str | None:
        """Return the decrypted secret, or None when nothing is stored."""
        box = self._require_box()
        ciphertext = await self.repository.get_ciphertext(household_id, connector, name)
        return None if ciphertext is None else box.decrypt(ciphertext)

    async def delete(self, household_id: UUID, connector: str, name: str) -> bool:
        return await self.repository.delete(household_id, connector, name)

    async def names(self, household_id: UUID, connector: str) -> list[str]:
        """Stored credential names for one household+connector — no secrets."""
        return await self.repository.names(household_id, connector)

    async def rotate(self) -> int:
        """Re-encrypt every stored secret with the primary key.

        Run while the previous key is still configured as a fallback; once
        this returns, the old key can be dropped from settings (see
        docs/deployment.md, "Rotating the connector credential key").
        Returns the number of rows rewritten.
        """
        box = self._require_box()
        rows = await self.repository.all()
        for row in rows:
            try:
                plaintext = box.decrypt(row.secret)
            except ValueError as error:
                raise ValueError(
                    f"credential {row.connector}/{row.name} for household "
                    f"{row.household_id} was not encrypted with any configured key"
                ) from error
            await self.repository.save_ciphertext(
                row.household_id, row.connector, row.name, box.encrypt(plaintext)
            )
        return len(rows)

    def _require_box(self) -> SecretBox:
        if self.box is None:
            raise CredentialKeyMissing(
                "NIDARO_CREDENTIAL_KEY is not configured; connector secrets are unavailable"
            )
        return self.box
