import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID

from nidaro.calendar.models import Event
from nidaro.calendar.recurrence import first_weekday_on_or_after, resolve_timezone
from nidaro.calendar.repository import CalendarRepository
from nidaro.config import get_settings
from nidaro.db.engine import create_engine, create_session_factory
from nidaro.db.registry import ensure_full_metadata
from nidaro.household.models import Household
from nidaro.household.repository import HouseholdRepository
from nidaro.household.schemas import CreateHouseholdRequest

MEMBERS = (("Alex", "parent"), ("Sam", "parent"), ("Emma", "child"), ("Leo", "child"))


@dataclass(frozen=True)
class SeriesSeed:
    title: str
    participant: str | None
    weekdays: tuple[int, ...]
    starts_at: time
    ends_at: time
    location: str


WEEKLY_ACTIVITIES = (
    SeriesSeed("Volleyball practice", "Emma", (0, 3), time(16, 0), time(17, 30), "The gym"),
    SeriesSeed("Dancing lesson", "Leo", (2,), time(15, 0), time(16, 0), "Dance studio"),
    SeriesSeed("Soccer practice", "Leo", (5,), time(10, 0), time(11, 30), "The fields"),
    SeriesSeed("Family game afternoon", None, (5,), time(14, 0), time(16, 0), "Living room"),
)

ALL_DAY_OCCURRENCES = ((4, "No school — long weekend"), (9, "Grandma's birthday"))


@dataclass(frozen=True)
class SeedEvent:
    event: Event
    participant_ids: tuple[UUID, ...] = ()


def next_weekday(after: date, weekdays: Iterable[int]) -> date:
    """First weekday strictly after ``after``: seeded series begin tomorrow or later."""
    return first_weekday_on_or_after(after + timedelta(days=1), weekdays)


def build_seed_events(household: Household, today: date) -> list[SeedEvent]:
    tz = resolve_timezone(household.timezone)
    member_ids = {member.name: member.id for member in household.members}
    seeds = []
    for activity in WEEKLY_ACTIVITIES:
        first_date = next_weekday(today, activity.weekdays)
        seeds.append(
            SeedEvent(
                Event(
                    household_id=household.id,
                    title=activity.title,
                    starts_at=datetime.combine(first_date, activity.starts_at, tzinfo=tz),
                    ends_at=datetime.combine(first_date, activity.ends_at, tzinfo=tz),
                    location=activity.location,
                    is_all_day=False,
                    recurrence_weekdays=list(activity.weekdays),
                ),
                (member_ids[activity.participant],) if activity.participant else (),
            )
        )
    dentist_date = today + timedelta(days=2)
    seeds.append(
        SeedEvent(
            Event(
                household_id=household.id,
                title="Dentist appointment",
                starts_at=datetime.combine(dentist_date, time(11, 30), tzinfo=tz),
                ends_at=datetime.combine(dentist_date, time(12, 15), tzinfo=tz),
                location="Dr. Patel",
                is_all_day=False,
            ),
            (member_ids["Emma"],),
        )
    )
    for offset, title in ALL_DAY_OCCURRENCES:
        seeds.append(
            SeedEvent(
                Event(
                    household_id=household.id,
                    title=title,
                    starts_at=datetime.combine(today + timedelta(days=offset), time.min, tzinfo=tz),
                    is_all_day=True,
                )
            )
        )
    return seeds


async def seed() -> None:
    ensure_full_metadata()
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    households = HouseholdRepository(sessions)
    events = CalendarRepository(sessions)
    household = await households.get()
    if household is None:
        household = await households.create(CreateHouseholdRequest(timezone=settings.timezone))
        # A freshly created household has no members; the detached instance
        # from create() cannot lazy-load the relationship.
        existing: set[str] = set()
    else:
        existing = {member.name for member in household.members}
    for name, role in MEMBERS:
        if name not in existing:
            await households.add_member(household.id, name, role)
    household = await households.get(household.id)
    if household and await events.count(household.id) == 0:
        today = datetime.now(resolve_timezone(household.timezone)).date()
        for seed_event in build_seed_events(household, today):
            await events.add(seed_event.event, seed_event.participant_ids)
    await engine.dispose()


def main() -> None:
    asyncio.run(seed())
