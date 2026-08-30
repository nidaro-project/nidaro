from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nidaro.meals.models import Dish, PlannedMeal
from nidaro.meals.schemas import CreateDishRequest, PlanMealRequest, UpdateDishRequest


class MealsRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def dishes(self, household_id: UUID) -> list[Dish]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(Dish).where(Dish.household_id == household_id).order_by(Dish.name)
            )
            return list(result)

    async def create_dish(self, request: CreateDishRequest) -> Dish:
        async with self.sessions.begin() as session:
            dish = Dish(**request.model_dump())
            session.add(dish)
            await session.flush()
            return dish

    async def get_dish(self, dish_id: UUID) -> Dish | None:
        async with self.sessions() as session:
            return await session.get(Dish, dish_id)

    async def planned_between(
        self, household_id: UUID, start: date, end: date
    ) -> list[PlannedMeal]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(PlannedMeal)
                .where(
                    PlannedMeal.household_id == household_id,
                    PlannedMeal.date >= start,
                    PlannedMeal.date <= end,
                )
                .order_by(PlannedMeal.date, PlannedMeal.created_at)
            )
            return list(result)

    async def create_planned(self, request: PlanMealRequest, name: str) -> PlannedMeal:
        async with self.sessions.begin() as session:
            meal = PlannedMeal(**request.model_dump(exclude={"name"}), name=name)
            session.add(meal)
            await session.flush()
            return meal

    async def update_dish(self, dish_id: UUID, request: UpdateDishRequest) -> Dish | None:
        async with self.sessions.begin() as session:
            dish = await session.get(Dish, dish_id)
            if dish is None:
                return None
            for field, value in request.model_dump().items():
                setattr(dish, field, value)
            await session.flush()
            return dish

    async def delete_dish(self, dish_id: UUID) -> bool:
        async with self.sessions.begin() as session:
            dish = await session.get(Dish, dish_id)
            if dish is None:
                return False
            await session.delete(dish)
            await session.flush()
            return True

    async def delete_planned(self, meal_id: UUID) -> bool:
        async with self.sessions.begin() as session:
            meal = await session.get(PlannedMeal, meal_id)
            if meal is None:
                return False
            await session.delete(meal)
            await session.flush()
            return True
