import json
from uuid import UUID, uuid4

import pytest
from caldav.response import DAVResponse

from nidaro.calendar.models import Event
from nidaro.calendar.repository import CalendarRepository
from nidaro.calendar.service import CalendarService
from nidaro.connectors.base import StaleCursorError
from nidaro.connectors.icloud_calendar import (
    CALENDAR_EVENT,
    CONNECTOR_NAME,
    CREDENTIAL_ASP,
    CREDENTIAL_USERNAME,
    FetchedIcs,
    IcloudCalendarConnector,
    SyncChanges,
    SyncUnsupportedError,
    calendar_multiget_body,
    calendar_query_body,
    decode_cursor,
    merge_tombstones,
    sync_collection_body,
)
from nidaro.connectors.models import ConnectorContext
from nidaro.connectors.registry import ConnectorRegistry
from nidaro.connectors.service import ConnectorService
from nidaro.db.types import new_uuid, utc_now
from nidaro.household.repository import HouseholdRepository

CALENDAR_URL = "https://p12-caldav.icloud.com/1711/calendars/home/"
SOCCER_HREF = "/1711/calendars/home/soccer.ics"
DENTIST_HREF = "/1711/calendars/home/dentist.ics"
GONE_HREF = "/1711/calendars/home/gone.ics"
TOKEN_A = "https://idmsa.apple.com/token/1"
TOKEN_B = "https://idmsa.apple.com/token/2"

SOCCER_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:soccer@example.com
DTSTAMP:20260831T100000Z
DTSTART;TZID=Europe/Oslo:20260914T160000
DTEND;TZID=Europe/Oslo:20260914T173000
RRULE:FREQ=WEEKLY;BYDAY=MO
SUMMARY:Soccer practice
END:VEVENT
END:VCALENDAR
"""

DENTIST_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:dentist@example.com
DTSTAMP:20260831T100000Z
DTSTART:20260915T090000
DTEND:20260915T094500
SUMMARY:Dentist
END:VEVENT
END:VCALENDAR
"""


class FakeCalDavSession:
    """Offline stand-in for the caldav client, scripted per test.

    `listings` maps the stored token to the sync-collection reply it gets;
    the None key is the initial full listing. Anything missing falls back
    to the None listing — the RFC 6578 behavior when a token is invalid.
    """

    def __init__(self, listings=None, fetches=None, report_error=False, stale_on_token=False):
        self.listings = listings or {}
        self.fetches = fetches or {}
        self.report_error = report_error
        self.stale_on_token = stale_on_token
        self.sync_calls: list[str | None] = []
        self.fetched_hrefs: list[list[str]] = []

    def calendar_urls(self):
        return [CALENDAR_URL]

    def sync_changes(self, calendar_url, token):
        self.sync_calls.append(token)
        if token is not None and self.stale_on_token:
            raise StaleCursorError("credentials revoked")
        if self.report_error:
            raise SyncUnsupportedError("server rejected the sync-collection REPORT")
        return self.listings.get(token, self.listings[None])

    def fetch(self, calendar_url, hrefs):
        self.fetched_hrefs.append(list(hrefs))
        return [fetch for href in hrefs for fetch in self.fetches.get(href, [])]

    def calendar_query(self, calendar_url):
        return [item for items in self.fetches.values() for item in items]


def listing(changed=(), deleted=(), token=TOKEN_A):
    return SyncChanges(changed=changed, deleted=deleted, token=token)


def fetch(href, ics):
    return FetchedIcs(href=href, ics=ics)


def context(**credential_overrides):
    credentials = {CREDENTIAL_USERNAME: "member@icloud.com", CREDENTIAL_ASP: "abcd-efgh"}
    credentials.update(credential_overrides)
    return ConnectorContext(
        household_id=str(uuid4()), timezone="Europe/Oslo", credentials=credentials
    )


def initial_listing():
    """Everything exists: one REPORT away from a fully populated cursor."""
    return listing(
        changed=((SOCCER_HREF, '"e1"'), (DENTIST_HREF, '"e2"')),
        token=TOKEN_A,
    )


def full_session():
    """A session whose first (initial) sync lists everything, then goes quiet."""
    return FakeCalDavSession(
        listings={
            None: initial_listing(),
            TOKEN_A: listing(token=TOKEN_A),  # incremental: nothing changed
        },
        fetches={
            SOCCER_HREF: [fetch(SOCCER_HREF, SOCCER_ICS)],
            DENTIST_HREF: [fetch(DENTIST_HREF, DENTIST_ICS)],
        },
    )


