"""Apple iCloud Calendar connector — CalDAV polling, read-only v1.

iCloud exposes no official calendar API and no push channel (no webhooks,
no subscriptions), so this connector *polls* CalDAV at
``caldav.icloud.com``: one sync-collection REPORT per calendar per run,
full re-list only when the server invalidates the token (RFC 6578 says
servers may, and iCloud does). Worst-case staleness is the per-household
polling cadence — that is inherent to the design, not a bug.

Authentication is HTTP Basic over TLS with a per-member app-specific
password (the Apple ID must have 2FA; the plaintext lives only in the
encrypted credential store and in memory — see `ConnectorContext.credentials`).
Credential names follow the module constants: ``apple_id`` plus
``app_specific_password``. Any 401/403 (revoked password, primary-password
change — Apple revokes all app-specific passwords instantly) surfaces as
`StaleCursorError`, so `ConnectorService` clears the stored cursor and the
next successful sync starts from a clean full listing.

The cursor is the RFC 6578 sync-token map, one token per calendar,
serialized as JSON. Deletions arrive as hrefs in the sync response; the
server never sends the deleted event's UID, so the cursor also carries a
per-calendar ``items`` map (href → mirrored external ids) — the standard
WebDAV-sync client-side database. A tombstone for an href the connector
never mirrored is dropped silently (nothing to remove).

Sync mechanics per calendar: the stored token is replayed as a
sync-collection REPORT; a rejected or unsupported token degrades to a full
calendar-query (the getctag-era fallback) with no deletions — that is the
full re-sync path, and an event whose content is unchanged is idempotent
at the applier because `content_hash` never hashes raw ICS bytes. Events
with ``STATUS:CANCELLED`` become tombstones, same policy as Google's
cancelled events. Parsing lives in `nidaro.connectors.icloud_ics`.

Read-only by design: write-back to a member's personal calendar (PUT with
etag preconditions, invitation side effects) is deliberately out of scope
for v1 — see docs/research/apple-calendar-integration.md §5.
"""

import asyncio
import json
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from caldav.lib.error import AuthorizationError, ReportError

from nidaro.connectors.base import StaleCursorError
from nidaro.connectors.icloud_ics import (
    content_hash,
    external_id,
    parse_events,
    record_payload,
)
from nidaro.connectors.models import ConnectorContext, ExternalRecord, SyncResult
from nidaro.db.types import utc_now

CONNECTOR_NAME = "icloud_calendar"
ICLOUD_URL = "https://caldav.icloud.com/"
CREDENTIAL_USERNAME = "apple_id"
CREDENTIAL_ASP = "app_specific_password"

CALENDAR_EVENT = "calendar_event"

# Resources per calendar-multiget REPORT; iCloud handles more, but modest
# chunks keep any single request small and retryable.
FETCH_CHUNK = 100


class MissingCredentialError(ValueError):
    """The household's connector config has no usable iCloud credentials."""


class SyncUnsupportedError(RuntimeError):
    """The server rejected the sync-collection REPORT itself.

    Raised by the adapter when caldav reports a REPORT-level failure —
    the connector answers with a full calendar-query, the getctag-era
    fallback.
    """


@dataclass(frozen=True)
class SyncChanges:
    """One sync-collection REPORT reply, translated to plain values.

    ``deleted`` also carries changed entries that came back without an
    etag: caldav's response parser only recognizes response-level 404s,
    while the RFC 6578 example shape (and iCloud's) puts the 404 inside a
    propstat, where it surfaces as an entry with no etag. Treating both
    shapes as tombstones covers every server variant.
    """

    changed: tuple[tuple[str, str], ...]  # (href, etag)
    deleted: tuple[str, ...]
    token: str | None

    @property
    def changed_hrefs(self) -> list[str]:
        return [href for href, _ in self.changed]


@dataclass(frozen=True)
class FetchedIcs:
    href: str
    ics: str


class CalDavSession(Protocol):
    """What the connector needs from CalDAV — sync (blocking) calls.

    The default implementation wraps the caldav library's synchronous
    client (its most battle-tested path) and runs behind `asyncio.to_thread`,
    so the connector's own interface stays async per house rules. Tests
    substitute a fake, keeping every fixture offline.
    """

    def calendar_urls(self) -> list[str]: ...

    def sync_changes(self, calendar_url: str, token: str | None) -> SyncChanges: ...

    def fetch(self, calendar_url: str, hrefs: Sequence[str]) -> list[FetchedIcs]: ...

    def calendar_query(self, calendar_url: str) -> list[FetchedIcs]: ...


SessionFactory = Callable[[str, str], CalDavSession]


