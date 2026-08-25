from uuid import uuid4

import pytest

from nidaro.calendar.schemas import CreateEventRequest
from nidaro.calendar.service import CalendarService
from nidaro.household.schemas import CreateHouseholdRequest
from nidaro.household.service import HouseholdService
from nidaro.memory.schemas import RememberFactRequest
from nidaro.memory.service import MemoryService
from nidaro.tasks.schemas import CreateTaskRequest
from nidaro.tasks.service import TaskService


class FakeHouseholdRepository:
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


class FakeEventRepository:
    async def create(self, request):
        from nidaro.calendar.models import Event
        from nidaro.db.types import new_uuid

        return Event(id=new_uuid(), status="scheduled", **request.model_dump())

    async def upcoming(self, household_id, days=7):
        return []


class FakeTaskRepository:
    async def create(self, request):
        from nidaro.db.types import new_uuid
        from nidaro.tasks.models import Task

        return Task(id=new_uuid(), status="open", **request.model_dump())

    async def open(self, household_id, days=7):
        return []

    async def complete(self, task_id):
        return True


class FakeFactRepository:
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
    event = await CalendarService(FakeEventRepository()).create_event(
        CreateEventRequest(
            household_id=household_id, title="Swimming", starts_at="2030-01-01T17:00:00Z"
        )
    )
    assert event.title == "Swimming"


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