@pytest.mark.anyio
async def test_first_sync_fetches_everything_and_stores_the_token_map():
    session = full_session()
    result = await IcloudCalendarConnector(lambda u, p: session).sync(context(), None)

    assert session.sync_calls == [None]
    soccer = next(record for record in result.records if "soccer" in record.external_id)
    assert soccer.connector == CONNECTOR_NAME
    assert soccer.external_type == CALENDAR_EVENT
    assert soccer.deleted is False
    assert soccer.content_hash
    assert soccer.payload["title"] == "Soccer practice"
    assert soccer.payload["recurrence_weekdays"] == [0]
    assert soccer.payload["calendar_url"] == CALENDAR_URL

    state = json.loads(result.next_cursor)
    (entry,) = state["calendars"].values()
    assert entry["token"] == TOKEN_A
    assert entry["items"][SOCCER_HREF] == ["soccer@example.com"]
    assert entry["items"][DENTIST_HREF] == ["dentist@example.com"]


@pytest.mark.anyio
async def test_incremental_sync_replays_the_stored_token():
    session = full_session()
    connector = IcloudCalendarConnector(lambda u, p: session)
    first = await connector.sync(context(), None)
    second = await connector.sync(context(), first.next_cursor)

    assert session.sync_calls == [None, TOKEN_A]
    # Nothing changed server-side: no second fetch, no records.
    assert second.records == []
    assert session.fetched_hrefs == [[SOCCER_HREF, DENTIST_HREF]]
    assert json.loads(second.next_cursor)["calendars"][CALENDAR_URL]["token"] == TOKEN_A


@pytest.mark.anyio
async def test_changed_event_is_refetched_and_updated():
    session = full_session()
    connector = IcloudCalendarConnector(lambda u, p: session)
    first = await connector.sync(context(), None)
    moved = SOCCER_ICS.replace("160000", "170000")
    session.listings[TOKEN_A] = listing(changed=((SOCCER_HREF, '"e9"'),), token=TOKEN_B)
    session.fetches[SOCCER_HREF] = [fetch(SOCCER_HREF, moved)]

    second = await connector.sync(context(), first.next_cursor)

    assert [
        (record.external_id, record.payload["starts_at"].hour) for record in second.records
    ] == [("soccer@example.com", 17)]
    assert session.fetched_hrefs[-1] == [SOCCER_HREF]  # only the changed resource
    state = json.loads(second.next_cursor)
    assert state["calendars"][CALENDAR_URL]["token"] == TOKEN_B


@pytest.mark.anyio
async def test_server_tombstone_removes_the_mirror_record():
    session = full_session()
    connector = IcloudCalendarConnector(lambda u, p: session)
    first = await connector.sync(context(), None)
    # A resource mirrored earlier was deleted on the server.
    session.listings[TOKEN_A] = listing(deleted=(SOCCER_HREF,), token=TOKEN_B)

    second = await connector.sync(context(), first.next_cursor)

    (tombstone,) = second.records
    assert tombstone.external_id == "soccer@example.com"
    assert tombstone.deleted is True
    assert tombstone.external_type == CALENDAR_EVENT
    state = json.loads(second.next_cursor)
    assert SOCCER_HREF not in state["calendars"][CALENDAR_URL]["items"]


@pytest.mark.anyio
async def test_merge_tombstones_folds_both_404_wire_shapes_together():
    """caldav's parser puts response-level 404s in `deleted` but surfaces
    the RFC 6578 propstat shape as an etag-less changed entry; the merge
    must treat both as deletions and keep only real changes."""
    response_level = DAVResponse.from_bytes(
        b"""<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response><D:href>/cal/gone.ics</D:href>
    <D:status>HTTP/1.1 404 Not Found</D:status></D:response>
  <D:response><D:href>/cal/kept.ics</D:href>
    <D:propstat><D:prop><D:getetag>"x"</D:getetag></D:prop>
      <D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>
  <D:sync-token>tok-9</D:sync-token>
</D:multistatus>"""
    )
    merged = merge_tombstones(response_level.parse_sync_collection())
    assert merged.changed == (("/cal/kept.ics", '"x"'),)
    assert merged.deleted == ("/cal/gone.ics",)
    assert merged.token == "tok-9"

    propstat_level = DAVResponse.from_bytes(
        b"""<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response><D:href>/cal/gone.ics</D:href>
    <D:propstat><D:prop><D:getetag/></D:prop>
      <D:status>HTTP/1.1 404 Not Found</D:status></D:propstat></D:response>
  <D:response><D:href>/cal/kept.ics</D:href>
    <D:propstat><D:prop><D:getetag>"y"</D:getetag></D:prop>
      <D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>
  <D:sync-token>tok-9</D:sync-token>
</D:multistatus>"""
    )
    merged = merge_tombstones(propstat_level.parse_sync_collection())
    assert merged.changed == (("/cal/kept.ics", '"y"'),)
    assert merged.deleted == ("/cal/gone.ics",)


