from datetime import date, time, timedelta
from uuid import uuid4

from nidaro.calendar.recurrence import resolve_timezone
from nidaro.household.models import FamilyMember, Household
from nidaro.meals.models import Dish
from nidaro.seed import (
    DISH_SEEDS,
    WEEK_PLAN_SEEDS,
    build_seed_events,
    build_seed_meals,
    next_weekday,
)

TODAY = date(2030, 6, 3)  # a Monday


def make_household():
    members = [
        FamilyMember(id=uuid4(), household_id=uuid4(), name=name, role=role)
        for name, role in (
            ("Alex", "parent"),
            ("Sam", "parent"),
            ("Emma", "child"),
            ("Leo", "child"),
        )
    ]
    return Household(id=uuid4(), name="My Family", timezone="Europe/Prague", members=members)


def member_by_name(household, name):
    return next(member for member in household.members if member.name == name)


def event_by_title(seeds, title):
    return next(seed for seed in seeds if seed.event.title == title)


def test_seed_builds_seven_one_shot_events():
    seeds = build_seed_events(make_household(), TODAY)
    assert len(seeds) == 7
    titles = sorted(seed.event.title for seed in seeds)
    assert titles == sorted(
        [
            "Volleyball practice",
            "Dancing lesson",
            "Soccer practice",
            "Family game afternoon",
            "Dentist appointment",
            "No school — long weekend",
            "Grandma's birthday",
        ]
    )


def test_weekly_series_start_on_their_first_occurrence():
    seeds = build_seed_events(make_household(), TODAY)
    expected_first = {
        "Volleyball practice": (date(2030, 6, 6), time(16, 0), time(17, 30)),
        "Dancing lesson": (date(2030, 6, 5), time(15, 0), time(16, 0)),
        "Soccer practice": (date(2030, 6, 8), time(10, 0), time(11, 30)),
        "Family game afternoon": (date(2030, 6, 8), time(14, 0), time(16, 0)),
    }
    for title, (first_date, start, end) in expected_first.items():
        event = event_by_title(seeds, title).event
        assert event.starts_at.date() == first_date
        assert event.starts_at.time() == start
        assert event.ends_at is not None
        assert event.ends_at.time() == end
        assert event.ends_at.date() == first_date  # same-day end
        assert event.starts_at.tzinfo is not None
        assert next_weekday(TODAY, event.recurrence_weekdays or ()) == first_date


def test_series_weekdays_and_locations():
    seeds = build_seed_events(make_household(), TODAY)
    expected = {
        "Volleyball practice": ([0, 3], "The gym"),
        "Dancing lesson": ([2], "Dance studio"),
        "Soccer practice": ([5], "The fields"),
        "Family game afternoon": ([5], "Living room"),
    }
    for title, (weekdays, location) in expected.items():
        event = event_by_title(seeds, title).event
        assert event.recurrence_weekdays == weekdays
        assert event.location == location
        assert event.is_all_day is False


def test_participants_follow_the_roster():
    household = make_household()
    seeds = build_seed_events(household, TODAY)
    assert event_by_title(seeds, "Volleyball practice").participant_ids == (
        member_by_name(household, "Emma").id,
    )
    assert event_by_title(seeds, "Dancing lesson").participant_ids == (
        member_by_name(household, "Leo").id,
    )
    assert event_by_title(seeds, "Soccer practice").participant_ids == (
        member_by_name(household, "Leo").id,
    )
    assert event_by_title(seeds, "Family game afternoon").participant_ids == ()
    assert event_by_title(seeds, "Dentist appointment").participant_ids == (
        member_by_name(household, "Emma").id,
    )


def test_dentist_is_a_one_off_two_days_out():
    event = event_by_title(build_seed_events(make_household(), TODAY), "Dentist appointment").event
    assert event.recurrence_weekdays is None
    assert event.starts_at.date() == date(2030, 6, 5)
    assert event.starts_at.time() == time(11, 30)
    assert event.ends_at is not None
    assert event.ends_at.time() == time(12, 15)
    assert event.location == "Dr. Patel"


