"""Bakaláři gatherer tests: connector + mappers over fixture replays.

The connector is exercised end-to-end against an httpx.MockTransport that
answers from tests/fixtures/bakalari; landing goes through the real
SchoolService over a fake repository (house pattern). No live school system
is ever contacted (ADR 0002).
"""

import base64
import json
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs
from uuid import UUID

import httpx
import pytest

from nidaro.connectors.bakalari import (
    BAKALARI,
    BakalariConfigError,
    BakalariConnector,
    BakalariGatherError,
    apply_substitutions,
    gather_day,
    grades_from_marks,
    homework_from_payload,
    lessons_from_timetable,
    module_enabled,
)
from nidaro.connectors.crypto import SecretBox
from nidaro.connectors.models import ConnectorContext
from nidaro.connectors.service import ConnectorCredentialService
from nidaro.db.types import new_uuid, utc_now
from nidaro.school.models import Grade, Homework, Lesson, Subject
from nidaro.school.service import SchoolService

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bakalari"
HOUSEHOLD = "00000000-0000-0000-0000-0000000000e0"
ANNA = UUID("00000000-0000-0000-0000-0000000000c1")
TOMAS = UUID("00000000-0000-0000-0000-0000000000c2")
KEY = base64.urlsafe_b64encode(b"\x01" * 32).decode()
TODAY = gather_day("Europe/Prague")


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


class FakeCredentialRepository:
    def __init__(self, secrets: dict[str, str], box: SecretBox):
        self.secrets = secrets
        self.box = box

    async def get_ciphertext(self, household_id, connector, name):
        return None if name not in self.secrets else self.box.encrypt(self.secrets[name])

    async def save_ciphertext(self, household_id, connector, name, ciphertext):
        self.secrets[name] = ciphertext
        return name

    async def delete(self, household_id, connector, name):
        return self.secrets.pop(name, None) is not None

    async def names(self, household_id, connector):
        return sorted(self.secrets)

    async def all(self):
        return []


def credential_service(secrets: dict[str, str]) -> ConnectorCredentialService:
    box = SecretBox(KEY)
    return ConnectorCredentialService(FakeCredentialRepository(dict(secrets), box), box)


def account_blob(base_url: str, username: str, password: str) -> str:
    return json.dumps({"base_url": base_url, "username": username, "password": password})


class FakeSchoolRepository:
    """Landing seam only: what apply_* needs, nothing more."""

    def __init__(self):
        self.subjects: dict[tuple[UUID, str], Subject] = {}
        self.lessons: dict[tuple[UUID, date], list[Lesson]] = {}
        self.grades: dict[tuple[UUID, str], Grade] = {}
        self.homework: dict[tuple[UUID, str], Homework] = {}

    async def upsert_subject(self, member_id, household_id, subject):
        key = (member_id, subject.code)
        if key in self.subjects:
            return self.subjects[key]

        row = Subject(
            id=new_uuid(),
            household_id=household_id,
            member_id=member_id,
            code=subject.code,
            name=subject.name,
            teacher=subject.teacher,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.subjects[key] = row
        return row

    async def replace_lessons(self, member_id, household_id, day, items):

        rows = []
        for lesson_input, subject_id in items:
            row = Lesson(
                id=new_uuid(),
                household_id=household_id,
                member_id=member_id,
                day=day,
                subject_id=subject_id,
                start=lesson_input.start,
                end=lesson_input.end,
                position=lesson_input.position,
                teacher=lesson_input.teacher,
                room=lesson_input.room,
                canceled=lesson_input.canceled,
                substitution=lesson_input.substitution,
                created_at=utc_now(),
                updated_at=utc_now(),
                subject=self.subjects[(member_id, lesson_input.subject.code)],
            )
            rows.append(row)
        self.lessons[(member_id, day)] = rows
        return rows

    async def upsert_grade(self, member_id, household_id, grade, subject_id):

        key = (member_id, grade.external_id)
        if key in self.grades:
            return self.grades[key]
        row = Grade(
            id=new_uuid(),
            household_id=household_id,
            member_id=member_id,
            subject_id=subject_id,
            external_id=grade.external_id,
            value=grade.value,
            weight=grade.weight,
            graded_on=grade.graded_on,
            teacher=grade.teacher,
            confirmed=grade.confirmed,
            created_at=utc_now(),
            updated_at=utc_now(),
            subject=self.subjects[(member_id, grade.subject.code)],
        )
        self.grades[key] = row
        return row

    async def lessons_on(self, member_id, day):
        return sorted(self.lessons.get((member_id, day), []), key=lambda r: r.position)

    async def subjects_for_member(self, member_id):
        return [s for (m, _), s in self.subjects.items() if m == member_id]

    async def grades_for_member(self, member_id):
        return [g for (m, _), g in self.grades.items() if m == member_id]

    async def homework_for_member(self, member_id):
        return [h for (m, _), h in self.homework.items() if m == member_id]

    async def update_equipment(self, member_id, subject_id, equipment):
        for row in self.subjects.values():
            if row.id == subject_id and row.member_id == member_id:
                row.equipment = list(equipment)
                return row
        return None

    async def upsert_homework(self, member_id, household_id, homework, subject_id):

        key = (member_id, homework.external_id)
        if key in self.homework:
            return self.homework[key]
        row = Homework(
            id=new_uuid(),
            household_id=household_id,
            member_id=member_id,
            subject_id=subject_id,
            external_id=homework.external_id,
            text=homework.text,
            due_on=homework.due_on,
            attachments=homework.attachments,
            created_at=utc_now(),
            updated_at=utc_now(),
            subject=self.subjects[(member_id, homework.subject.code)],
        )
        self.homework[key] = row
        return row


def _fixture_for_today(name: str):
    """Fixture payloads dated to the gather day, as a school server would."""
    payload = fixture(name)
    if name == "timetable_actual.json":
        payload["Days"][0]["Date"] = f"{TODAY.isoformat()}T00:00:00+02:00"
    if name == "substitutions.json":
        payload[0]["Date"] = f"{TODAY.isoformat()}T00:00:00+02:00"
        payload[1]["Date"] = f"{(TODAY + timedelta(days=1)).isoformat()}T00:00:00+02:00"
    return payload


def bakalari_transport(seen: list, *, user="user.json", fail_passwords: set[str] | None = None):
    denied = fail_passwords or set()

    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.read().decode())
        seen.append((request.method, request.url.path, form or dict(request.url.params)))
        if request.method == "POST" and request.url.path == "/api/login":
            if form.get("password", [""])[0] in denied:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=fixture("login.json"))
        if request.method == "GET":
            responses = {
                "/api/3/user": httpx.Response(200, json=fixture(user)),
                "/api/3/timetable/actual": httpx.Response(
                    200, json=_fixture_for_today("timetable_actual.json")
                ),
                "/api/3/substitutions": httpx.Response(
                    200, json=_fixture_for_today("substitutions.json")
                ),
                "/api/3/marks": httpx.Response(200, json=fixture("marks.json")),
                "/api/3/homeworks": httpx.Response(200, json=fixture("homeworks.json")),
            }
            if request.url.path in responses:
                return responses[request.url.path]
        return httpx.Response(404, json={"Message": "no fixture for this route"})

    return httpx.MockTransport(handler)