def sync_collection_body(token: str | None) -> str:
    """RFC 6578 sync-collection REPORT asking for etags (no calendar data)."""
    ns = "urn:ietf:params:xml:ns:caldav"
    root = ET.Element(f"{{{ns}}}sync-collection")
    ET.SubElement(root, "{DAV:}sync-token").text = token or ""
    ET.SubElement(root, "{DAV:}sync-level").text = "1"
    props = ET.SubElement(root, "{DAV:}prop")
    ET.SubElement(props, "{DAV:}getetag")
    return _xml(root)


def calendar_multiget_body(hrefs: Sequence[str]) -> str:
    """RFC 4791 §7.9 calendar-multiget REPORT fetching ICS bodies."""
    ns = "urn:ietf:params:xml:ns:caldav"
    root = ET.Element(f"{{{ns}}}calendar-multiget")
    props = ET.SubElement(root, "{DAV:}prop")
    ET.SubElement(props, "{DAV:}getetag")
    ET.SubElement(props, f"{{{ns}}}calendar-data")
    for href in hrefs:
        ET.SubElement(root, "{DAV:}href").text = href
    return _xml(root)


def calendar_query_body() -> str:
    """RFC 4791 §7.8 calendar-query REPORT listing every VEVENT with data."""
    ns = "urn:ietf:params:xml:ns:caldav"
    root = ET.Element(f"{{{ns}}}calendar-query")
    props = ET.SubElement(root, "{DAV:}prop")
    ET.SubElement(props, "{DAV:}getetag")
    ET.SubElement(props, f"{{{ns}}}calendar-data")
    filter_ = ET.SubElement(root, f"{{{ns}}}filter")
    comp = ET.SubElement(filter_, f"{{{ns}}}comp-filter", {"name": "VCALENDAR"})
    ET.SubElement(comp, f"{{{ns}}}comp-filter", {"name": "VEVENT"})
    return _xml(root)


def _xml(root: ET.Element) -> str:
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


# Stable, readable prefixes for the two REPORT namespaces.
ET.register_namespace("D", "DAV:")
ET.register_namespace("C", "urn:ietf:params:xml:ns:caldav")


class CaldavIcloudClient:
    """CalDavSession over the caldav library's synchronous client.

    Deliberately sync: the caldav maintainer recommends the sync path for
    production use, and the connector offloads it with `asyncio.to_thread`.
    Discovery (principal → calendar-home-set → calendars) is the library's
    RFC 5397/4791 flow; the REPORTs are built here so tombstone shapes and
    paging stay explicit.
    """

    def __init__(self, username: str, password: str, url: str = ICLOUD_URL) -> None:
        from caldav import DAVClient

        # One client per sync run; sessions are not shared across tasks.
        self._client = DAVClient(url=url, username=username, password=password, timeout=60)

    def calendar_urls(self) -> list[str]:
        with _translate_auth_errors():
            principal = self._client.principal()
            return [str(calendar.url) for calendar in principal.calendars()]

    def sync_changes(self, calendar_url: str, token: str | None) -> SyncChanges:
        with _translate_auth_errors():
            response = self._client.report(calendar_url, sync_collection_body(token), depth=1)
            return merge_tombstones(response.parse_sync_collection())

    def fetch(self, calendar_url: str, hrefs: Sequence[str]) -> list[FetchedIcs]:
        fetched: list[FetchedIcs] = []
        for start in range(0, len(hrefs), FETCH_CHUNK):
            chunk = hrefs[start : start + FETCH_CHUNK]
            with _translate_auth_errors():
                response = self._client.report(
                    calendar_url, calendar_multiget_body(chunk), depth=None
                )
                for item in response.parse_calendar_query():
                    if item.calendar_data:
                        fetched.append(FetchedIcs(href=item.href, ics=item.calendar_data))
        return fetched

    def calendar_query(self, calendar_url: str) -> list[FetchedIcs]:
        with _translate_auth_errors():
            response = self._client.report(calendar_url, calendar_query_body(), depth=1)
            return [
                FetchedIcs(href=item.href, ics=item.calendar_data)
                for item in response.parse_calendar_query()
                if item.calendar_data
            ]