def test_all_day_entries_have_no_times():
    seeds = build_seed_events(make_household(), TODAY)
    no_school = event_by_title(seeds, "No school — long weekend").event
    birthday = event_by_title(seeds, "Grandma's birthday").event
    assert no_school.is_all_day is True
    assert no_school.starts_at.date() == date(2030, 6, 7)
    assert no_school.ends_at is None
    assert birthday.is_all_day is True
    assert birthday.starts_at.date() == date(2030, 6, 12)


def test_unknown_timezone_still_builds_deterministic_seeds():
    household = make_household()
    household.timezone = "Atlantis/Central"
    seeds = build_seed_events(household, TODAY)
    volleyball = event_by_title(seeds, "Volleyball practice").event
    starts_at = volleyball.starts_at
    assert starts_at is not None
    assert starts_at.tzinfo == resolve_timezone(None)


# ---- meals seeds ----


def make_dishes(**renamed):
    """Dish rows for every DISH_SEEDS name, keyed by seed name. A rename maps
    the seed name to a dish row whose .name differs (renamed since seeding)."""
    household_id = uuid4()
    dishes = {}
    for seed in DISH_SEEDS:
        name = renamed.get(seed.name, seed.name)
        dishes[seed.name] = Dish(id=uuid4(), household_id=household_id, name=name)
    return dishes


def meal_by_name(seeds, name):
    return next((seed for seed in seeds if seed.name == name), None)


def test_dish_seeds_are_the_household_rotation():
    assert [seed.name for seed in DISH_SEEDS] == [
        "Spaghetti Bolognese",
        "Pancakes",
        "Chili con Carne",
        "Sunday Roast Chicken",
        "Lentil Curry",
        "Sushi Night",
    ]
    for seed in DISH_SEEDS:
        assert seed.notes
        assert seed.tags


def test_seed_week_plan_is_partly_planned_and_mixed():
    meals = build_seed_meals(make_dishes(), TODAY)
    assert len(meals) == len(WEEK_PLAN_SEEDS) == 5
    assert len({meal.on for meal in meals}) == 4  # five meals over four days
    one_offs = [meal for meal in meals if meal.dish_id is None]
    assert [meal.name for meal in one_offs] == ["Pizza for the guests"]
    dish_backed = [meal for meal in meals if meal.dish_id is not None]
    assert {meal.name for meal in dish_backed} <= {seed.name for seed in DISH_SEEDS}


def test_seed_week_plan_stays_inside_the_coming_week():
    for meal in build_seed_meals(make_dishes(), TODAY):
        assert timedelta(0) <= meal.on - TODAY <= timedelta(days=6)


def test_dish_backed_meals_snapshot_the_dish_name():
    dishes = make_dishes(**{"Sushi Night": "Sushi Friday"})  # renamed after seeding
    meals = build_seed_meals(dishes, TODAY)
    sushi = meal_by_name(meals, "Sushi Friday")
    assert sushi.dish_id == dishes["Sushi Night"].id  # plan carries the new name…
    assert meal_by_name(meals, "Sushi Night") is None  # …never the seed-time one


def test_renamed_dish_leaves_its_seed_cell_unplanned():
    dishes = make_dishes(**{"Sushi Night": "Sushi Friday"})
    dishes.pop("Sushi Night")  # lookup is by seed-time name; the rename broke it
    meals = build_seed_meals(dishes, TODAY)
    assert "Sushi Friday" not in [meal.name for meal in meals]
    assert len(meals) == len(WEEK_PLAN_SEEDS) - 1


def test_seed_meal_slots_and_offsets_are_deterministic():
    meals = build_seed_meals(make_dishes(), TODAY)
    spaghetti = meal_by_name(meals, "Spaghetti Bolognese")
    assert (spaghetti.on, spaghetti.slot) == (TODAY, "dinner")
    pancakes = meal_by_name(meals, "Pancakes")
    assert (pancakes.on, pancakes.slot) == (TODAY + timedelta(days=1), "breakfast")
    assert meals.index(pancakes) < meals.index(meal_by_name(meals, "Chili con Carne"))
