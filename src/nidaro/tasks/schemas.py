from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateTaskRequest(BaseModel):
    household_id: UUID
    title: str
    description: str | None = None
    due_at: datetime | None = None
    priority: int = Field(default=0, ge=0, le=10)
    assignee_id: UUID | None = None


class TaskView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    title: str
    description: str | None
    due_at: datetime | None
    status: str
    priority: int
    assignee_id: UUID | None


class OpenTasks(BaseModel):
    tasks: list[TaskView] = []
