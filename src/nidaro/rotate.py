"""Re-encrypt every stored connector credential with the primary key.

Run after moving NIDARO_CREDENTIAL_KEY to a new key (with the old key still
listed in NIDARO_CREDENTIAL_PREVIOUS_KEYS) and before dropping the old key.
See docs/deployment.md, "Rotating the connector credential key".
"""

import asyncio

from nidaro.config import get_settings
from nidaro.connectors.crypto import SecretBox
from nidaro.connectors.repository import ConnectorCredentialRepository
from nidaro.connectors.service import ConnectorCredentialService
from nidaro.db.engine import create_engine, create_session_factory


async def rotate() -> int:
    settings = get_settings()
    box = SecretBox.from_settings(settings)
    if box is None:
        raise SystemExit("NIDARO_CREDENTIAL_KEY is not configured — nothing to rotate with")
    engine = create_engine(settings)
    try:
        service = ConnectorCredentialService(
            ConnectorCredentialRepository(create_session_factory(engine)), box
        )
        return await service.rotate()
    finally:
        await engine.dispose()


def main() -> None:
    rotated = asyncio.run(rotate())
    print(f"re-encrypted {rotated} credential(s) with the primary key")
