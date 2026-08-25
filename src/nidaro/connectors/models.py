from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ConnectorContext(BaseModel):
    household_id: str
    timezone: str


class ExternalRecord(BaseModel):
    connector: str
    external_type: str
    external_id: str
    payload: dict[str, Any]
    content_hash: str
    observed_at: datetime


class SyncResult(BaseModel):
    records: list[ExternalRecord]
    next_cursor: str | None = None
