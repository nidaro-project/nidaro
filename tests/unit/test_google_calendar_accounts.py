from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from nidaro.connectors.crypto import SecretBox
from nidaro.connectors.google_calendar.accounts import (
    CONNECTOR_NAME,
    GoogleCalendarAccount,
    GoogleCalendarAccountRepository,
    GoogleCalendarAccountService,
)
from nidaro.connectors.service import ConnectorCredentialService
from nidaro.db.types import new_uuid, utc_now

TEST_KEY = Fernet.generate_key().decode()


class FakeAccountRepository(GoogleCalendarAccountRepository):
    def __init__(self):
        self.rows: dict[tuple[object, str], GoogleCalendarAccount] = {}

    async def get(self, household_id, email):
        return self.rows.get((household_id, email))

    async def list_for_household(self, household_id):
        return sorted(
            (row for key, row in self.rows.items() if key[0] == household_id),
            key=lambda row: row.google_email,
        )

    async def upsert(self, household_id, email, *, calendar_id, granted_scopes):
        row = self.rows.get((household_id, email))
        if row is None:
            row = GoogleCalendarAccount(
                id=new_uuid(),
                household_id=household_id,
                google_email=email,
                calendar_id=calendar_id,
                granted_scopes=granted_scopes,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            self.rows[(household_id, email)] = row
        else:
            row.calendar_id = calendar_id
            row.granted_scopes = granted_scopes
        return row

    async def delete(self, household_id, email):
        return self.rows.pop((household_id, email), None) is not None


class FakeCredentialRepository:
    def __init__(self):
        self.ciphertexts: dict[tuple[object, str, str], str] = {}

    async def get_ciphertext(self, household_id, connector, name):
        return self.ciphertexts.get((household_id, connector, name))

    async def save_ciphertext(self, household_id, connector, name, ciphertext):
        self.ciphertexts[(household_id, connector, name)] = ciphertext

    async def delete(self, household_id, connector, name):
        return self.ciphertexts.pop((household_id, connector, name), None) is not None

    async def names(self, household_id, connector):
        return sorted(
            key[2] for key in self.ciphertexts if key[0] == household_id and key[1] == connector
        )

    async def all(self):
        return []


def make_service():
    repository = FakeAccountRepository()
    credentials = ConnectorCredentialService(FakeCredentialRepository(), SecretBox(TEST_KEY))
    return GoogleCalendarAccountService(repository, credentials), credentials


@pytest.mark.anyio
async def test_register_stores_token_encrypted_and_row():
    service, credentials = make_service()
    household_id = uuid4()

    row = await service.register(
        household_id,
        "ada@example.com",
        "refresh-token-1",
        granted_scopes=["https://www.googleapis.com/auth/calendar.events"],
    )

    assert row.google_email == "ada@example.com"
    assert row.calendar_id == "primary"
    (ciphertext,) = credentials.repository.ciphertexts.values()
    assert ciphertext != "refresh-token-1"


@pytest.mark.anyio
async def test_register_overwrites_existing_account_in_place():
    service, _ = make_service()
    household_id = uuid4()
    await service.register(household_id, "ada@example.com", "old-token", calendar_id="primary")

    await service.register(household_id, "ada@example.com", "new-token", calendar_id="work")

    (account,) = await service.credentials_for_household(household_id)
    assert account.calendar_id == "work"
    assert account.refresh_token == "new-token"


@pytest.mark.anyio
async def test_credentials_for_household_decrypts_tokens():
    service, _ = make_service()
    household_id = uuid4()
    await service.register(household_id, "ben@example.com", "ben-token")
    await service.register(household_id, "ada@example.com", "ada-token")

    accounts = await service.credentials_for_household(household_id)

    assert [account.email for account in accounts] == ["ada@example.com", "ben@example.com"]
    assert {account.refresh_token for account in accounts} == {"ada-token", "ben-token"}


@pytest.mark.anyio
async def test_missing_credential_for_row_is_loud():
    service, credentials = make_service()
    household_id = uuid4()
    await service.register(household_id, "ada@example.com", "token")

    await credentials.delete(household_id, CONNECTOR_NAME, "ada@example.com")

    with pytest.raises(ValueError, match="reconnect"):
        await service.credentials_for_household(household_id)


@pytest.mark.anyio
async def test_forget_removes_row_and_credential():
    service, _ = make_service()
    household_id = uuid4()
    await service.register(household_id, "ada@example.com", "token")

    assert await service.forget(household_id, "ada@example.com") is True
    assert await service.credentials_for_household(household_id) == []
    assert await service.forget(household_id, "ada@example.com") is False
