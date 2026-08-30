from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nidaro.calendar.models import Event
from nidaro.calendar.repository import CalendarRepository
from nidaro.calendar.schemas import CreateEventRequest, EventView
from nidaro.calendar.service import CalendarService
from nidaro.household.models import FamilyMember


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
    event = await CalendarService(repository).create_event(
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
    event = await CalendarService(repository).create_event(make_request())
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