def make_connector(
    secrets: dict[str, str], seen: list, **kwargs
) -> tuple[BakalariConnector, FakeSchoolRepository]:
    repo = FakeSchoolRepository()
    connector = BakalariConnector(
        credentials=credential_service(secrets),
        school=SchoolService(repo),
        transport=bakalari_transport(seen, **kwargs),
    )
    return connector, repo


def context() -> ConnectorContext:
    return ConnectorContext(household_id=HOUSEHOLD, timezone="Europe/Prague")


@pytest.mark.anyio
async def test_sync_lands_timetable_grades_and_homework():
    seen: list = []
    connector, repo = make_connector(
        {str(ANNA): account_blob("https://skola.example.cz", "a", "x")}, seen
    )

    result = await connector.sync(context(), None)

    assert result.next_cursor is None
    types = sorted((record.external_type, record.external_id) for record in result.records)
    assert types == [
        ("grade", "mark-1"),
        ("grade", "mark-2"),
        ("grade", "mark-3"),
        ("homework", "hw-1"),
        ("homework", "hw-2"),
        ("lesson", f"{TODAY.isoformat()}:1"),
        ("lesson", f"{TODAY.isoformat()}:2"),
        ("lesson", f"{TODAY.isoformat()}:3"),
    ]
    assert all(record.deleted is False for record in result.records)
    assert all(record.content_hash for record in result.records)
    assert all(record.connector == BAKALARI for record in result.records)

    member = repo.grades[(ANNA, "mark-1")]
    assert member.value == "1"
    assert member.weight == 2
    assert member.confirmed is True
    assert member.subject is not None
    assert member.subject.code == "M"

    day = repo.lessons[(ANNA, TODAY)]
    assert [row.position for row in day] == [1, 2, 3]
    assert day[0].canceled is False
    assert day[1].canceled is True
    assert day[1].substitution == "Kučera nemocný"
    assert day[2].substitution == "Supluje Mgr. Svobodová"
    assert day[2].teacher == "Mgr. Svobodová"
    assert day[0].start.hour == 8

    stored_homework = repo.homework[(ANNA, "hw-1")]
    assert stored_homework.due_on == date(2026, 5, 15)
    assert stored_homework.attachments == ["wordlist.pdf"]

    fetched = [path for method, path, _ in seen if method == "GET"]
    assert fetched == [
        "/api/3/user",
        "/api/3/timetable/actual",
        "/api/3/substitutions",
        "/api/3/marks",
        "/api/3/homeworks",
    ]
    window = seen[-1][2]
    assert window["from"] == (TODAY - timedelta(days=14)).isoformat()
    assert window["to"] == (TODAY + timedelta(days=14)).isoformat()