@pytest.mark.anyio
async def test_cancelled_status_mirrors_as_tombstone():
    cancelled = SOCCER_ICS.replace("SUMMARY:Soccer practice", "SUMMARY:Soccer\nSTATUS:CANCELLED")
    session = full_session()
    session.fetches[SOCCER_HREF] = [fetch(SOCCER_HREF, cancelled)]

    result = await IcloudCalendarConnector(lambda u, p: session).sync(context(), None)

    record = next(r for r in result.records if r.external_id == "soccer@example.com")
    assert record.deleted is True
    # Cancelled events stay out of the href memory: nothing left to remove.
    state = json.loads(result.next_cursor)
    assert state["calendars"][CALENDAR_URL]["items"][SOCCER_HREF] == []


@pytest.mark.anyio
async def test_invalidated_token_full_relist_is_a_normal_sync():
    """RFC 6578 lets iCloud answer an unknown token with the full listing;
    the connector must treat that as a plain full re-sync, not corruption."""
    session = full_session()
    connector = IcloudCalendarConnector(lambda u, p: session)
    first = await connector.sync(context(), None)
    session.listings[TOKEN_A] = initial_listing()  # full listing again, new token

    second = await connector.sync(context(), first.next_cursor)

    assert {record.external_id for record in second.records} == {
        "soccer@example.com",
        "dentist@example.com",
    }
    assert all(record.deleted is False for record in second.records)
    state = json.loads(second.next_cursor)
    assert state["calendars"][CALENDAR_URL]["token"] == TOKEN_A


@pytest.mark.anyio
async def test_report_failure_falls_back_to_full_calendar_query():
    session = full_session()
    session.report_error = True

    result = await IcloudCalendarConnector(lambda u, p: session).sync(context(), None)

    assert {record.external_id for record in result.records} >= {"soccer@example.com"}
    state = json.loads(result.next_cursor)
    assert state["calendars"][CALENDAR_URL]["token"] is None  # retry sync next run


@pytest.mark.anyio
async def test_corrupt_cursor_starts_fresh():
    session = full_session()
    await IcloudCalendarConnector(lambda u, p: session).sync(context(), "not-json{")
    assert session.sync_calls == [None]


@pytest.mark.anyio
async def test_missing_credentials_are_rejected_before_any_io():
    connector = IcloudCalendarConnector(lambda u, p: full_session())
    with pytest.raises(ValueError, match="app_specific_password"):
        await connector.sync(context(**{CREDENTIAL_ASP: ""}), None)


def test_sync_collection_body_requests_etags_only():
    body = sync_collection_body("tok-1")
    assert "sync-collection" in body
    assert "<D:sync-token>tok-1</D:sync-token>" in body
    assert "getetag" in body
    assert "calendar-data" not in body


def test_sync_collection_body_with_no_token_is_the_initial_listing_request():
    assert "<D:sync-token />" in sync_collection_body(None)


def test_multiget_body_carries_the_hrefs():
    body = calendar_multiget_body([SOCCER_HREF, DENTIST_HREF])
    assert "calendar-multiget" in body
    assert body.count("<D:href>") == 2
    assert SOCCER_HREF in body
    assert "calendar-data" in body


def test_calendar_query_body_filters_vevents():
    body = calendar_query_body()
    assert "calendar-query" in body
    assert 'name="VCALENDAR"' in body
    assert 'name="VEVENT"' in body


def test_caldav_parser_reads_both_wire_shapes():
    """Document the raw parser behavior merge_tombstones normalizes:
    response-level 404 lands in `deleted`, propstat-level 404 in `changed`
    without an etag."""
    response_level = DAVResponse.from_bytes(
        b"""<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response><D:href>/cal/gone.ics</D:href>
    <D:status>HTTP/1.1 404 Not Found</D:status></D:response>
  <D:response><D:href>/cal/kept.ics</D:href>
    <D:propstat><D:prop><D:getetag>"x"</D:getetag></D:prop>
      <D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>
  <D:sync-token>tok-9</D:sync-token>
</D:multistatus>"""
    )
    result = response_level.parse_sync_collection()
    assert [href for href, _etag in [(c.href, c.etag) for c in result.changed] if _etag] == [
        "/cal/kept.ics"
    ]
    assert result.deleted == ["/cal/gone.ics"]

    propstat_level = DAVResponse.from_bytes(
        b"""<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response><D:href>/cal/gone.ics</D:href>
    <D:propstat><D:prop><D:getetag/></D:prop>
      <D:status>HTTP/1.1 404 Not Found</D:status></D:propstat></D:response>
  <D:sync-token>tok-9</D:sync-token>
</D:multistatus>"""
    )
    parsed = propstat_level.parse_sync_collection()
    assert parsed.deleted == []
    assert [(item.href, item.etag) for item in parsed.changed] == [("/cal/gone.ics", None)]


