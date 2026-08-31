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
from nidaro.meals.models import Dish
from nidaro.meals.repository import MealsRepository
from nidaro.meals.schemas import CreateDishRequest, PlanMealRequest, Slot
from nidaro.school.repository import SchoolRepository
from nidaro.school.schemas import GradeInput, HomeworkInput, LessonInput, SubjectInput
from nidaro.school.service import SchoolService

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


@dataclass(frozen=True)
class DishSeed:
    name: str
    notes: str
    tags: tuple[str, ...]


DISH_SEEDS = (
    DishSeed(
        "Spaghetti Bolognese",
        "Sunday sauce, double batch. Leo picks out the carrots.",
        ("quick", "favorite"),
    ),
    DishSeed("Pancakes", "Buttermilk only. Emma likes blueberries in hers.", ("weekend", "kids")),
    DishSeed(
        "Chili con Carne",
        "Mild for the kids, hot sauce on the side. Freezes well.",
        ("one-pot", "freezer"),
    ),
    DishSeed("Sunday Roast Chicken", "Leftovers become Monday's bowls.", ("sunday",)),
    DishSeed("Lentil Curry", "Coconut milk version. Serve with rice.", ("veggie", "quick")),
    DishSeed(
        "Sushi Night", "Everyone rolls their own. Needs a shopping run.", ("special", "weekend")
    ),
)


@dataclass(frozen=True)
class PlannedMealSeed:
    """One entry of the seed week: either dish-backed (dish_name) or a one-off
    (one_off). Exactly one of the two is set."""

    day_offset: int
    slot: Slot
    dish_name: str | None = None
    one_off: str = ""

    def __post_init__(self) -> None:
        if (self.dish_name is None) != bool(self.one_off):
            raise ValueError("Set exactly one of dish_name or one_off")


# A partly-planned week, not a full one: the empty cells are the point.
WEEK_PLAN_SEEDS = (
    PlannedMealSeed(0, "dinner", dish_name="Spaghetti Bolognese"),
    PlannedMealSeed(1, "breakfast", dish_name="Pancakes"),
    PlannedMealSeed(1, "dinner", dish_name="Chili con Carne"),
    PlannedMealSeed(2, "dinner", one_off="Pizza for the guests"),
    PlannedMealSeed(5, "dinner", dish_name="Sushi Night"),
)


@dataclass(frozen=True)
class SeedMeal:
    """A planned meal to write: the name is already snapshotted (copy-on-plan)."""

    on: date
    slot: Slot
    name: str
    dish_id: UUID | None = None


def build_seed_meals(dishes_by_name: dict[str, Dish], today: date) -> list[SeedMeal]:
    """Resolve WEEK_PLAN_SEEDS against the seeded dishes. Each dish-backed meal
    copies the dish's name now, so later dish edits never rewrite the plan. A
    dish reference that no longer resolves (renamed or removed since) leaves
    its cell unplanned instead of failing the seed."""
    meals = []
    for seed in WEEK_PLAN_SEEDS:
        on = today + timedelta(days=seed.day_offset)
        if seed.dish_name is not None:
            dish = dishes_by_name.get(seed.dish_name)
            if dish is None:
                continue
            meals.append(SeedMeal(on, seed.slot, dish.name, dish.id))
        else:
            meals.append(SeedMeal(on, seed.slot, seed.one_off))
    return meals


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


async def _seed_meals(meals: MealsRepository, household: Household, today: date) -> None:
    """Idempotent: dishes are keyed by name, the week plan is written only while
    the coming week has no planned meals yet."""
    by_name = {dish.name: dish for dish in await meals.dishes(household.id)}
    for seed in DISH_SEEDS:
        if seed.name not in by_name:
            request = CreateDishRequest(
                household_id=household.id,
                name=seed.name,
                notes=seed.notes,
                tags=list(seed.tags),
            )
            by_name[seed.name] = await meals.create_dish(request)
    if await meals.planned_between(household.id, today, today + timedelta(days=6)):
        return
    for meal in build_seed_meals(by_name, today):
        # The repository takes the snapshot name explicitly — copy-on-plan,
        # the same semantics the meals service applies on the HTTP path.
        request = PlanMealRequest(
            household_id=household.id,
            date=meal.on,
            slot=meal.slot,
            dish_id=meal.dish_id,
            name=meal.name,
        )
        await meals.create_planned(request, meal.name)