@pytest.mark.anyio
async def test_disabled_modules_are_never_fetched():
    seen: list = []
    connector, repo = make_connector(
        {str(ANNA): account_blob("https://skola.example.cz", "a", "x")},
        seen,
        user="user_limited.json",
    )

    result = await connector.sync(context(), None)

    assert result.records == []
    assert repo.grades == {}
    assert repo.lessons == {}
    assert [path for _, path, _ in seen] == ["/api/login", "/api/3/user"]


@pytest.mark.anyio
async def test_two_accounts_land_under_their_own_member():
    seen: list = []
    connector, repo = make_connector(
        {
            str(ANNA): account_blob("https://skola.example.cz", "anna", "tajne"),
            str(TOMAS): account_blob("https://skola.example.cz", "tomas", "jine"),
        },
        seen,
    )

    result = await connector.sync(context(), None)

    assert {record.connector for record in result.records} == {BAKALARI}
    assert (ANNA, "mark-1") in repo.grades
    assert (TOMAS, "mark-1") in repo.grades
    assert (ANNA, TODAY) in repo.lessons
    assert (TOMAS, TODAY) in repo.lessons
    assert len(seen) == 12  # login + five reads, per account


@pytest.mark.anyio
async def test_one_failing_account_does_not_block_the_other():
    seen: list = []
    connector, repo = make_connector(
        {
            str(ANNA): account_blob("https://skola.example.cz", "anna", "good"),
            str(TOMAS): account_blob("https://skola.example.cz", "tomas", "broken"),
        },
        seen,
        fail_passwords={"broken"},
    )

    with pytest.raises(BakalariGatherError) as error:
        await connector.sync(context(), None)

    assert str(TOMAS) in str(error.value)
    assert (ANNA, "mark-1") in repo.grades
    assert (TOMAS, "mark-1") not in repo.grades


@pytest.mark.anyio
async def test_no_accounts_configured_raises_config_error():
    connector, _ = make_connector({}, [])

    with pytest.raises(BakalariConfigError):
        await connector.sync(context(), None)


@pytest.mark.anyio
async def test_malformed_account_blob_fails_the_run():
    connector, _ = make_connector({str(ANNA): "not-json"}, [])

    with pytest.raises(BakalariGatherError) as error:
        await connector.sync(context(), None)

    assert str(ANNA) in str(error.value)


@pytest.mark.anyio
async def test_credential_name_must_be_a_member_id():
    connector, _ = make_connector({"emma": account_blob("https://skola.example.cz", "a", "x")}, [])

    with pytest.raises(BakalariGatherError):
        await connector.sync(context(), None)


def test_lesson_without_subject_or_timeslot_is_skipped():
    payload = {
        "Days": [
            {
                "Date": "2026-05-13T00:00:00+02:00",
                "Hours": [
                    {
                        "HourId": 1,
                        "Subject": {"Id": "s", "Abbrev": "M", "Name": "Matematika"},
                    },
                    {"HourId": 2, "Change": None},
                ],
            }
        ],
        "Hours": [{"Id": 1, "BeginTime": "08:00", "EndTime": "08:45"}],
    }

    lessons = lessons_from_timetable(payload, date(2026, 5, 13))

    assert [lesson.position for lesson in lessons] == [1]
    assert lessons[0].start.hour == 8


def test_substitutions_for_other_days_do_not_touch_lessons():
    lessons = lessons_from_timetable(fixture("timetable_actual.json"), date(2026, 5, 13))

    merged = apply_substitutions(lessons, fixture("substitutions.json"), date(2026, 5, 13))

    # The removal entry is for the 14th: hour 1 stays live, hour 3 gets substituted.
    assert merged[0].canceled is False
    assert merged[0].substitution is None
    assert merged[2].substitution == "Supluje Mgr. Svobodová"


def test_grades_missing_mark_id_are_skipped_and_weights_round():
    payload = {
        "Subjects": [
            {
                "Subject": {"Abbrev": "M", "Name": "Matematika"},
                "Marks": [
                    {"MarkText": "1", "Date": "2026-05-10T00:00:00+02:00"},
                    {
                        "MarkId": "m9",
                        "MarkText": "2",
                        "Date": "2026-05-11T00:00:00+02:00",
                        "Weight": 2.4,
                    },
                ],
            }
        ]
    }

    grades = grades_from_marks(payload)

    assert [grade.external_id for grade in grades] == ["m9"]
    assert grades[0].weight == 2
    assert grades[0].graded_on == date(2026, 5, 11)


def test_homework_mapping_keeps_optional_due_date():
    homework = homework_from_payload(fixture("homeworks.json"))

    assert homework[0].due_on == date(2026, 5, 15)
    assert homework[1].due_on is None
    assert homework[1].attachments == []


def test_module_gating_reads_enabled_modules():
    user = fixture("user.json")

    assert module_enabled(user, "Marks") is True
    assert module_enabled(user, "Timetable") is True
    assert module_enabled(user, "Canteen") is False
    assert module_enabled({}, "Marks") is False