def test_decode_cursor_rejects_foreign_payloads():
    assert decode_cursor(None) == {"calendars": {}}
    assert decode_cursor("[]") == {"calendars": {}}
    assert decode_cursor('{"version": 1}') == {"calendars": {}}
    assert decode_cursor('{"calendars": {"a": {"token": "t", "items": {}}}}')["calendars"] == {
        "a": {"token": "t", "items": {}}
    }


# --- Acceptance path: connector → ConnectorService → CalendarService ---


class FakeMirrorRepository(CalendarRepository):
    """Identity lookups in Python; the seam CalendarService applies through."""

    def __init__(self):
        self.events = []

    async def upsert_mirror(self, household_id, connector, external_id, fields):
        event = next(
            (
                e
                for e in self.events
                if (e.household_id, e.external_connector, e.external_id)
                == (household_id, connector, external_id)
            ),
            None,
        )
        if event is None:
            event = Event(
                id=new_uuid(),
                household_id=household_id,
                external_connector=connector,
                external_id=external_id,
                status="scheduled",
                created_at=utc_now(),
                updated_at=utc_now(),
                **fields,
            )
            self.events.append(event)
        else:
            for name, value in fields.items():
                setattr(event, name, value)
        return event

    async def remove_mirror(self, household_id, connector, external_id):
        for index, event in enumerate(self.events):
            if (event.household_id, event.external_connector, event.external_id) == (
                household_id,
                connector,
                external_id,
            ):
                del self.events[index]
                return True
        return False


class FakeHouseholdRepository(HouseholdRepository):
    def __init__(self):
        pass

    async def get(self, household_id=None):
        return None


class FakeCursorRepository:
    def __init__(self):
        self.rows: dict[tuple[UUID, str], str] = {}

    async def get(self, household_id, connector):
        return self.rows.get((household_id, connector))

    async def save(self, household_id, connector, cursor):
        self.rows[(household_id, connector)] = cursor

    async def clear(self, household_id, connector):
        return self.rows.pop((household_id, connector), None) is not None


@pytest.mark.anyio
async def test_new_changed_deleted_events_mirror_within_one_poll_cycle():
    """The ticket's acceptance criterion, offline end to end."""
    mirrors = FakeMirrorRepository()
    household_id = uuid4()
    context_ = context()
    store = FakeCursorRepository()
    registry = ConnectorRegistry()
    registry.register(IcloudCalendarConnector(lambda u, p: full_session()))
    connector_service = ConnectorService(registry, store)
    calendar_service = CalendarService(mirrors, FakeHouseholdRepository())

    # Poll 1: new events land.
    result = await connector_service.sync(CONNECTOR_NAME, context_)
    report = await calendar_service.apply_external_records(household_id, result.records)
    assert (report.applied, report.removed, report.skipped) == (2, 0, 0)
    assert {event.title for event in mirrors.events} == {"Soccer practice", "Dentist"}

    # Poll 2: one event changed server-side, one was deleted on iCloud.
    session_two = full_session()
    session_two.listings[TOKEN_A] = listing(
        changed=((DENTIST_HREF, '"e3"'),), deleted=(SOCCER_HREF,), token=TOKEN_B
    )
    session_two.fetches[DENTIST_HREF] = [
        fetch(DENTIST_HREF, DENTIST_ICS.replace("Dentist", "Dentist (moved)"))
    ]
    registry = ConnectorRegistry()
    registry.register(IcloudCalendarConnector(lambda u, p: session_two))
    connector_service = ConnectorService(registry, store)
    result = await connector_service.sync(CONNECTOR_NAME, context_)

    report = await calendar_service.apply_external_records(household_id, result.records)
    assert (report.applied, report.removed) == (1, 1)
    assert [event.title for event in mirrors.events] == ["Dentist (moved)"]
    assert mirrors.events[0].external_id == "dentist@example.com"
    assert mirrors.events[0].recurrence_weekdays is None


@pytest.mark.anyio
async def test_stale_cursor_clears_stored_state_for_full_resync():
    """A revoked app-specific password surfaces as StaleCursorError; the
    service clears the cursor so the next successful sync re-lists fully."""
    store = FakeCursorRepository()
    seed = full_session()
    stale = FakeCalDavSession(listings=seed.listings, fetches=seed.fetches, stale_on_token=True)
    registry = ConnectorRegistry()
    registry.register(IcloudCalendarConnector(lambda u, p: stale))
    service = ConnectorService(registry, store)
    context_ = context()
    await service.sync(CONNECTOR_NAME, context_)
    assert await store.get(UUID(context_.household_id), CONNECTOR_NAME) is not None
    with pytest.raises(StaleCursorError):
        await service.sync(CONNECTOR_NAME, context_)
    assert await store.get(UUID(context_.household_id), CONNECTOR_NAME) is None
