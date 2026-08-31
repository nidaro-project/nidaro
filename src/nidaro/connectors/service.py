from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from nidaro.connectors.base import StaleCursorError
from nidaro.connectors.crypto import CredentialKeyMissing, SecretBox
from nidaro.connectors.models import (
    DEFAULT_POLL_SECONDS,
    ConnectorConfig,
    ConnectorContext,
    ConnectorCredential,
    ConnectorCursor,
    SyncResult,
)
from nidaro.connectors.registry import ConnectorRegistry
from nidaro.db.types import utc_now


class ConnectorCursorRepositoryProtocol(Protocol):
    async def get(self, household_id: UUID, connector: str) -> str | None: ...

    async def save(self, household_id: UUID, connector: str, cursor: str) -> ConnectorCursor: ...

    async def clear(self, household_id: UUID, connector: str) -> bool: ...


class ConnectorConfigRepositoryProtocol(Protocol):
    async def get(self, household_id: UUID, connector: str) -> ConnectorConfig | None: ...

    async def upsert(
        self,
        household_id: UUID,
        connector: str,
        *,
        enabled: bool,
        credential_names: list[str],
        trigger_word: str | None,
        poll_seconds: int,
    ) -> ConnectorConfig: ...

    async def enabled_for_household(self, household_id: UUID) -> list[ConnectorConfig]: ...

    async def all_enabled(self) -> list[ConnectorConfig]: ...

    async def stamp_synced(self, household_id: UUID, connector: str, at: datetime) -> bool: ...


class ConnectorService:
    def __init__(
        self,
        registry: ConnectorRegistry,
        cursors: ConnectorCursorRepositoryProtocol,
        configs: ConnectorConfigRepositoryProtocol | None = None,
    ) -> None:
        self.registry = registry
        self.cursors = cursors
        self.configs = configs

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

        When a config repository is wired, every completed run stamps
        `last_synced_at` on the household's config row — the basis on which
        the scheduler honors per-household cadence. A failed run does not
        stamp, so the config stays due on the next scheduler pass.
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
        if self.configs is not None:
            await self.configs.stamp_synced(household_id, name, utc_now())
        return result


class ConnectorConfigService:
    """Per-household connector onboarding, persisted in PostgreSQL.

    One `connector_configs` row per (household, connector): enabled flag,
    credential references (names stored via `ConnectorCredentialService.set`
    — identifiers, never secret material), the WhatsApp trigger word, and
    the polling cadence. `ConnectorService.sync` stamps `last_synced_at`,
    so `due` reflects runs no matter which path triggered them — worker,
    route, or assistant tool.
    """

    def __init__(self, repository: ConnectorConfigRepositoryProtocol) -> None:
        self.repository = repository

    async def enable(
        self,
        household_id: UUID,
        connector: str,
        *,
        credential_names: Sequence[str] = (),
        trigger_word: str | None = None,
        poll_seconds: int = DEFAULT_POLL_SECONDS,
    ) -> ConnectorConfig:
        """Onboard (or reconfigure) one connector for a household — one call.

        The arguments are the full desired intake and overwrite whatever the
        household had stored for the connector; a disabled row is re-enabled
        in place.
        """
        if poll_seconds < 1:
            raise ValueError(f"poll_seconds must be at least 1, got {poll_seconds}")
        return await self.repository.upsert(
            household_id,
            connector,
            enabled=True,
            credential_names=list(credential_names),
            trigger_word=trigger_word,
            poll_seconds=poll_seconds,
        )

    async def disable(self, household_id: UUID, connector: str) -> bool:
        """Disable the connector, keeping its intake for a later re-enable.

        Returns whether an enabled config was found and disabled.
        """
        row = await self.repository.get(household_id, connector)
        if row is None or not row.enabled:
            return False
        await self.repository.upsert(
            household_id,
            connector,
            enabled=False,
            credential_names=row.credential_names,
            trigger_word=row.trigger_word,
            poll_seconds=row.poll_seconds,
        )
        return True

    async def get(self, household_id: UUID, connector: str) -> ConnectorConfig | None:
        return await self.repository.get(household_id, connector)

    async def enabled(self, household_id: UUID) -> list[ConnectorConfig]:
        """Enabled connector configs for one household."""
        return await self.repository.enabled_for_household(household_id)

    async def due(self, now: datetime | None = None) -> list[ConnectorConfig]:
        """Enabled configs across all households whose cadence has elapsed.

        A config that has never synced is immediately due. The scheduler
        calls this without arguments and dispatches each returned config's
        connector for its household.
        """
        moment = utc_now() if now is None else now
        return [
            row
            for row in await self.repository.all_enabled()
            if row.last_synced_at is None
            or row.last_synced_at + timedelta(seconds=row.poll_seconds) <= moment
        ]


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
