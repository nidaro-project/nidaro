"""Bridge from connector syncs to the domain services that mirror records.

Connectors produce external records and never touch domain tables; this
module is the workers' hands: it builds each due sync's context (household
timezone plus decrypted credentials, in memory only), runs it through
`ConnectorService.sync` (cursor persistence, stale-cursor reset), and
routes the returned records to the domain applier that owns their
`external_type` — calendar events to `CalendarService.apply_external_records`,
today. A new connector with a new record type adds one entry in
`_applier_for`, nowhere else.

The same code path serves every trigger: the Taskiq sweep, a manual route,
or a test — scheduled jobs call the same application services as HTTP and
assistant code.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

from nidaro.calendar.schemas import MirrorApplyReport
from nidaro.calendar.service import CalendarService
from nidaro.connectors.models import ConnectorContext, ExternalRecord
from nidaro.connectors.service import (
    ConnectorConfigService,
    ConnectorCredentialService,
    ConnectorService,
)
from nidaro.household.service import HouseholdService

CALENDAR_EVENT = "calendar_event"

CREDENTIALS_UNAVAILABLE = "credentials unavailable"


class ConnectorSyncServices(Protocol):
    """The slice of `ApplicationServices` a sync sweep needs.

    Members are read-only properties so frozen dataclasses (the real
    container) and plain test fakes both satisfy the protocol.
    """

    @property
    def calendar(self) -> CalendarService: ...

    @property
    def connectors(self) -> ConnectorService: ...

    @property
    def connector_configs(self) -> ConnectorConfigService: ...

    @property
    def credentials(self) -> ConnectorCredentialService: ...

    @property
    def household(self) -> HouseholdService: ...


class SyncOutcome(BaseModel):
    """What syncing one (household, connector) pair did."""

    connector: str
    household_id: str
    records: int = 0
    applied: int = 0
    removed: int = 0
    skipped: int = 0


class SweepReport(BaseModel):
    """Result of one due-configs sweep: per-config outcomes plus failures."""

    outcomes: list[SyncOutcome] = []
    errors: list[str] = []


class _DomainApplier(Protocol):
    async def __call__(
        self, household_id: UUID, records: Sequence[ExternalRecord]
    ) -> MirrorApplyReport: ...


def _applier_for(services: ConnectorSyncServices, external_type: str) -> _DomainApplier | None:
    """Route a record type to the domain service that mirrors it."""
    if external_type == CALENDAR_EVENT:
        return services.calendar.apply_external_records
    return None


async def sync_connector(
    services: ConnectorSyncServices, connector: str, household_id: UUID
) -> SyncOutcome:
    """Sync one (household, connector) pair and land its records in the domain.

    Credentials are resolved by name from the encrypted store into the
    run's context — plaintext exists for this call only. A sync that
    returns records whose type has no applier counts them as skipped
    instead of dropping them silently.
    """
    config = await services.connector_configs.get(household_id, connector)
    if config is None or not config.enabled:
        raise LookupError(f"connector '{connector}' is not enabled for household {household_id}")
    # A failed credential read (store unusable, key unconfigured) fails the
    # sync loudly — silently syncing without secrets would be worse.
    credentials: dict[str, str] = {}
    for name in config.credential_names:
        secret = await services.credentials.get(household_id, connector, name)
        if secret is not None:
            credentials[name] = secret
    household = await services.household.get_household(household_id)
    context = ConnectorContext(
        household_id=str(household_id),
        timezone=household.timezone if household else "UTC",
        credentials=credentials,
    )
    result = await services.connectors.sync(connector, context)
    report = MirrorApplyReport()
    by_type: dict[str, list[ExternalRecord]] = {}
    for record in result.records:
        by_type.setdefault(record.external_type, []).append(record)
    for external_type, records in by_type.items():
        applier = _applier_for(services, external_type)
        if applier is None:
            report.skipped += len(records)
            continue
        applied = await applier(household_id, records)
        report.applied += applied.applied
        report.removed += applied.removed
        report.skipped += applied.skipped
    return SyncOutcome(
        connector=connector,
        household_id=str(household_id),
        records=len(result.records),
        applied=report.applied,
        removed=report.removed,
        skipped=report.skipped,
    )


async def sync_due(
    services: ConnectorSyncServices,
    connector: str | None = None,
    now: datetime | None = None,
) -> SweepReport:
    """Sync every connector config whose per-household cadence has elapsed.

    `now` is injection for tests; production sweeps pass nothing. One
    household's failure never blocks the others.
    """
    report = SweepReport()
    for config in await services.connector_configs.due(now):
        if connector is not None and config.connector != connector:
            continue
        try:
            outcome = await sync_connector(services, config.connector, config.household_id)
        except Exception as error:
            # One household's failure (revoked password, unreachable source)
            # must not block the others; the task reports it and moves on.
            report.errors.append(f"{config.connector}/{config.household_id}: {error}")
            continue
        report.outcomes.append(outcome)
    return report
