from collections.abc import Sequence
from datetime import date, datetime, timedelta
from uuid import UUID

from nidaro.calendar.recurrence import (
    OccurrenceView,
    expand_events,
    resolve_timezone,
    validate_range,
)
from nidaro.calendar.repository import CalendarRepository
from nidaro.calendar.schemas import (
    CreateEventRequest,
    EventView,
    ExternalEventPayload,
    MirrorApplyReport,
)
from nidaro.connectors.models import ExternalRecord
from nidaro.household.repository import HouseholdRepository


class CalendarService:
    def __init__(self, repository: CalendarRepository, households: HouseholdRepository) -> None:
        self.repository = repository
        self.households = households

    async def range(
        self, household_id: UUID, from_date: date, to_date: date
    ) -> list[OccurrenceView]:
        validate_range(from_date, to_date)
        tz = await self._household_timezone(household_id)
        events = await self.repository.range(household_id, from_date, to_date, tz)
        return expand_events(events, tz, from_date, to_date)

    async def get_upcoming_events(self, household_id: UUID, days: int = 7) -> list[OccurrenceView]:
        tz = await self._household_timezone(household_id)
        today = datetime.now(tz).date()
        return await self.range(household_id, today, today + timedelta(days=days - 1))

    async def create_event(self, request: CreateEventRequest) -> EventView:
        return EventView.model_validate(await self.repository.create(request))

    async def get_mirror(
        self, household_id: UUID, connector: str, external_id: str
    ) -> EventView | None:
        """The mirrored event for one external item, if it has been landed."""
        event = await self.repository.get_by_external_identity(household_id, connector, external_id)
        return EventView.model_validate(event) if event else None

    async def apply_external_records(
        self, household_id: UUID, records: Sequence[ExternalRecord]
    ) -> MirrorApplyReport:
        """Land a connector batch into the calendar: upsert mirrors, honor
        tombstones.

        A live `calendar_event` record is validated against
        `ExternalEventPayload` and upserted keyed by (household, connector,
        external id). A tombstone record (`deleted=True`, Google
        `status:"cancelled"` true deletions, CalDAV sync-collection REPORT
        deletions) removes the mirror — and with it the event the family
        sees. Tombstones for mirrors nidaro never had are counted as skipped,
        as are records of other external types that belong to a different
        domain application. A malformed live payload raises
        `pydantic.ValidationError` and aborts the run; records before the bad
        one are already committed, so callers should re-apply the whole batch
        after fixing the source.
        """
        report = MirrorApplyReport()
        for record in records:
            if record.deleted:
                if await self.repository.remove_mirror(
                    household_id, record.connector, record.external_id
                ):
                    report.removed += 1
                else:
                    report.skipped += 1
                continue
            if record.external_type != "calendar_event":
                report.skipped += 1
                continue
            payload = ExternalEventPayload.model_validate(record.payload)
            await self.repository.upsert_mirror(
                household_id,
                record.connector,
                record.external_id,
                payload.model_dump(),
            )
            report.applied += 1
        return report

    async def _household_timezone(self, household_id: UUID):
        household = await self.households.get(household_id)
        return resolve_timezone(household.timezone if household else None)
