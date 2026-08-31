"""The passive Bakaláři gatherer: one Connector over mobile API v3.

Per the [portal-3] resolution a household's config rides the generic
connector intake: each `connector_credentials` row of connector "bakalari"
is one Bakaláři account instance, named by the family member it belongs to
(the kid↔account binding), holding an encrypted JSON blob of
`{"base_url", "username", "password"}`. One account is one kid; API
responses are already scoped to it, so no child-id plumbing exists.

`sync` gathers per account: login, EnabledModules discovery from
`/api/3/user`, then — only for modules the school enables — the actual
timetable (with substitution overlay), marks, and homework. Everything lands
through `SchoolService.apply_*` (the [portal-2] seam); the returned
`SyncResult` mirrors the landed items as `ExternalRecord`s. The run is
snapshot-based: re-fetching is safe because grades and homework upsert by
external id and the day's lessons are replaced wholesale, so no cursor state
is needed and `next_cursor` stays None.

ADR 0002: module reads are GET-only and the school system is never written
to — no mark-as-read, no confirmations, no replies.
"""

import json
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import BaseModel

from nidaro.connectors.bakalari_client import (
    BakalariAuthError,
    BakalariClient,
    BakalariRequestError,
)
from nidaro.connectors.models import ConnectorContext, ExternalRecord, SyncResult
from nidaro.connectors.service import ConnectorCredentialService, CredentialKeyMissing
from nidaro.db.types import utc_now
from nidaro.school.schemas import GradeInput, HomeworkInput, LessonInput, SubjectInput
from nidaro.school.service import SchoolService

BAKALARI = "bakalari"

# Change/ChangeType names that mean the lesson does not happen (community-
# documented v3 payloads use English names, some servers Czech ones).
CANCELED_CHANGES = {"removed", "cancelled", "canceled", "zruseno", "zrušeno"}

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


def gather_day(timezone: str) -> date:
    """Today in the household's timezone, UTC when the zone is unknown."""
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        zone = None
    moment = datetime.now(zone) if zone else datetime.now(UTC)
    return moment.date()


def module_enabled(user: dict[str, Any], name: str) -> bool:
    """EnabledModules discovery: a module counts as enabled when `/api/3/user`
    lists it with a truthy value; a school withholding a module omits it."""
    return bool((user.get("EnabledModules") or {}).get(name))


def _as_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _as_time(value: Any) -> time | None:
    if not value:
        return None
    parts = str(value).split(":")
    try:
        return time(int(parts[0]), int(parts[1]))
    except (IndexError, ValueError):
        return None


