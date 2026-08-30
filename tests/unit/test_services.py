from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

import pytest

from nidaro.calendar.repository import CalendarRepository
from nidaro.calendar.schemas import CreateEventRequest
from nidaro.calendar.service import CalendarService
from nidaro.household.models import Household
from nidaro.household.repository import HouseholdRepository
from nidaro.household.schemas import CreateHouseholdRequest
from nidaro.household.service import HouseholdService
from nidaro.memory.repository import FactRepository
from nidaro.memory.schemas import RememberFactRequest
from nidaro.memory.service import MemoryService
from nidaro.tasks.repository import TaskRepository
from nidaro.tasks.schemas import CreateTaskRequest
from nidaro.tasks.service import TaskService


class FakeHouseholdRepository(HouseholdRepository):
    def __init__(self):
        self.value = None

    async def get(self, household_id=None):
        return self.value

    async def create(self, request):
        from nidaro.db.types import new_uuid, utc_now
        from nidaro.household.models import Household

        self.value = Household(
            id=new_uuid(),
            name=request.name,
            timezone=request.timezone,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        return self.value


class FakeEventRepository(CalendarRepository):
    def __init__(self, events=()):
        self.events = list(events)

    async def create(self, request):
        from nidaro.calendar.models import Event
        from nidaro.db.types import new_uuid

        event = Event(id=new_uuid(), status="scheduled", **request.model_dump())
        self.events.append(event)
        return event

    async def upcoming(self, household_id, days=7):
        return []

    async def range(self, household_id, from_date, to_date, tz):
        # Expansion filters by window; the fake hands over everything.
        return [event for event in self.events if event.household_id == household_id]


class FakeTaskRepository(TaskRepository):
    def __init__(self):
        pass

    async def create(self, request):
        from nidaro.db.types import new_uuid
        from nidaro.tasks.models import Task

        return Task(id=new_uuid(), status="open", **request.model_dump())

    async def open(self, household_id, days=7):
        return []

    async def complete(self, task_id):
        return True


class FakeFactRepository(FactRepository):
    def __init__(self):
        pass

    async def create(self, request):
        from nidaro.db.types import new_uuid
        from nidaro.memory.models import Fact

        return Fact(id=new_uuid(), **request.model_dump())

    async def search(self, household_id, query, limit):
        return []

    async def recent(self, household_id, limit=10):
        return []


@pytest.mark.anyio
async def test_household_service_is_idempotent():
    service = HouseholdService(FakeHouseholdRepository())
    first = await service.ensure_household(CreateHouseholdRequest())
    second = await service.ensure_household(CreateHouseholdRequest(name="Other"))
    assert first.id == second.id
    assert second.name == "My Family"


@pytest.mark.anyio
async def test_event_service_creates_typed_view():
    household_id = uuid4()
    service = CalendarService(FakeEventRepository(), FakeHouseholdRepository())
    event = await service.create_event(
        CreateEventRequest(
            household_id=household_id,
            title="Swimming",
            starts_at=datetime(2030, 1, 1, 17, 0, tzinfo=UTC),
        )
    )
    assert event.title == "Swimming"


@pytest.mark.anyio
async def test_range_service_merges_occurrences_time_ordered():
    from zoneinfo import ZoneInfo

    from nidaro.calendar.models import Event

    household_id = uuid4()
    tz = ZoneInfo("UTC")
    monday = date(2030, 6, 3)
    all_day = Event(
        id=uuid4(),
        household_id=household_id,
        title="Birthday",
        is_all_day=True,
        starts_at=datetime.combine(monday, time.min, tzinfo=tz),
        participants=[],
    )
    series = Event(
        id=uuid4(),
        household_id=household_id,
        title="Practice",
        starts_at=datetime.combine(monday, time(16, 0), tzinfo=tz),
        ends_at=datetime.combine(monday, time(17, 0), tzinfo=tz),
        recurrence_weekdays=[0, 3],
        participants=[],
    )
    repository = FakeEventRepository([all_day, series])
    household = FakeHouseholdRepository()
    household.value = Household(
        id=household_id, name="My Family", timezone="UTC", created_at=datetime.now(UTC)
    )
    service = CalendarService(repository, household)

    occurrences = await service.range(household_id, monday, monday + timedelta(days=7))
    assert [(o.title, o.occurrence_date) for o in occurrences] == [
        ("Birthday", monday),
        ("Practice", monday),
        ("Practice", monday + timedelta(days=3)),
        ("Practice", monday + timedelta(days=7)),
    ]
    assert occurrences[0].starts_at is None
    first_practice = occurrences[1].starts_at
    assert first_practice is not None
    assert first_practice.hour == 16


@pytest.mark.anyio
async def test_range_service_rejects_windows_beyond_clamp():
    service = CalendarService(FakeEventRepository(), FakeHouseholdRepository())
    with pytest.raises(ValueError, match="62 days"):
        await service.range(uuid4(), date(2030, 1, 1), date(2030, 1, 1) + timedelta(days=63))


@pytest.mark.anyio
async def test_upcoming_events_reports_occurrences_not_series_rows():
    from zoneinfo import ZoneInfo

    from nidaro.calendar.models import Event

    household_id = uuid4()
    tz = ZoneInfo("UTC")
    soon = datetime.now(tz) + timedelta(hours=2)
    far = datetime.now(tz) + timedelta(days=30)
    repository = FakeEventRepository(
        [
            Event(
                id=uuid4(),
                household_id=household_id,
                title="Soccer practice",
                starts_at=soon,
                ends_at=soon + timedelta(hours=1),
                recurrence_weekdays=[0, 1, 2, 3, 4, 5, 6],
                participants=[],
            ),
            Event(
                id=uuid4(),
                household_id=household_id,
                title="Camp trip",
                starts_at=far,
                participants=[],
            ),
        ]
    )
    household = FakeHouseholdRepository()
    household.value = Household(
        id=household_id, name="My Family", timezone="UTC", created_at=datetime.now(UTC)
    )
    occurrences = await CalendarService(repository, household).get_upcoming_events(household_id)

    assert [o.title for o in occurrences] == ["Soccer practice"] * len(occurrences)
    assert len(occurrences) >= 2  # one series row became daily occurrences
    assert occurrences[0].occurrence_date == soon.date()
    assert occurrences[0].starts_at is not None


@pytest.mark.anyio
async def test_task_service_completes_task():
    service = TaskService(FakeTaskRepository())
    task = await service.create_task(CreateTaskRequest(household_id=uuid4(), title="Pack bag"))
    assert task.title == "Pack bag"
    assert await service.complete_task(task.id)


@pytest.mark.anyio
async def test_memory_service_searches_through_repository():
    service = MemoryService(FakeFactRepository())
    fact = await service.remember_fact(
        RememberFactRequest(
            household_id=uuid4(),
            subject_type="family",
            fact_type="preference",
            content="Likes apples",
        )
    )
    assert fact.content == "Likes apples"
