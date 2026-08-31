from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet

from nidaro.config import Settings
from nidaro.connectors.crypto import CredentialKeyMissing, SecretBox
from nidaro.connectors.models import ConnectorCredential
from nidaro.connectors.service import ConnectorCredentialService
from nidaro.db.types import new_uuid, utc_now

SECRET = "oauth-refresh-token-for-unit-tests-only"


class FakeCredentialRepository:
    def __init__(self):
        self.rows: dict[tuple[UUID, str, str], ConnectorCredential] = {}

    async def get_ciphertext(self, household_id, connector, name):
        row = self.rows.get((household_id, connector, name))
        return row.secret if row else None

    async def save_ciphertext(self, household_id, connector, name, ciphertext):
        row = self.rows.get((household_id, connector, name))
        if row is None:
            row = ConnectorCredential(
                id=new_uuid(),
                household_id=household_id,
                connector=connector,
                name=name,
                secret=ciphertext,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            self.rows[(household_id, connector, name)] = row
        else:
            row.secret = ciphertext
            row.updated_at = utc_now()
        return row

    async def delete(self, household_id, connector, name):
        return self.rows.pop((household_id, connector, name), None) is not None

    async def names(self, household_id, connector):
        return sorted(
            self.rows[key].name
            for key in self.rows
            if key[0] == household_id and key[1] == connector
        )

    async def all(self):
        return list(self.rows.values())


def make_box(keys: int = 1) -> tuple[SecretBox, list[str]]:
    generated = [Fernet.generate_key().decode() for _ in range(keys)]
    return SecretBox(generated[0], generated[1:]), generated


def make_service(key_list: list[str]) -> ConnectorCredentialService:
    return ConnectorCredentialService(
        FakeCredentialRepository(), SecretBox(key_list[0], key_list[1:])
    )


@pytest.mark.anyio
async def test_set_then_get_round_trips_secret():
    service = make_service([Fernet.generate_key().decode()])
    household_id = uuid4()

    await service.set(household_id, "bakalari", "emma", SECRET)

    assert await service.get(household_id, "bakalari", "emma") == SECRET


@pytest.mark.anyio
async def test_repository_sees_only_ciphertext():
    repository = FakeCredentialRepository()
    service = ConnectorCredentialService(repository, SecretBox(Fernet.generate_key().decode()))
    household_id = uuid4()

    await service.set(household_id, "icloud", "app-password", SECRET)

    (row,) = repository.rows.values()
    assert row.secret != SECRET
    assert SECRET not in row.secret


@pytest.mark.anyio
async def test_get_missing_returns_none():
    service = make_service([Fernet.generate_key().decode()])

    assert await service.get(uuid4(), "bakalari", "nobody") is None


@pytest.mark.anyio
async def test_set_overwrites_in_place():
    repository = FakeCredentialRepository()
    service = ConnectorCredentialService(repository, SecretBox(Fernet.generate_key().decode()))
    household_id = uuid4()

    first = await service.set(household_id, "bakalari", "emma", SECRET)
    second = await service.set(household_id, "bakalari", "emma", "rotated-secret")

    assert first.id == second.id
    assert len(repository.rows) == 1
    assert await service.get(household_id, "bakalari", "emma") == "rotated-secret"


@pytest.mark.anyio
async def test_same_name_isolated_across_connectors_and_households():
    service = make_service([Fernet.generate_key().decode()])
    household_a, household_b = uuid4(), uuid4()

    await service.set(household_a, "bakalari", "emma", SECRET)
    await service.set(household_a, "gcal", "emma", "google-token")
    await service.set(household_b, "bakalari", "emma", "other-household-token")

    assert await service.get(household_a, "bakalari", "emma") == SECRET
    assert await service.get(household_a, "gcal", "emma") == "google-token"
    assert await service.get(household_b, "bakalari", "emma") == "other-household-token"


@pytest.mark.anyio
async def test_delete_reports_presence():
    service = make_service([Fernet.generate_key().decode()])
    household_id = uuid4()
    await service.set(household_id, "bakalari", "emma", SECRET)

    assert await service.delete(household_id, "bakalari", "emma")
    assert not await service.delete(household_id, "bakalari", "emma")
    assert await service.get(household_id, "bakalari", "emma") is None


@pytest.mark.anyio
async def test_names_lists_metadata_without_secrets():
    repository = FakeCredentialRepository()
    service = ConnectorCredentialService(repository, SecretBox(Fernet.generate_key().decode()))
    household_id = uuid4()
    await service.set(household_id, "bakalari", "leo", SECRET)
    await service.set(household_id, "bakalari", "emma", SECRET)

    assert await service.names(household_id, "bakalari") == ["emma", "leo"]
    assert SECRET not in str(repository.rows)


@pytest.mark.anyio
async def test_rotate_rewrites_rows_under_new_primary():
    old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    repository = FakeCredentialRepository()
    await ConnectorCredentialService(repository, SecretBox(old_key)).set(
        uuid4(), "bakalari", "emma", SECRET
    )
    rotating = ConnectorCredentialService(repository, SecretBox(new_key, [old_key]))

    assert await rotating.rotate() == 1

    primary = SecretBox(new_key)
    (row,) = repository.rows.values()
    assert primary.decrypt(row.secret) == SECRET
    stranded = ConnectorCredentialService(repository, SecretBox(old_key))
    with pytest.raises(ValueError, match="any configured key"):
        await stranded.get(row.household_id, "bakalari", "emma")


@pytest.mark.anyio
async def test_rotate_is_idempotent_and_reports_count():
    keys = [Fernet.generate_key().decode() for _ in range(2)]
    repository = FakeCredentialRepository()
    service = ConnectorCredentialService(repository, SecretBox(keys[0], keys[1:]))
    household_id = uuid4()
    await service.set(household_id, "bakalari", "emma", SECRET)
    await service.set(household_id, "gcal", "refresh", "another-secret")

    assert await service.rotate() == 2
    assert await service.rotate() == 2
    assert len(repository.rows) == 2
    assert await service.get(household_id, "gcal", "refresh") == "another-secret"


@pytest.mark.anyio
async def test_rotate_names_the_row_but_never_the_secret():
    repository = FakeCredentialRepository()
    service = ConnectorCredentialService(repository, SecretBox(Fernet.generate_key().decode()))
    household_id = uuid4()
    await service.set(household_id, "bakalari", "emma", SECRET)
    broken = ConnectorCredentialService(repository, SecretBox(Fernet.generate_key().decode()))

    with pytest.raises(ValueError, match="bakalari/emma") as excinfo:
        await broken.rotate()

    assert SECRET not in str(excinfo.value)


@pytest.mark.anyio
async def test_secret_calls_without_key_raise():
    service = ConnectorCredentialService(FakeCredentialRepository(), None)
    household_id = uuid4()

    with pytest.raises(CredentialKeyMissing, match="NIDARO_CREDENTIAL_KEY"):
        await service.set(household_id, "bakalari", "emma", SECRET)
    with pytest.raises(CredentialKeyMissing, match="NIDARO_CREDENTIAL_KEY"):
        await service.get(household_id, "bakalari", "emma")
    with pytest.raises(CredentialKeyMissing, match="NIDARO_CREDENTIAL_KEY"):
        await service.rotate()


@pytest.mark.anyio
async def test_metadata_calls_work_without_key():
    repository = FakeCredentialRepository()
    service = ConnectorCredentialService(repository, None)
    household_id = uuid4()
    await repository.save_ciphertext(household_id, "bakalari", "emma", "gAAAAA-stored-cipher")

    assert await service.names(household_id, "bakalari") == ["emma"]
    assert await service.delete(household_id, "bakalari", "emma")


def test_box_from_settings_without_key_is_none():
    assert SecretBox.from_settings(Settings(credential_key=None)) is None


def test_box_from_settings_honors_previous_keys():
    keys = [Fernet.generate_key().decode() for _ in range(2)]
    box = SecretBox.from_settings(
        Settings(credential_key=keys[0], credential_previous_keys=f"{keys[1]}, ,")
    )

    assert box is not None
    assert box.decrypt(SecretBox(keys[1]).encrypt(SECRET)) == SECRET