def _name(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    return entry.get("Name") or entry.get("Abbrev") or None


def _cancel_state(change: dict[str, Any] | None) -> tuple[bool, str | None]:
    """(canceled, note) from a Change object; no change means a live lesson."""
    change_type = ""
    if isinstance(change, dict):
        change_type = str((change.get("ChangeType") or {}).get("Name") or "").strip()
        description = change.get("Description")
    else:
        description = None
    canceled = change_type.lower() in CANCELED_CHANGES
    note = description or (change_type if canceled else None)
    return canceled, note or None


def lessons_from_timetable(payload: dict[str, Any], day: date) -> list[LessonInput]:
    """Materialized lessons for `day` from a `/api/3/timetable/actual` payload.

    Lessons without a subject or without a known timeslot are skipped; lesson
    times come from the payload's hour table (or the entry itself when it
    carries its own times).
    """
    slots = {slot.get("Id"): slot for slot in payload.get("Hours", []) if isinstance(slot, dict)}
    entry = next(
        (
            entry
            for entry in payload.get("Days", [])
            if isinstance(entry, dict) and str(entry.get("Date", "")).startswith(day.isoformat())
        ),
        None,
    )
    if entry is None:
        return []
    lessons: list[LessonInput] = []
    for hour in entry.get("Hours", []):
        subject = hour.get("Subject")
        if not isinstance(subject, dict):
            continue
        slot = slots.get(hour.get("HourId"), hour) or {}
        start = _as_time(slot.get("BeginTime"))
        end = _as_time(slot.get("EndTime"))
        if start is None or end is None:
            continue
        canceled, note = _cancel_state(hour.get("Change"))
        teacher = _name(hour.get("Teacher"))
        lessons.append(
            LessonInput(
                subject=SubjectInput(
                    code=subject.get("Abbrev") or "?",
                    name=subject.get("Name") or subject.get("Abbrev") or "Subject",
                    teacher=teacher,
                ),
                start=start,
                end=end,
                position=int(hour.get("HourId", len(lessons) + 1)),
                teacher=teacher,
                room=_name(hour.get("Room")),
                canceled=canceled,
                substitution=note,
            )
        )
    return sorted(lessons, key=lambda lesson: lesson.position)


def apply_substitutions(
    lessons: list[LessonInput], entries: list[dict[str, Any]], day: date
) -> list[LessonInput]:
    """Overlay `/api/3/substitutions` entries for `day` onto the lessons.

    A matching entry (same day and hour) can cancel the lesson, replace the
    teacher, and carries the note parents see. Entries for other days and
    hours without a lesson are ignored.
    """
    merged = [lesson.model_copy() for lesson in lessons]
    by_position = {lesson.position: lesson for lesson in merged}
    for entry in entries:
        if not isinstance(entry, dict) or _as_date(entry.get("Date")) != day:
            continue
        position = entry.get("Hour")
        if position is None:
            continue
        lesson = by_position.get(position)
        if lesson is None:
            continue
        change_type = str((entry.get("ChangeType") or {}).get("Name") or "").strip()
        if change_type.lower() in CANCELED_CHANGES:
            lesson.canceled = True
        note = entry.get("Description") or change_type or None
        if note:
            lesson.substitution = note
        teacher = _name(entry.get("Teacher"))
        if teacher:
            lesson.teacher = teacher
    return merged


def grades_from_marks(payload: dict[str, Any]) -> list[GradeInput]:
    """Marks per subject from a `/api/3/marks` payload."""
    grades: list[GradeInput] = []
    for block in payload.get("Subjects", []):
        subject = block.get("Subject") or {}
        code = subject.get("Abbrev") or "?"
        name = subject.get("Name") or code
        for mark in block.get("Marks", []):
            mark_id = mark.get("MarkId")
            graded_on = _as_date(mark.get("Date"))
            if not mark_id or graded_on is None:
                continue
            weight = mark.get("Weight")
            grades.append(
                GradeInput(
                    external_id=str(mark_id),
                    subject=SubjectInput(code=code, name=name),
                    value=str(mark.get("MarkText") or ""),
                    weight=round(float(weight)) if weight is not None else 1,
                    graded_on=graded_on,
                    teacher=mark.get("Teacher"),
                    confirmed=bool(mark.get("IsConfirmed")),
                )
            )
    return grades


def homework_from_payload(payload: dict[str, Any]) -> list[HomeworkInput]:
    """Assignments from a `/api/3/homeworks` payload."""
    items: list[HomeworkInput] = []
    for entry in payload.get("Homeworks", []):
        external_id = entry.get("Id")
        if not external_id:
            continue
        subject = entry.get("Subject") or {}
        items.append(
            HomeworkInput(
                external_id=str(external_id),
                subject=SubjectInput(
                    code=subject.get("Abbrev") or "?",
                    name=subject.get("Name") or subject.get("Abbrev") or "Subject",
                ),
                text=str(entry.get("Content") or ""),
                due_on=_as_date(entry.get("DateEnd")),
                attachments=[
                    attachment["Name"]
                    for attachment in entry.get("Attachments") or []
                    if isinstance(attachment, dict) and attachment.get("Name")
                ],
            )
        )
    return items


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
        keeps whatever cursor state it holds untouched.
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