class _translate_auth_errors:
    """Surface revoked credentials as a stale cursor (reset on next success)."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None and issubclass(exc_type, AuthorizationError):
            raise StaleCursorError(
                "iCloud rejected the credentials — the app-specific password was "
                "likely revoked; clearing sync state for a full re-sync after reconnect"
            ) from exc
        if exc_type is not None and issubclass(exc_type, ReportError):
            raise SyncUnsupportedError(str(exc)) from exc
        return False


def decode_cursor(raw: str | None) -> dict:
    """Cursor JSON → state dict; corrupt or foreign payloads start fresh."""
    if not raw:
        return {"calendars": {}}
    try:
        state = json.loads(raw)
    except ValueError:
        return {"calendars": {}}
    if not isinstance(state, dict) or not isinstance(state.get("calendars"), dict):
        return {"calendars": {}}
    return state


def merge_tombstones(parsed) -> SyncChanges:
    """Normalize a parsed sync-collection reply, folding 404 shapes together.

    caldav's response parser recognizes only response-level 404s; the RFC
    6578 example shape (and iCloud's) hides the 404 inside a propstat,
    which surfaces as a changed entry with no etag. Both mean the resource
    is gone, so both land in `deleted`; anything with an etag is a real
    change. Accepts the parser's result duck-typed, so tests replay real
    parser output without a server.
    """
    changed = tuple((item.href, item.etag) for item in parsed.changed if item.etag is not None)
    deleted = tuple(parsed.deleted) + tuple(
        item.href for item in parsed.changed if item.etag is None
    )
    return SyncChanges(changed=changed, deleted=deleted, token=parsed.sync_token)


def encode_cursor(state: dict) -> str:
    return json.dumps(state, sort_keys=True, separators=(",", ":"))


class IcloudCalendarConnector:
    """Mirrors iCloud calendars into ExternalRecords, read-only, token-driven."""

    name = CONNECTOR_NAME

    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory

    def _session(self, credentials: dict[str, str]) -> CalDavSession:
        username = credentials.get(CREDENTIAL_USERNAME)
        password = credentials.get(CREDENTIAL_ASP)
        if not username or not password:
            raise MissingCredentialError(
                f"{CONNECTOR_NAME} needs the '{CREDENTIAL_USERNAME}' and "
                f"'{CREDENTIAL_ASP}' credentials for the household; store "
                "them via ConnectorCredentialService and reference them in the "
                "connector config"
            )
        if self._session_factory is None:
            return CaldavIcloudClient(username, password)
        return self._session_factory(username, password)

    async def sync(self, context: ConnectorContext, cursor: str | None) -> SyncResult:
        session = self._session(context.credentials)
        state = decode_cursor(cursor)
        calendars = state["calendars"]
        records: list[ExternalRecord] = []
        for url in await asyncio.to_thread(session.calendar_urls):
            entry = calendars.get(url) or {}
            items: dict[str, list[str]] = entry.get("items") or {}
            try:
                changes = await asyncio.to_thread(session.sync_changes, url, entry.get("token"))
            except SyncUnsupportedError:
                # The full re-list fallback: everything comes back, deletions
                # are unknowable, and the next run retries the sync REPORT.
                fetched = await asyncio.to_thread(session.calendar_query, url)
                for resource in fetched:
                    mirror_records, mirrored_ids = _records_for_resource(resource, url, context)
                    records.extend(mirror_records)
                    items[resource.href] = mirrored_ids
                calendars[url] = {"token": None, "items": items}
                continue
            for href in changes.deleted:
                # Tombstones only remove what this connector mirrored; an
                # unknown href was never fetched (or is already forgotten).
                for external_id_value in items.pop(href, []):
                    records.append(
                        ExternalRecord(
                            connector=CONNECTOR_NAME,
                            external_type=CALENDAR_EVENT,
                            external_id=external_id_value,
                            payload={},
                            content_hash="",
                            observed_at=utc_now(),
                            deleted=True,
                        )
                    )
            if changes.changed_hrefs:
                for resource in await asyncio.to_thread(session.fetch, url, changes.changed_hrefs):
                    mirror_records, mirrored_ids = _records_for_resource(resource, url, context)
                    records.extend(mirror_records)
                    items[resource.href] = mirrored_ids
            calendars[url] = {"token": changes.token, "items": items}
        return SyncResult(records=records, next_cursor=encode_cursor(state))


def _records_for_resource(
    resource: FetchedIcs, calendar_url: str, context: ConnectorContext
) -> tuple[list[ExternalRecord], list[str]]:
    """One fetched resource → ExternalRecords plus the href→id memory.

    ``STATUS:CANCELLED`` events become tombstone records (``deleted=True``)
    and are kept out of the href memory: the calendar mirror must not show
    an event that will not happen, and a server-side tombstone for the
    href later finds nothing left to remove.
    """
    records: list[ExternalRecord] = []
    mirrored_ids: list[str] = []
    for event in parse_events(resource.ics, context.timezone):
        identity = external_id(event)
        cancelled = event.status == "cancelled"
        if not cancelled:
            mirrored_ids.append(identity)
        records.append(
            ExternalRecord(
                connector=CONNECTOR_NAME,
                external_type=CALENDAR_EVENT,
                external_id=identity,
                payload=record_payload(event, calendar_url, resource.href),
                content_hash=content_hash(event),
                observed_at=utc_now(),
                deleted=cancelled,
            )
        )
    return records, mirrored_ids
