from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FamilyMemberView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    role: str
    birth_date: date | None


class HouseholdView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    timezone: str
    members: list[FamilyMemberView] = []
    created_at: datetime


class CreateHouseholdRequest(BaseModel):
    name: str = "My Family"
    timezone: str = "Europe/Prague"
