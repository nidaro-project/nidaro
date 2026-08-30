"""Meals week view route tests: window math, slot grouping, service calls.

Real services over fake repositories (house pattern); the FastAPI dependency
override swaps ApplicationServices, so no PostgreSQL is touched.
"""

from dataclasses import replace
from datetime import date, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from nidaro.app import create_app
from nidaro.container import ApplicationServices
from nidaro.db.types import new_uuid, utc_now
from nidaro.household.models import Household
from nidaro.household.repository import HouseholdRepository
from nidaro.household.service import HouseholdService
from nidaro.meals.models import Dish, PlannedMeal
from nidaro.meals.repository import MealsRepository
from nidaro.meals.schemas import PlannedMealView
from nidaro.meals.service import MealsService
from nidaro.web.dependencies import get_services
from nidaro.web.routes.meals import _group_by_cell, _window


class FakeHouseholdRepository(HouseholdRepository):
    def __init__(self, household=None):
        self.household = household

    async def get(self, household_id=None):
        return self.household


class FakeMealsRepository(MealsRepository):
    def __init__(self, dish_rows=()):
        self.dish_rows = list(dish_rows)
        self.planned = []
        self.removed = []

    async def dishes(self, household_id):
        return [d for d in self.dish_rows if d.household_id == household_id]

    async def get_dish(self, dish_id):
        return next((d for d in self.dish_rows if d.id == dish_id), None)

    async def create_planned(self, request, name):
        meal = PlannedMeal(
            id=new_uuid(),
            household_id=request.household_id,
            date=request.date,
            slot=request.slot,
            dish_id=request.dish_id,
            name=name,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.planned.append(meal)
        return meal

    async def planned_between(self, household_id, start, end):
        return [m for m in self.planned if start <= m.date <= end]

    async def delete_planned(self, meal_id):
        meal = next((m for m in self.planned if m.id == meal_id), None)
        if meal is None:
            return False
        self.planned.remove(meal)
        self.removed.append(meal_id)
        return True


def _household():
    return Household(
        id=uuid4(),
        name="Morgan",
        timezone="Europe/Prague",
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def _dish(household_id, name):
    return Dish(
        id=uuid4(),
        household_id=household_id,
        name=name,
        notes=None,
        tags=[],
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def _services(household, meals_repo):
    base = ApplicationServices.build(async_sessionmaker())
    return replace(
        base,
        household=HouseholdService(FakeHouseholdRepository(household)),
        meals=MealsService(meals_repo),
    )


def _client(services):
    app = create_app()
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)


def test_window_is_rolling_seven_days_from_today():
    window = _window(0)
    assert window == [date.today() + timedelta(days=i) for i in range(7)]
    assert _window(3)[0] == date.today() + timedelta(weeks=3)
    assert _window(-1)[0] == date.today() - timedelta(weeks=1)


def test_group_by_cell_buckets_meals_by_day_and_slot():
    household_id = uuid4()
    day = date(2030, 5, 20)

    def meal(on, slot, name):
        return PlannedMealView(
            id=uuid4(), household_id=household_id, date=on, slot=slot, dish_id=None, name=name
        )

    grouped = _group_by_cell(
        [
            meal(day, "dinner", "Soup"),
            meal(day, "dinner", "Bread"),
            meal(day + timedelta(days=1), "breakfast", "Eggs"),
            meal(day - timedelta(days=1), "dinner", "Leftovers"),
        ]
    )
    assert [m.name for m in grouped[(day, "dinner")]] == ["Soup", "Bread"]
    assert grouped[(day + timedelta(days=1), "breakfast")][0].name == "Eggs"
    assert grouped[(day - timedelta(days=1), "dinner")][0].name == "Leftovers"


def test_week_page_renders_grid_with_dishes_and_planned_meal():
    household = _household()
    dish = _dish(household.id, "Pancakes")
    repo = FakeMealsRepository(dish_rows=[dish])
    today = date.today()
    repo.planned.append(
        PlannedMeal(
            id=uuid4(),
            household_id=household.id,
            date=today,
            slot="dinner",
            dish_id=dish.id,
            name="Pancakes",
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )
    response = _client(_services(household, repo)).get("/meals")
    assert response.status_code == 200
    expected_range = (
        f"{today.strftime('%b %-d')} - {(today + timedelta(days=6)).strftime('%b %-d')}"
    )
    assert expected_range in response.text
    assert 'href="/meals/dishes"' in response.text
    assert 'hx-post="/meals/plan"' in response.text
    assert "Pancakes" in response.text
    assert "meals-dayhead--today" in response.text
    assert "meals-cell--today" in response.text
    # w=0 hides the Today reset; prev/next shift by one week.
    assert ">Today</a>" not in response.text
    assert 'href="/meals?w=-1"' in response.text
    assert 'href="/meals?w=1"' in response.text


def test_week_page_shifts_window_and_shows_today_reset():
    household = _household()
    repo = FakeMealsRepository()
    response = _client(_services(household, repo)).get("/meals", params={"w": 2})
    assert response.status_code == 200
    start = date.today() + timedelta(weeks=2)
    expected_range = (
        f"{start.strftime('%b %-d')} - {(start + timedelta(days=6)).strftime('%b %-d')}"
    )
    assert expected_range in response.text
    assert 'href="/meals?w=1"' in response.text
    assert 'href="/meals?w=3"' in response.text
    assert 'href="/meals?w=0">Today</a>' in response.text


def test_week_page_without_household_renders_empty_state():
    repo = FakeMealsRepository()
    response = _client(_services(None, repo)).get("/meals")
    assert response.status_code == 200
    assert "No household yet" in response.text
    assert "hx-post" not in response.text


def test_plan_action_adds_one_off_and_renders_cell_fragment():
    household = _household()
    repo = FakeMealsRepository()
    today = date.today().isoformat()
    response = _client(_services(household, repo)).post(
        "/meals/plan",
        data={"w": "0", "on": today, "slot": "dinner", "name": "  Tomato soup  "},
    )
    assert response.status_code == 200
    assert len(repo.planned) == 1
    assert repo.planned[0].name == "Tomato soup"
    assert f'id="meals-cell-{today}-dinner"' in response.text
    assert "meals-chip--oneoff" in response.text


def test_plan_action_prefers_dish_over_typed_name():
    household = _household()
    dish = _dish(household.id, "Chili con Carne")
    repo = FakeMealsRepository(dish_rows=[dish])
    response = _client(_services(household, repo)).post(
        "/meals/plan",
        data={
            "w": "0",
            "on": date.today().isoformat(),
            "slot": "lunch",
            "dish_id": str(dish.id),
            "name": "ignored",
        },
    )
    assert response.status_code == 200
    assert len(repo.planned) == 1
    assert repo.planned[0].name == "Chili con Carne"
    assert repo.planned[0].dish_id == dish.id
    assert "meals-chip--oneoff" not in response.text


def test_plan_action_without_dish_or_name_is_a_no_op():
    household = _household()
    repo = FakeMealsRepository()
    response = _client(_services(household, repo)).post(
        "/meals/plan",
        data={"w": "0", "on": date.today().isoformat(), "slot": "lunch", "name": "   "},
    )
    assert response.status_code == 200
    assert repo.planned == []


def test_plan_action_rejects_dates_outside_the_week():
    household = _household()
    repo = FakeMealsRepository()
    response = _client(_services(household, repo)).post(
        "/meals/plan",
        data={"w": "0", "on": "2030-01-01", "slot": "lunch", "name": "Soup"},
    )
    assert response.status_code == 404
    assert repo.planned == []


def test_remove_action_calls_the_service():
    household = _household()
    repo = FakeMealsRepository()
    services = _services(household, repo)
    client = _client(services)
    today = date.today().isoformat()
    client.post("/meals/plan", data={"w": "0", "on": today, "slot": "dinner", "name": "Soup"})
    meal_id = repo.planned[0].id
    response = client.post(
        "/meals/planned/remove",
        data={"w": "0", "on": today, "slot": "dinner", "meal_id": str(meal_id)},
    )
    assert response.status_code == 200
    assert repo.removed == [UUID(str(meal_id))]
    assert repo.planned == []
    # The swapped-in cell is empty again: add form back, chip gone.
    assert "meals-add" in response.text
    assert "meals-chip" not in response.text
