"""The passive Bakaláři gatherer: one Connector over mobile API v3.

Per the [portal-3] resolution a household's config rides the generic
connector intake: each `connector_credentials` row of connector "bakalari"
is one Bakaláři account instance, named by the family member it belongs to
(the kid↔account binding), holding an encrypted JSON blob of
`{"base_url", "username", "password"}`. One account is one kid; API
responses are already scoped to it, so no child-id plumbing exists.

`sync` gathers per account: login, EnabledModules discovery from
`/api/3/user`, then — only for modules the school enables — the actual
timetable (with substitution overlay), marks, and homework. Payload
mapping lives in `bakalari_mapping`; everything here lands through
`SchoolService.apply_*` (the [portal-2] seam), and the returned
`SyncResult` mirrors the landed items as `ExternalRecord`s. The run is
snapshot-based: re-fetching is safe because grades and homework upsert by
external id and the day's lessons are replaced wholesale, so no cursor state
is needed and `next_cursor` stays None.

ADR 0002: module reads are GET-only and the school system is never written
to — no mark-as-read, no confirmations, no replies.
"""

import json
from datetime import timedelta
from hashlib import sha256
from uuid import UUID

import httpx
from pydantic import BaseModel

from nidaro.connectors.bakalari_client import (
    BakalariAuthError,
    BakalariClient,
    BakalariRequestError,
)
from nidaro.connectors.bakalari_mapping import (
    apply_substitutions,
    gather_day,
    grades_from_marks,
    homework_from_payload,
    lessons_from_timetable,
    module_enabled,
)
from nidaro.connectors.models import ConnectorContext, ExternalRecord, SyncResult
from nidaro.connectors.service import ConnectorCredentialService, CredentialKeyMissing
from nidaro.db.types import utc_now
from nidaro.school.service import SchoolService

BAKALARI = "bakalari"

HOMEWORK_WINDOW_DAYS = 14


class BakalariConfigError(Exception):
    """The household's Bakaláři intake is unusable (no accounts, bad blob)."""


class BakalariGatherError(Exception):
    """At least one account failed; its member id names the failure."""


class BakalariAccount(BaseModel):
    member_id: UUID
    base_url: str
    username: str
    password: str


class BakalariConnector:
    """The Connector registered under the name "bakalari"."""

    name = BAKALARI

    def __init__(
        self,
        credentials: ConnectorCredentialService,
        school: SchoolService,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._credentials = credentials
        self._school = school
        self._transport = transport

    async def sync(self, context: ConnectorContext, cursor: str | None) -> SyncResult:
        """Gather every configured account; one bad account fails the run.

        Snapshot semantics make the `cursor` argument irrelevant (see module
        docstring), so `next_cursor` is always None and `ConnectorService`
        keeps whatever cursor state it holds untouched. A failure per account
        is collected; when any account failed the good ones still landed, but
        the run raises so `ConnectorService` does not stamp `last_synced_at`.
        """
        household = UUID(context.household_id)
        names = await self._credentials.names(household, BAKALARI)
        if not names:
            raise BakalariConfigError(f"no Bakaláři accounts configured for household {household}")
        records: list[ExternalRecord] = []
        failures: list[str] = []
        for name in sorted(names):
            try:
                account = await self._account(household, name)
                records += await self._gather(account, household, context)
            except (
                BakalariConfigError,
                BakalariAuthError,
                BakalariRequestError,
                CredentialKeyMissing,
            ) as error:
                failures.append(f"{name}: {error}")
        if failures:
            raise BakalariGatherError("; ".join(failures))
        return SyncResult(records=records)

    async def _account(self, household: UUID, name: str) -> BakalariAccount:
        blob = await self._credentials.get(household, BAKALARI, name)
        try:
            payload = json.loads(blob or "")
            return BakalariAccount.model_validate({"member_id": name, **payload})
        except ValueError as error:
            raise BakalariConfigError(
                f"credential {name} is not a valid Bakaláři account instance"
            ) from error

    async def _gather(
        self, account: BakalariAccount, household: UUID, context: ConnectorContext
    ) -> list[ExternalRecord]:
        day = gather_day(context.timezone)
        records: list[ExternalRecord] = []
        async with BakalariClient(
            account.base_url, account.username, account.password, transport=self._transport
        ) as client:
            user = await client.user()
            if module_enabled(user, "Timetable"):
                lessons = lessons_from_timetable(await client.timetable_actual(day), day)
                if module_enabled(user, "Substitutions"):
                    lessons = apply_substitutions(lessons, await client.substitutions(day), day)
                if lessons:
                    await self._school.apply_day(account.member_id, household, day, lessons)
                    records += [
                        _record("lesson", f"{day.isoformat()}:{lesson.position}", lesson)
                        for lesson in lessons
                    ]
            if module_enabled(user, "Marks"):
                grades = grades_from_marks(await client.marks())
                if grades:
                    await self._school.apply_grades(account.member_id, household, grades)
                    records += [_record("grade", grade.external_id, grade) for grade in grades]
            if module_enabled(user, "Homeworks"):
                homework = homework_from_payload(
                    await client.homeworks(
                        day - timedelta(days=HOMEWORK_WINDOW_DAYS),
                        day + timedelta(days=HOMEWORK_WINDOW_DAYS),
                    )
                )
                if homework:
                    await self._school.apply_homework(account.member_id, household, homework)
                    records += [_record("homework", item.external_id, item) for item in homework]
        return records


def _record(external_type: str, external_id: str, item: BaseModel) -> ExternalRecord:
    payload = item.model_dump(mode="json")
    digest = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode())
    return ExternalRecord(
        connector=BAKALARI,
        external_type=external_type,
        external_id=external_id,
        payload=payload,
        content_hash=digest.hexdigest(),
        observed_at=utc_now(),
    )
