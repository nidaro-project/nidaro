from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RecordCommitmentRequest(BaseModel):
    household_id: UUID
    description: str
    from_member_id: UUID | None = None
    to_person_name: str | None = None
    due_at: datetime | None = None


class CommitmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    description: str
    from_member_id: UUID | None
    to_person_name: str | None
    due_at: datetime | None
    status: str
