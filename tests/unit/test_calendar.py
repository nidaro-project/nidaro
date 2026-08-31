from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nidaro.calendar.models import Event
from nidaro.calendar.repository import CalendarRepository
from nidaro.calendar.schemas import CreateEventRequest, EventView
from nidaro.calendar.service import CalendarService
from nidaro.connectors.models import ExternalRecord
from nidaro.db.types import new_uuid, utc_now
from nidaro.household.models import FamilyMember
from nidaro.household.repository import HouseholdRepository


class FakeHouseholdRepository(HouseholdRepository):
    def __init__(self):
        pass

    async def get(self, household_id=None):
        return None


class FakeEventRepository(CalendarRepository):
    def __init__(self):
        self.members = {}
        self.events = []

    async def create(self, request):
        from nidaro.calendar.models import Event as EventModel
        from nidaro.db.types import new_uuid

        fields = request.model_dump()
        participant_ids = fields.pop("participants")
        event = EventModel(
            id=new_uuid(),
            status="scheduled",
            participants=[self.members[member_id] for member_id in participant_ids],
            **fields,
        )
        self.events.append(event)
        return event

    async def upcoming(self, household_id, days=7):
        return []


class FakeMirrorRepository(CalendarRepository):
    """Serves the external-mirror seam; identity lookups in Python."""

    def __init__(self):
        self.events = []

    async def upsert_mirror(self, household_id, connector, external_id, fields):
        event = next(
            (e for e in self.events if self._identity(e) == (household_id, connector, external_id)),
            None,
        )
        if event is None:
            event = Event(
                id=new_uuid(),
                household_id=household_id,
                external_connector=connector,
                external_id=external_id,
                status="scheduled",
                created_at=utc_now(),
                updated_at=utc_now(),
                **fields,
            )
            self.events.append(event)
        else:
            for name, value in fields.items():
                setattr(event, name, value)
        return event

    async def remove_mirror(self, household_id, connector, external_id):
        for index, event in enumerate(self.events):
            if self._identity(event) == (household_id, connector, external_id):
                del self.events[index]
                return True
        return False

    @staticmethod
    def _identity(event):
        return (event.household_id, event.external_connector, event.external_id)


def calendar_record(**overrides):
    record = ExternalRecord(
        connector="bakalari",
        external_type="calendar_event",
        external_id="term/1",
        payload={
            "title": "School trip",
            "starts_at": datetime(2030, 6, 10, 8, 0, tzinfo=UTC),
            "ends_at": datetime(2030, 6, 10, 13, 0, tzinfo=UTC),
        },
        content_hash="hash-1",
        observed_at=datetime.now(UTC),
    )
    return record.model_copy(update=overrides) if overrides else record


def make_request(**overrides):
    starts_at = datetime(2030, 1, 1, 17, 0, tzinfo=UTC)
    fields = {"household_id": uuid4(), "title": "Swimming", "starts_at": starts_at}
    fields.update(overrides)
    return CreateEventRequest(**fields)


def test_create_event_request_defaults_to_single_occurrence():
    request = make_request()
    assert request.is_all_day is False
    assert request.recurrence_weekdays is None
    assert request.participants == []


@pytest.mark.parametrize("weekdays", [[-1], [7], [0, 7], [0, 0, 9]])
def test_create_event_request_rejects_weekday_out_of_range(weekdays):
    with pytest.raises(ValidationError, match=r"0\.\.6"):
        make_request(recurrence_weekdays=weekdays)


@pytest.mark.parametrize("weekdays", [[0], [1, 3, 5], list(range(7)), []])
def test_create_event_request_accepts_weekdays(weekdays):
    request = make_request(recurrence_weekdays=weekdays)
    assert request.recurrence_weekdays == weekdays


@pytest.mark.anyio
async def test_event_service_persists_new_fields():
    repository = FakeEventRepository()
    household_id = uuid4()
    member_ids = [uuid4(), uuid4()]
    for member_id in member_ids:
        repository.members[member_id] = FamilyMember(
            id=member_id, household_id=household_id, name="Member", role="adult"
        )
    event = await CalendarService(repository, FakeHouseholdRepository()).create_event(
        CreateEventRequest(
            household_id=household_id,
            title="Swim class",
            starts_at=datetime(2030, 1, 1, 17, 0, tzinfo=UTC),
            ends_at=datetime(2030, 1, 1, 18, 0, tzinfo=UTC),
            is_all_day=True,
            recurrence_weekdays=[1, 3],
            participants=member_ids,
        )
    )
    assert event.is_all_day is True
    assert event.recurrence_weekdays == [1, 3]
    assert event.participants == member_ids
    stored = repository.events[0]
    assert stored.is_all_day is True
    assert stored.recurrence_weekdays == [1, 3]
    assert [member.id for member in stored.participants] == member_ids