async def _seed_school(school: SchoolService, household: Household, today: date) -> None:
    """Idempotent by construction: days are replaced wholesale, grades and
    homework upsert by external id, equipment is set outright."""
    kids = {m.name: m for m in household.members if m.role == "child"}
    if "Emma" not in kids or "Leo" not in kids:
        return
    tomorrow = today + timedelta(days=1)

    def lesson(position: int, code: str, name: str, canceled: bool = False) -> LessonInput:
        return LessonInput(
            subject=SubjectInput(code=code, name=name),
            start=time(8 + position, 0),
            end=time(8 + position, 45),
            position=position,
            teacher="Mgr. Vávrová",
            room="204",
            canceled=canceled,
            substitution="Moved to room 118" if canceled else None,
        )

    emma_lessons = [
        lesson(1, "M", "Matematika"),
        lesson(2, "ČJ", "Český jazyk"),
        lesson(3, "TV", "Tělesná výchova", canceled=True),
    ]
    await school.apply_day(kids["Emma"].id, household.id, today, emma_lessons)
    await school.apply_day(
        kids["Emma"].id, household.id, tomorrow, [lesson(1, "PČ", "Pracovní činnosti")]
    )
    await school.apply_grades(
        kids["Emma"].id,
        household.id,
        [
            GradeInput(
                external_id="seed-emma-m",
                subject=SubjectInput(code="M", name="Matematika"),
                value="1",
                weight=2,
                graded_on=today - timedelta(days=2),
                confirmed=True,
            ),
            GradeInput(
                external_id="seed-emma-cj",
                subject=SubjectInput(code="ČJ", name="Český jazyk"),
                value="2",
                weight=1,
                graded_on=today - timedelta(days=4),
                confirmed=False,
            ),
        ],
    )
    await school.apply_homework(
        kids["Emma"].id,
        household.id,
        [
            HomeworkInput(
                external_id="seed-emma-hw",
                subject=SubjectInput(code="M", name="Matematika"),
                text="Worksheet p. 34",
                due_on=tomorrow,
                attachments=["worksheet-34.pdf"],
            )
        ],
    )

    await school.apply_day(
        kids["Leo"].id,
        household.id,
        today,
        [lesson(1, "M", "Matematika"), lesson(2, "TV", "Tělesná výchova")],
    )
    await school.apply_day(kids["Leo"].id, household.id, tomorrow, [lesson(1, "ČJ", "Český jazyk")])
    await school.apply_grades(
        kids["Leo"].id,
        household.id,
        [
            GradeInput(
                external_id="seed-leo-m",
                subject=SubjectInput(code="M", name="Matematika"),
                value="2",
                weight=1,
                graded_on=today - timedelta(days=5),
                confirmed=True,
            )
        ],
    )

    for kid, subject_code, _name, items in (
        ("Emma", "TV", "", ["Gym kit", "Water bottle"]),
        ("Emma", "PČ", "", ["Art apron"]),
        ("Leo", "TV", "", ["Gym kit"]),
    ):
        target = next(s for s in await school.subjects_for(kids[kid].id) if s.code == subject_code)
        await school.set_equipment(kids[kid].id, target.id, items)


async def seed() -> None:
    ensure_full_metadata()
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    households = HouseholdRepository(sessions)
    events = CalendarRepository(sessions)
    meals = MealsRepository(sessions)
    school = SchoolService(SchoolRepository(sessions))
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
    if household:
        today = datetime.now(resolve_timezone(household.timezone)).date()
        if await events.count(household.id) == 0:
            for seed_event in build_seed_events(household, today):
                await events.add(seed_event.event, seed_event.participant_ids)
        await _seed_meals(meals, household, today)
        await _seed_school(school, household, today)
    await engine.dispose()


def main() -> None:
    asyncio.run(seed())
