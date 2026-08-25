from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RememberFactRequest(BaseModel):
    household_id: UUID
    subject_type: str
    fact_type: str
    content: str
    subject_id: UUID | None = None


class FactView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    subject_type: str
    subject_id: UUID | None
    fact_type: str
    content: str
    valid_from: datetime | None
    valid_until: datetime | None


class MemorySearchRequest(BaseModel):
    household_id: UUID
    query: str
    limit: int = Field(default=10, ge=1, le=50)
