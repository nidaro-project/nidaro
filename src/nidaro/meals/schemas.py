from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

Slot = Literal["breakfast", "lunch", "dinner", "snacks"]


class CreateDishRequest(BaseModel):
    household_id: UUID
    name: str
    notes: str | None = None
    tags: list[str] = []


class DishView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    name: str
    notes: str | None
    tags: list[str]


class UpdateDishRequest(BaseModel):
    name: str
    notes: str | None = None
    tags: list[str] = []


class PlanMealRequest(BaseModel):
    household_id: UUID
    date: date
    slot: Slot
    dish_id: UUID | None = None
    name: str | None = None

    @model_validator(mode="after")
    def needs_name_or_dish(self) -> "PlanMealRequest":
        if not self.name and not self.dish_id:
            raise ValueError("A planned meal needs a dish or a one-off name")
        return self


class PlannedMealView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    date: date
    slot: Slot
    dish_id: UUID | None
    name: str