@pytest.mark.anyio
async def test_event_service_defaults_participants_to_household_wide():
    repository = FakeEventRepository()
    event = await CalendarService(repository, FakeHouseholdRepository()).create_event(
        make_request()
    )
    assert event.participants == []
    assert repository.events[0].participants == []


@pytest.mark.anyio
async def test_event_view_maps_participant_members_to_ids():
    household_id = uuid4()
    ada = FamilyMember(id=uuid4(), household_id=household_id, name="Ada", role="adult")
    event = Event(
        id=uuid4(),
        household_id=household_id,
        title="Park",
        starts_at=datetime(2030, 3, 4, 10, 0, tzinfo=UTC),
        status="scheduled",
        is_all_day=True,
        recurrence_weekdays=[6, 0],
        participants=[ada],
    )
    view = EventView.model_validate(event)
    assert view.participants == [ada.id]
    assert view.is_all_day is True
    assert view.recurrence_weekdays == [6, 0]


@pytest.mark.anyio
async def test_apply_external_record_upserts_mirror():
    repository = FakeMirrorRepository()
    report = await CalendarService(repository, FakeHouseholdRepository()).apply_external_records(
        uuid4(), [calendar_record()]
    )
    (event,) = repository.events
    assert (event.external_connector, event.external_id) == ("bakalari", "term/1")
    assert event.title == "School trip"
    assert event.starts_at == datetime(2030, 6, 10, 8, 0, tzinfo=UTC)
    assert event.ends_at == datetime(2030, 6, 10, 13, 0, tzinfo=UTC)
    assert event.status == "scheduled"
    assert report.model_dump() == {"applied": 1, "removed": 0, "skipped": 0}


@pytest.mark.anyio
async def test_reapplying_a_changed_record_updates_the_same_mirror():
    repository = FakeMirrorRepository()
    service = CalendarService(repository, FakeHouseholdRepository())
    household_id = uuid4()
    await service.apply_external_records(household_id, [calendar_record()])

    changed = calendar_record(
        payload={
            "title": "School trip",
            "starts_at": datetime(2030, 6, 10, 8, 0, tzinfo=UTC),
            "location": "New hall",
        }
    )
    report = await service.apply_external_records(household_id, [changed])

    (event,) = repository.events
    assert event.location == "New hall"
    assert report.applied == 1


@pytest.mark.anyio
async def test_external_tombstone_removes_the_mirror():
    repository = FakeMirrorRepository()
    service = CalendarService(repository, FakeHouseholdRepository())
    household_id = uuid4()
    await service.apply_external_records(household_id, [calendar_record()])
    assert len(repository.events) == 1

    tombstone = calendar_record(deleted=True, payload={}, content_hash="")
    report = await service.apply_external_records(household_id, [tombstone])

    assert repository.events == []
    assert report.model_dump() == {"applied": 0, "removed": 1, "skipped": 0}


@pytest.mark.anyio
async def test_tombstone_for_unknown_mirror_is_skipped():
    repository = FakeMirrorRepository()
    tombstone = calendar_record(external_id="ghost", deleted=True, payload={}, content_hash="")
    report = await CalendarService(repository, FakeHouseholdRepository()).apply_external_records(
        uuid4(), [tombstone]
    )
    assert repository.events == []
    assert report.removed == 0
    assert report.skipped == 1


@pytest.mark.anyio
async def test_records_of_other_domains_are_skipped():
    repository = FakeMirrorRepository()
    grade = calendar_record(external_type="school_grade", payload={"value": "1"})
    report = await CalendarService(repository, FakeHouseholdRepository()).apply_external_records(
        uuid4(), [grade]
    )
    assert repository.events == []
    assert report.skipped == 1


@pytest.mark.anyio
async def test_malformed_live_payload_raises():
    service = CalendarService(FakeMirrorRepository(), FakeHouseholdRepository())
    with pytest.raises(ValidationError, match="starts_at"):
        await service.apply_external_records(uuid4(), [calendar_record(payload={"title": "?"})])
