from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from nidaro.db.base import Base, TimestampMixin
from nidaro.db.types import new_uuid


class GoogleCalendarAccount(TimestampMixin, Base):
    """One family member's consented Google account for one household.

    The row holds metadata only: the account email (the primary calendar id
    doubles as the email address), which of that account's calendars nidaro
    syncs, and the scopes Google actually granted. The OAuth refresh token
    never lives here — it is stored encrypted in `connector_credentials`
    under the account email as the credential name, written by
    `GoogleCalendarAccountService.register`.
    """

    __tablename__ = "google_calendar_accounts"
    __table_args__ = (UniqueConstraint("household_id", "google_email"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_uuid)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), index=True)
    google_email: Mapped[str] = mapped_column(String(250))
    calendar_id: Mapped[str] = mapped_column(String(250), default="primary")
    granted_scopes: Mapped[list[Any]] = mapped_column(JSONB, default=list)
