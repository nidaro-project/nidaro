from datetime import date
from uuid import uuid4

import pytest

from nidaro.meals.schemas import CreateDishRequest, PlanMealRequest, UpdateDishRequest
from nidaro.meals.service import MealsService


class FakeMealsRepository:
    def __init__(self):
        self.dishes_by_id = {}
        self.planned = []

    async def dishes(self, household_id):
        return [d for d in self.dishes_by_id.values() if d.household_id == household_id]

    async def create_dish(self, request):
        from nidaro.db.types import new_uuid, utc_now
        from nidaro.meals.models import Dish

        dish = Dish(
            id=new_uuid(),
            household_id=request.household_id,
            name=request.name,
            notes=request.notes,
            tags=request.tags,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.dishes_by_id[dish.id] = dish
        return dish

    async def get_dish(self, dish_id):
        return self.dishes_by_id.get(dish_id)

    async def create_planned(self, request, name):
        from nidaro.db.types import new_uuid, utc_now
        from nidaro.meals.models import PlannedMeal

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
        return sorted(
            (m for m in self.planned if m.household_id == household_id and start <= m.date <= end),
            key=lambda m: (m.date, m.created_at),
        )

    async def get_planned(self, meal_id):
        return next((m for m in self.planned if m.id == meal_id), None)

    async def delete_planned(self, meal_id):
        meal = await self.get_planned(meal_id)
        if meal is None:
            return False
        self.planned.remove(meal)
        return True

    async def update_dish(self, dish_id, request):
        dish = self.dishes_by_id.get(dish_id)
        if dish is None:
            return None
        for field, value in request.model_dump().items():
            setattr(dish, field, value)
        return dish

    async def delete_dish(self, dish_id):
        return self.dishes_by_id.pop(dish_id, None) is not None


@pytest.mark.anyio
async def test_plan_meal_snapshots_dish_name():
    repository = FakeMealsRepository()
    service = MealsService(repository)
    dish = await service.create_dish(
        CreateDishRequest(household_id=uuid4(), name="Chili con Carne")
    )
    meal = await service.plan_meal(
        PlanMealRequest(
            household_id=dish.household_id, date=date(2030, 3, 4), slot="dinner", dish_id=dish.id
        )
    )
    assert meal.name == "Chili con Carne"
    assert meal.dish_id == dish.id


@pytest.mark.anyio
async def test_plan_meal_requires_name_or_dish():
    service = MealsService(FakeMealsRepository())
    with pytest.raises(ValueError, match="dish or a one-off name"):
        await service.plan_meal(
            PlanMealRequest(household_id=uuid4(), date=date(2030, 3, 4), slot="lunch")
        )


@pytest.mark.anyio
async def test_dish_service_creates_typed_view():
    service = MealsService(FakeMealsRepository())
    dish = await service.create_dish(
        CreateDishRequest(household_id=uuid4(), name="Pancakes", tags=["weekend", "kids"])
    )
    assert dish.name == "Pancakes"
    assert dish.tags == ["weekend", "kids"]


@pytest.mark.anyio
async def test_list_planned_meals_returns_window_ordered():
    repository = FakeMealsRepository()
    service = MealsService(repository)
    household_id = uuid4()
    await service.plan_meal(
        PlanMealRequest(
            household_id=household_id, date=date(2030, 3, 6), slot="dinner", name="Late"
        )
    )
    await service.plan_meal(
        PlanMealRequest(
            household_id=household_id, date=date(2030, 3, 4), slot="lunch", name="Early"
        )
    )
    meals = await service.list_planned_meals(household_id, date(2030, 3, 1), date(2030, 3, 7))
    assert [m.name for m in meals] == ["Early", "Late"]
    outside = await service.list_planned_meals(household_id, date(2030, 4, 1), date(2030, 4, 7))
    assert outside == []


@pytest.mark.anyio
async def test_remove_planned_meal_reports_presence():
    repository = FakeMealsRepository()
    service = MealsService(repository)
    meal = await service.plan_meal(
        PlanMealRequest(household_id=uuid4(), date=date(2030, 3, 4), slot="dinner", name="Soup")
    )
    assert await service.remove_planned_meal(meal.id)
    assert not await service.remove_planned_meal(meal.id)


@pytest.mark.anyio
async def test_update_and_delete_dish():
    repository = FakeMealsRepository()
    service = MealsService(repository)
    dish = await service.create_dish(CreateDishRequest(household_id=uuid4(), name="Old name"))
    updated = await service.update_dish(
        dish.id, UpdateDishRequest(name="New name", notes="now with notes", tags=["quick"])
    )
    assert updated is not None
    assert updated.name == "New name"
    assert updated.notes == "now with notes"
    assert updated.tags == ["quick"]
    assert await service.delete_dish(dish.id)
    assert not await service.delete_dish(dish.id)
