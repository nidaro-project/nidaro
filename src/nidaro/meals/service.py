from datetime import date
from uuid import UUID

from nidaro.meals.repository import MealsRepository
from nidaro.meals.schemas import (
    CreateDishRequest,
    DishView,
    PlanMealRequest,
    PlannedMealView,
    UpdateDishRequest,
)


class MealsService:
    def __init__(self, repository: MealsRepository) -> None:
        self.repository = repository

    async def list_dishes(self, household_id: UUID) -> list[DishView]:
        return [DishView.model_validate(d) for d in await self.repository.dishes(household_id)]

    async def create_dish(self, request: CreateDishRequest) -> DishView:
        return DishView.model_validate(await self.repository.create_dish(request))

    async def plan_meal(self, request: PlanMealRequest) -> PlannedMealView:
        name = request.name
        if name is None and request.dish_id is not None:
            dish = await self.repository.get_dish(request.dish_id)
            if dish is None:
                raise ValueError(f"Dish {request.dish_id} does not exist")
            name = dish.name
        if name is None:
            raise ValueError("A planned meal needs a dish or a one-off name")
        return PlannedMealView.model_validate(await self.repository.create_planned(request, name))

    async def list_planned_meals(
        self, household_id: UUID, start: date, end: date
    ) -> list[PlannedMealView]:
        return [
            PlannedMealView.model_validate(meal)
            for meal in await self.repository.planned_between(household_id, start, end)
        ]

    async def remove_planned_meal(self, meal_id: UUID) -> bool:
        return await self.repository.delete_planned(meal_id)

    async def update_dish(self, dish_id: UUID, request: UpdateDishRequest) -> DishView | None:
        dish = await self.repository.update_dish(dish_id, request)
        return DishView.model_validate(dish) if dish else None

    async def delete_dish(self, dish_id: UUID) -> bool:
        return await self.repository.delete_dish(dish_id)
