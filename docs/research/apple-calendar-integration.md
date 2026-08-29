# Apple Calendar integration for nidaro — research findings

Researched 2026-02 against Apple support/developer docs, RFCs 4791/5545/6578/6638, and library source code. For an engineer who knows nidaro but not CalDAV.

## Summary verdict

Build the iCloud integration as **polling CalDAV against `caldav.icloud.com` with per-member app-specific passwords**. There is no official Apple calendar API, no push channel, and no OAuth option available to a Linux server — CalDAV with HTTP Basic auth over TLS is the only programmatic path that reads *and* writes, and Apple has never documented it publicly, so it must be treated as an unofficial-but-stable surface used by every third-party calendar client. Sync mechanics are well covered: iCloud supports the RFC 6578 `sync-collection` REPORT with opaque sync-tokens plus the CalendarServer `getctag` property, which maps cleanly onto nidaro's `Connector.sync(context, cursor)` with the sync-token as `next_cursor`. Ship v1 **read-only**: parse each VEVENT into an `ExternalRecord` (one per `UID`+`RECURRENCE-ID`) and apply it to the `events` table through `CalendarService`; defer write-back to a later, separately-flagged service because writing into a member's personal iCloud calendar carries invitation and conflict risks with little product payoff. Run the sync `caldav` library (actively maintained, Apache-2.0 dual-licensed, Python 3.14 tested) inside `asyncio.to_thread` from a Taskiq-scheduled job on a 10–15 minute cadence.

---

## 1. The option space, ranked

### Option A (recommended): iCloud CalDAV at `caldav.icloud.com`

iCloud runs a descendant of Apple's CalendarServer behind `caldav.icloud.com` (TLS, port 443), speaking CalDAV (RFC 4791) over WebDAV (RFC 4918). Apple has **never officially documented** this service — the python-caldav maintainer states plainly that "Apple has never officially said that they do support CalDAV in iCloud" ([python-caldav issue #3](https://github.com/python-caldav/caldav/issues/3)), and the library docs repeat that "iCloud supports CalDAV partly, but there exists no official information about it" ([caldav docs, Server-specific highlights](https://caldav.readthedocs.io/latest/about.html)). Despite that, it is the same interface Apple's own macOS/iOS Calendar client uses, and every serious third-party client (Thunderbird, Home Assistant, Outlook via manual setup) connects through it.

Facts that matter for implementation:

- **Endpoint discovery.** You do not need a per-account URL. Start from `https://caldav.icloud.com/` and run the standard WebDAV discovery: a `PROPFIND` for `DAV:current-user-principal` (RFC 5397), then a `PROPFIND` on the principal for `CALDAV:calendar-home-set` (RFC 4791 §6.2.1). The resolved calendar URLs look like `https://p12-caldav.icloud.com/17112341234/calendars/12345@example.com/` — the `pNN` host shard and numeric IDs differ per account ([caldav docs, notes on CalDAV URLs](https://caldav.readthedocs.io/latest/about.html); [issue #3](https://github.com/python-caldav/caldav/issues/3)). The python-caldav library performs this discovery automatically from the bare root URL.
- **Authentication.** HTTP Basic auth over TLS with the Apple Account username and an **app-specific password** — a normal account password is rejected for third-party clients. See §6 for credential details ([Apple: app-specific passwords](https://support.apple.com/en-us/102654)).
- **Read and write.** Calendars are WebDAV collections of `.ics` resources. `GET` fetches, `PUT` creates/updates (`If-None-Match: *` for create, `If-Match: "<etag>"` for update, RFC 4791 §5.3.2), `DELETE` removes. The python-caldav author confirms "basic access into events on calendars in iCloud, as well as to save changes" works ([issue #3](https://github.com/python-caldav/caldav/issues/3)).
- **Known gaps on iCloud CalDAV.** No free/busy queries, no journal entries, tasks (Reminders) not accessible through CalDAV, `object_by_uid` lookups historically broken, and a single `UID` cannot live on two calendars at once ([issue #3](https://github.com/python-caldav/caldav/issues/3)).
- **Invites/attendees.** ATTENDEE/ORGANIZER fields arrive inside the ICS payloads (RFC 5545). Acting on invites (i.e. replying) requires CalDAV scheduling, RFC 6638 `calendar-auto-schedule` / schedule-inboxes ([RFC 6638](https://datatracker.ietf.org/doc/html/rfc6638)). iCloud's support for RFC 6638 over CalDAV is not officially documented and python-caldav's RFC 6638 support is work-in-progress ([caldav docs, RFC compliance](https://caldav.readthedocs.io/latest/about.html)). Treat invite *participation* as out of scope for v1; passive reading of attendee fields is fine.

### Option B (fallback for read-only use cases): public ICS subscription links

iCloud's "Public Calendar" share produces a no-auth URL (`https://pNN-caldav.icloud.com/published/2/<opaque>`, offered as `webcal://`) that serves the calendar as an iCalendar feed. Apple documents the toggle: "Turn on Public Calendar… Share the calendar with a link," and notes "Anyone who has the link can view and subscribe to it, even if they don't use iCloud" ([Share a calendar on iCloud.com](https://support.apple.com/guide/icloud/share-a-calendar-mm6b1a9479/icloud), [What you can do with iCloud and Calendar](https://support.apple.com/guide/icloud/what-you-can-do-with-icloud-and-calendar-mm15eb200ab4/icloud)).

Limitations: strictly read-only; no authentication (the link *is* the credential — leaking it leaks the whole calendar); the URL regenerates when the user toggles sharing off/on ([observed in GAS-ICS-Sync #261](https://github.com/derekantrican/GAS-ICS-Sync/issues/261)); each poll re-downloads the entire feed (no incremental sync); and it requires per-calendar manual setup by the member rather than account-level discovery. Useful as a zero-credential demo path or for calendars members refuse to give real access to; not the main integration.

### Option C (not viable): EventKit / EventKitSync

EventKit is an Apple OS framework — iOS, iPadOS, macOS, Mac Catalyst, visionOS, watchOS only — that reads and writes the **on-device** calendar database, which the OS keeps in sync with iCloud ([Apple: EventKit](https://developer.apple.com/documentation/eventkit)). It is not portable to Linux, and nidaro's sync would need a fleet of always-on Apple devices to mediate. Dead end; documented here so nobody re-litigates it.

### Option D (verified not to exist): a newer official Apple API

As of this research there is **no public REST/JSON calendar API** for iCloud: no SDK, no developer portal ([Nylas Apple Calendar cookbook](https://developer.nylas.com/docs/cookbook/calendar/apple-calendar-api/), and nothing on [Apple Developer News](https://developer.apple.com/news/)).

One genuinely new thing in 2025 must be addressed: Apple now offers "authorize the app using your Apple Account" for third-party apps accessing iCloud Mail, Calendar, and Contacts ([Apple support 121539, published 2025-10-07](https://support.apple.com/en-us/121539)), and the iCloud Mail setup doc points Windows Outlook 2021+ users at it ([support 102525, published 2026-02-03](https://support.apple.com/en-us/102525)). This is an authorization flow for **supported client applications**, not a documented OAuth API: Apple names no endpoints, scopes, client registration, or refresh-token grant. Thunderbird — the reference implementation for open-source calendar/mail OAuth — has **no Apple issuer** in its built-in OAuth2 provider registry as of current `master` ([comm-central `OAuth2Providers.sys.mjs`](https://github.com/mozilla/releases-comm-central/blob/master/mailnews/base/src/OAuth2Providers.sys.mjs)). A headless Linux server cannot go through an interactive device-flow approval, and there is no published token endpoint to code against. Conclusion: not usable for nidaro today; revisit if Apple publishes an OAuth API.

## 2. CalDAV sync mechanics

### Sync strategies defined by the RFCs

Three mechanisms exist, in decreasing order of preference:

1. **`sync-collection` REPORT with `DAV:sync-token` (RFC 6578).** The client sends a REPORT containing the token it received last time; the server answers with a multistatus listing only member URLs added/changed/removed since then, plus a fresh token ([RFC 6578 §3.2](https://datatracker.ietf.org/doc/html/rfc6578#section-3.2)). Results may be truncated; the client pages with `DAV:limit`/`nresults` ([RFC 6578 §3.6–3.7](https://datatracker.ietf.org/doc/html/rfc6578#section-3.6)). Tokens can be invalidated: the `DAV:valid-sync-token` precondition says a token "MUST be a valid token previously returned by the server," that "servers might need to invalidate tokens previously returned to clients," forcing a full re-list, and that servers "MUST limit themselves to invalidating tokens only when absolutely necessary" ([RFC 6578 §3.2, Preconditions](https://datatracker.ietf.org/doc/html/rfc6578#section-3.2)). Clients must handle the full-list fallback gracefully.
2. **`getctag` / etag polling.** `http://calendarserver.org/ns/` `getctag` is a CalendarServer extension property that changes on any collection mutation; the client compares it cheaply and only downloads when it differs. `getetag` comparisons detect which specific resources changed.
3. **Time-range REPORT queries** (`CALDAV:calendar-query` with `time-range`, optionally `CALDAV:expand` for server-side recurrence expansion, RFC 4791 §7.8/§9.6.5). Stateless, no cursor — every poll re-fetches the window. Used by Home Assistant's CalDAV integration for its "next event" view.

### What iCloud actually supports

Verified against wire captures of real iCloud traffic and library source:

- iCloud **implements the `sync-collection` REPORT**, including incremental token sync and `DAV:limit` paging; real request/response captures against `p34-caldav.icloud.com` show opaque base64 sync-tokens and successful incremental REPORTs ([Aurinko, CalDAV Apple Calendar integration](https://www.aurinko.io/blog/caldav-apple-calendar-integration/)). The same capture shows iCloud answering `PROPFIND` with both `getctag` and `DAV:sync-token` on the calendar collection — and notably the `getctag` value and `sync-token` value are the same opaque string on iCloud.
- **Tokens can be dropped.** The python-caldav author: "a calendar server (in this case, iCloud) may eventually drop a sync token — in that case the URL for all events… will be returned" when calling `objects_by_sync_token`, which is why the library re-checks etags on full listings ([python-caldav issue #122](https://github.com/python-caldav/caldav/issues/122)). This is the RFC-sanctioned invalidation path; nidaro's connector must treat "empty cursor result = full sync" as normal, not as corruption.
- `calendar-multiget` (fetch many hrefs in one REPORT) is REQUIRED for CalDAV servers ([RFC 4791 §7.9](https://datatracker.ietf.org/doc/html/rfc4791#section-7.9)) and is how batch downloads should be done after a sync-report.
- Discovery works from the bare `https://caldav.icloud.com/` root per the standard principal → home-set flow ([caldav docs](https://caldav.readthedocs.io/latest/about.html); [RFC 4791 §6.2.1](https://datatracker.ietf.org/doc/html/rfc4791#section-6.2.1)).

### Polling frequency and abuse

There is **no push channel**: CalDAV has no webhooks, and Apple exposes no notification API for calendar changes — periodic polling is the only option. Apple publishes no rate limits or quotas for CalDAV, so treat pacing as a courtesy-plus-defensive measure: Home Assistant's caldav integration enforces `MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=15)` ([HA caldav coordinator source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/caldav/coordinator.py)). Recommendation: one sync-collection REPORT per calendar per 10–15 minutes with jitter, a `getctag`/`sync-token` short-circuit so a no-change poll costs one request, and exponential backoff on any non-2xx. Community reports of iCloud CalDAV connections flaking (IPv6-related sign-in failures, intermittent disabled integrations) exist ([python-caldav issue #393](https://github.com/python-caldav/caldav/issues/393)); none are officially characterized, which is itself the point — fly under the radar.

## 3. iCalendar data handling

### Parsing

Use **`icalendar`** (collective project): v7.3.0 on PyPI, uploaded 2026-08, requires Python ≥ 3.10, RFC 5545 parser/generator ([PyPI: icalendar](https://pypi.org/project/icalendar/)). It is the parser python-caldav itself adopted internally: "as many people requested the vobject dependency to be replaced with icalendar, both are now supported, and the icalendar library is now consistently used internally" ([caldav docs](https://caldav.readthedocs.io/latest/about.html)). Since icalendar 6.0 the default timezone implementation is stdlib `zoneinfo`; `from_ical` resolves TZIDs to `ZoneInfo` objects, and `Calendar.add_missing_timezones()` handles the write side ([icalendar usage docs](https://icalendar.readthedocs.io/en/latest/how-to/usage.html)).

Alternatives, for the record: **vobject** 0.9.9 (Dec 2024) is maintained again after years of dormancy ([PyPI: vobject](https://pypi.org/project/vobject/); [caldav docs](https://caldav.readthedocs.io/latest/about.html)) but icalendar is the safer bet; the **`ics`** package has a stalled rewrite and a smaller API surface ([PyPI: ics](https://pypi.org/project/ics/)). For recurrence expansion use **`recurring-ical-events`** 3.8.2 (2026-04, same collective as icalendar) ([PyPI](https://pypi.org/project/recurring-ical-events/)) or `dateutil.rrule` 2.9.0.post0 ([PyPI](https://pypi.org/project/python-dateutil/)) — both deterministic.

### VEVENT structure relevant to nidaro

- A recurring event is one **master VEVENT with an `RRULE`** ([RFC 5545 §3.8.5.3](https://datatracker.ietf.org/doc/html/rfc5545#section-3.8.5.3)). Exceptions are separate VEVENTs with the **same `UID`** and a `RECURRENCE-ID` ([RFC 5545 §3.8.4.4](https://datatracker.ietf.org/doc/html/rfc5545#section-3.8.4.4)) identifying which instance they override. Expand masters deterministically in nidaro code over a bounded window (e.g. now → now+90d); never persist infinite expansions.
- `VALARM` subcomponents are per-device reminder noise ([RFC 5545 §3.6.6](https://datatracker.ietf.org/doc/html/rfc5545#section-3.6.5)); strip them at parse time. Apple events routinely carry one or more.
- Fields that map onto nidaro's `Event` model: `SUMMARY`→`title`, `DESCRIPTION`→`description`, `DTSTART`/`DTEND`→`starts_at`/`ends_at`, `LOCATION`→`location`, `STATUS` (CONFIRMED/CANCELLED/TENTATIVE)→`status`, `ATTENDEE`/`ORGANIZER`→`metadata_`.

### Timezones: do not trust bare TZIDs

TZID parameters are nominally IANA names (`Europe/Oslo`), but Apple-ecosystem servers have historically emitted **vendor-prefixed** TZIDs such as `TZID=/freeassociation.sourceforge.net/Europe/Berlin` (a FreeAssociation/CalendarServer artifact; reported against GNOME Evolution as a source of breakage: [evolution issue #3332](https://gitlab.gnome.org/GNOME/evolution/-/work_items/3332); same format seen in [Rainlendar's CalDAV bug report](https://forum.rainlendar.net/t/time-zone-value-for-caldav-calendar/19133)). The robust approach: resolve TZIDs by taking the trailing path segment if the prefix is a known non-IANA vendor prefix, and otherwise trust the VTIMEZONE component shipped in the same VCALENDAR rather than assuming the TZID string is a `zoneinfo` key. Events with `DATE` (all-day) values have no timezone at all — keep them date-only in the payload.

### Stable `external_id` and `content_hash`

- **`external_id`**: `f"{uid}"` for standalone events, `f"{uid}/{recurrence_id}"` for exceptions, where `recurrence_id` is the normalized RECURRENCE-ID value. UID is the iCalendar-global identifier ([RFC 5545 §3.8.4.7](https://datatracker.ietf.org/doc/html/rfc5545#section-3.8.4.7)) and is stable across edits. iCloud caveat: the same UID cannot exist on two of the account's calendars ([issue #3](https://github.com/python-caldav/caldav/issues/3)), so a per-household connector that watches several calendars should salt the id with the calendar's path or id if the same event can legitimately appear under two iCloud calendars (subscribed/shared).
- **`content_hash`**: hash a **canonical projection of the parsed fields** (title, start UTC, end UTC, all-day flag, status, location, description, sorted attendees, RRULE string, recurrence-id) — e.g. SHA-256 over `json.dumps(..., sort_keys=True)`. Do **not** hash raw ICS bytes: Apple's server rewrites property order, DTSTAMP, and PRODID on round-trip, so byte-hashing produces phantom "changes" on every poll and pollutes the domain table with no-op updates. This is a design decision informed by the general CalDAV property instability noted in the caldav library docs ("the library will modify icalendar data to get around known compatibility issues") ([caldav docs](https://caldav.readthedocs.io/latest/about.html)).

## 4. Python client reality

### `caldav` (python-caldav)

- **Health**: v3.2.1 uploaded 2026-05 ([PyPI: caldav](https://pypi.org/project/caldav/)); tested on Python 3.10–3.14, so it fits nidaro's 3.14 ([caldav docs](https://caldav.readthedocs.io/latest/about.html)). License is **dual GPL-3.0 / Apache-2.0** — use under Apache-2.0, which is dependency-friendly ([caldav docs](https://caldav.readthedocs.io/latest/about.html)). Version 3.x is the current series; 1.x unmaintained.
- **Sync/async**: the library is synchronous by design. Its default HTTP stack is `niquests` with fallbacks to `requests` and the httpx family; an async fallback chain (niquests → httpx2 → httpxyz → httpx) exists since 3.x, but the maintainer's own recommendation is: "In a very sharp production environment (as of 3.x), use the CalDAV library in a sync way, the async version of CalDAV still lacks some real-world testing" ([caldav HTTP library docs](https://caldav.readthedocs.io/latest/http-libraries.html)).
- **Running under asyncio**: wrap the sync calls in `asyncio.to_thread` (a `ThreadPoolExecutor` with a small max_workers bound per connector is enough; the work is I/O-bound HTTP). This is exactly the pattern Home Assistant uses: its caldav coordinator calls `hass.async_add_executor_job(...)` around `caldav` calls ([HA coordinator source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/caldav/coordinator.py)). Writing a custom minimal async WebDAV client on httpx is feasible — nidaro would need only PROPFIND, REPORT (sync-collection, calendar-multiget), GET/PUT/DELETE, which is a small wire surface (see the capture in [Aurinko's write-up](https://www.aurinko.io/blog/caldav-apple-calendar-integration/)) — but it means re-implementing principal/home-set discovery and absorbing iCloud quirks firsthand. Use `caldav` + `to_thread` for v1; revisit only if the thread offload shows up in profiling.
- **iCloud quirks known to the library**: the `icloud` compatibility profile in `caldav/compatibility_hints.py` is only a **commented-out historical list** (duplicate-UID, sticky events, no journal 500s, no todo, no freebusy, `propfind_allprop_failure`, broken get-by-uid) — iCloud is *not* in the library's regularly-tested server matrix ("Google and iCloud haven't been tested for a long time") ([compatibility_hints.py source](https://github.com/python-caldav/caldav/blob/master/caldav/compatibility_hints.py); [caldav docs](https://caldav.readthedocs.io/latest/about.html)). Also: IPv6 on the host can break iCloud sign-in ([issue #393](https://github.com/python-caldav/caldav/issues/393)), and recurring-event test paths against iCloud were disabled years ago ([issue #3](https://github.com/python-caldav/caldav/issues/3)) — expect to verify recurrence behavior against a live account during implementation. None of these are blockers for a read path built on sync-token + multiget.

## 5. Two-way write and conflicts

Mechanics (RFC 4791 §5.3.2, §5.3.4):

- **Create**: `PUT` a `text/calendar` body to a new URL inside the calendar collection with `If-None-Match: *`; server answers `201 Created` with an `ETag`.
- **Update**: `PUT` to the resource's existing URL with `If-Match: "<etag>"`; on concurrent modification the precondition fails with **412 Precondition Failed** — the optimistic-concurrency signal. Re-GET, re-apply, retry.
- **Delete**: `DELETE` with `If-Match`. Skip the precondition to delete regardless of drift.

Why write-back is not worth it for v1:

1. **Deduplication hazards.** iCloud rejects the same UID on two calendars, so nidaro writing mirrored events must invent UIDs and track the mapping — and any event nidaro writes immediately re-enters nidaro's own read loop (self-echo), which the applier must filter by a marker property.
2. **Scheduling side effects.** A PUT containing ATTENDEEs can trigger iTIP invitation processing server-side (RFC 6638 semantics); the exact iCloud behavior is undocumented ([RFC 6638](https://datatracker.ietf.org/doc/html/rfc6638); [caldav docs — RFC 6638 support WIP](https://caldav.readthedocs.io/latest/about.html)).
3. **Conflict UX without a product surface.** 412 retries on a family member's personal calendar need a resolution policy nobody has asked for.

If/when write-back is wanted, restrict it to a dedicated nidaro-owned iCloud calendar created via `MKCALENDAR` (RFC 4791 §5.3.1), tag written events with a marker `X-` property, and expose it as a separate application service — never as connector code (connectors produce external records only; see §7).

## 6. Credentials reality

App-specific passwords ([Apple support 102654, published 2025-10-08](https://support.apple.com/en-us/102654)):

- **Requirement**: the Apple Account must have two-factor authentication; generation happens at account.apple.com → Sign-In and Security → App-Specific Passwords. There is no API to mint them — each family member generates theirs manually.
- **Limits and revocation**: up to **25 active** per account; revocable individually or all at once; revoked apps are signed out until re-provisioned. Changing or resetting the primary Apple Account password **automatically revokes all** app-specific passwords — expect this failure mode and surface it as "reconnect" UX, not as an error.
- **Scope**: an app-specific password grants access to the account's iCloud data services (mail, contacts, calendars) generally — there are no fine-grained scopes and no documented expiry.

Security posture versus Google:

- Google Calendar integrations authenticate via OAuth 2.0 with **scoped, revocable refresh tokens** and standardized revocation ([Google OAuth 2.0 docs](https://developers.google.com/identity/protocols/oauth2)). Apple's app-specific password is closer to a second account password: unscoped, long-lived, revocable only as a whole.
- Storage: store one credential per (household, member) in PostgreSQL, encrypted at rest with application-layer AES-GCM; the key comes from the environment/KMS, never from source control (AGENTS.md forbids secrets in VCS). Display the generated value exactly once at setup.
- Rotation/revocation UX: name each password `nidaro <household> <member>` in the Apple UI so members can identify it; on any 401 from caldav.icloud.com, mark the connector degraded (visible in household settings), keep the last synced data, and prompt for a fresh password. Revocation at Apple is instant and complete — there is no grace period to code against.

## 7. Plugin design for nidaro

Everything below sits inside the existing seams: `src/nidaro/connectors/` for collection, `src/nidaro/calendar/` for application, `src/nidaro/jobs/` for scheduling. Contract-level only.

### Component map

```
Taskiq scheduler (cron */15, LabelScheduleSource)
  -> connector_sync task (jobs/tasks.py, currently a placeholder)
    -> ConnectorService.sync("icloud_calendar", context, cursor)   [connectors/service.py]
      -> IcloudCalendarConnector.sync(context, cursor)             [connectors/icloud_calendar.py, new]
           runs caldav in asyncio.to_thread; I/O stays async at the boundary
      -> applier consumes SyncResult.records
    -> CalendarService.upsert_external_event / delete_external_event  [calendar/service.py, new methods]
      -> CalendarRepository                                        [calendar/repository.py]
```

### `IcloudCalendarConnector`

Satisfies the existing `Connector` Protocol (`name: str`; `async def sync(self, context: ConnectorContext, cursor: str | None) -> SyncResult`).

- `name = "icloud_calendar"`; registered into `ConnectorRegistry` at `ApplicationServices.build` time.
- `context: ConnectorContext(household_id, timezone)` — one connector instance per household; the iCloud account and app-specific password come from the household's stored, encrypted connector config (see gaps below).
- **Cursor**: `next_cursor` is the per-calendar `DAV:sync-token` map, serialized as a compact JSON string `{"<calendar_href>": "<token>", ...}`. `cursor=None` (or a per-calendar missing token, or a `valid-sync-token` failure) triggers discovery + initial full sync for that calendar. Cursors must be persisted per (household, connector) between runs — the repo has no such table yet (see gaps).
- **Flow per sync**:
  1. Build the `caldav` client once (`get_davclient(url="https://caldav.icloud.com/", username=..., password=asp)`) inside `to_thread`; principal → `calendars()` does RFC 5397/4791 discovery.
  2. For each selected calendar: PROPFIND current token; if unchanged from cursor, skip. Else `sync-collection` REPORT with stored token (etags only), paging via `DAV:limit`.
  3. `calendar-multiget` the changed hrefs; DELETE-tombstones from the report become deletion records.
  4. Parse each ICS with `icalendar`; for every VEVENT (masters and RECURRENCE-ID exceptions) emit one `ExternalRecord`.
- **`ExternalRecord` mapping** (existing model in `connectors/models.py`):
  - `connector = "icloud_calendar"`
  - `external_type = "calendar_event"` (tombstones: `"calendar_event_deleted"` — or a `deleted: True` payload flag; pick one and keep SyncResult shape unchanged)
  - `external_id = f"{uid}"` or `f"{uid}/{recurrence_id}"`, optionally prefixed with a calendar-id salt when multiple calendars are watched
  - `payload` = `{title, start_utc, end_utc, all_day, status, location, description, attendees[], rrule, recurrence_id, calendar_href, etag}` (no VALARMs, no raw ICS needed post-parse — keep the raw ICS only if write-back is ever planned)
  - `content_hash` = SHA-256 over the canonical projection described in §3
  - `observed_at` = now (UTC)

### Applying records to the calendar domain

The connector never touches domain tables. The scheduled task hands `SyncResult.records` to new `CalendarService` methods (service → repository → DB, per the boundary):

- `upsert_external_event(household_id, record: ExternalRecord) -> EventView`: identity on `(household_id, metadata_["external_id"])`; skip when `content_hash` is unchanged; else upsert with `source_id` pointing at the household's `Source` row (`type="icloud_calendar"`) and `metadata_` carrying `{connector, external_id, calendar_href}` — `Event.metadata_` (JSONB) and `Event.source_id` already exist for exactly this.
- `delete_external_event(household_id, external_id)`: only deletes events whose `metadata_["connector"] == "icloud_calendar"` — nidaro-native events are untouchable.
- The assistant needs **no changes**: `build_calendar_tools`' existing `get_upcoming_events` tool reads through `CalendarService.get_upcoming_events` and sees synced events immediately. The LLM reasons over whatever the deterministic pipeline stored.

### Scheduling

Replace the placeholder body of `connector_sync` in `jobs/tasks.py` with a real task registered per household, scheduled via a label cron (e.g. `*/15 * * * *` plus per-household jitter) on the existing `TaskiqScheduler`/`LabelScheduleSource` setup; record each run in `JobRun` via `JobService` as today. **State it plainly in docs and code comments: this is polling. There is no push channel for iCloud calendars — no webhooks, no subscriptions — so a 10–15 minute worst-case staleness is inherent to the design.** Write-back, if ever built, is a separate `CalendarWriteService` behind the service boundary, gated per household, writing only to a nidaro-owned calendar.

### Gaps this design exposes (small, expected)

1. **Cursor/state persistence** — no table stores per-(household, connector) cursors or connector credentials; needs a small `connector_state` table + repository in the connectors package.
2. **Credential encryption** — no encryption-at-rest helper exists yet; needed before the first real app-specific password is stored.
3. **Deletion semantics** — `ExternalRecord`/`SyncResult` have no explicit delete concept; resolve tombstone representation (payload flag vs. `external_type`) before implementation.
4. **Config intake** — nothing today collects "which member's iCloud account" per household; the connector config shape (member reference, encrypted ASP, calendar allow-list) must be defined with the household domain.

## Open questions / risks

- **Unofficial surface.** iCloud CalDAV is undocumented and changeable without notice ([issue #3](https://github.com/python-caldav/caldav/issues/3)). Mitigation: the connector is one file; the `ExternalRecord` contract insulates the domain.
- **Recurrence via iCloud CalDAV** has history of flakiness in library tests (the `no_recurring` flag in the old iCloud profile; RRULE-bearing events do sync in practice, but exception handling needs a live-account test). Verify with a real account: masters, single-instance edits (`RECURRENCE-ID`), and `this-and-future` edits before trusting the expansion code.
- **Sync-token invalidation frequency** on iCloud is unknown; the full-list fallback path must be load-tested (RFC-sanctioned behavior: [RFC 6578](https://datatracker.ietf.org/doc/html/rfc6578#section-3.2); observed on iCloud: [issue #122](https://github.com/python-caldav/caldav/issues/122)).
- **Undocumented rate limits.** No official numbers; keep cadence ≥ 10 minutes, short-circuit no-change polls, back off on errors, and never poll per-request in assistant tools — the assistant reads PostgreSQL, not iCloud.
- **Invite reply path unverified.** Reading ATTENDEE fields is fine; acting on invitations (RFC 6638) on iCloud is undocumented and out of scope for v1.
- **Password-change cliff.** Any primary Apple Account password change silently revokes all app-specific passwords ([Apple support 102654](https://support.apple.com/en-us/102654)) — households will hit this; the reconnect UX is not optional.
- **2FA is a hard prerequisite** per member's Apple Account; members without 2FA cannot mint app-specific passwords at all.
- **Key management** for credential encryption at rest is an open infra decision (no KMS in the stack; a concrete requirement would need to justify adding one per AGENTS.md).

## Source list

Apple primary sources:

- App-specific passwords — https://support.apple.com/en-us/102654 (published 2025-10-08)
- Authorize third-party apps with Apple Account (Mail/Calendar/Contacts) — https://support.apple.com/en-us/121539 (published 2025-10-07)
- iCloud Mail server settings incl. Outlook authorization note — https://support.apple.com/en-us/102525 (published 2026-02-03)
- Share a calendar on iCloud.com (public calendar link) — https://support.apple.com/guide/icloud/share-a-calendar-mm6b1a9479/icloud
- What you can do with iCloud and Calendar — https://support.apple.com/guide/icloud/what-you-can-do-with-icloud-and-calendar-mm15eb200ab4/icloud
- EventKit framework (Apple platforms only) — https://developer.apple.com/documentation/eventkit
- Apple Developer News (no calendar API announcements) — https://developer.apple.com/news/

RFCs:

- RFC 4791 (CalDAV): PUT/If-Match §5.3.2, MKCALENDAR §5.3.1, calendar-home-set §6.2.1, calendar-multiget §7.9, CALDAV:expand §9.6.5 — https://www.rfc-editor.org/rfc/rfc4791
- RFC 5545 (iCalendar): VTIMEZONE §3.6.5, RECURRENCE-ID §3.8.4.4, UID §3.8.4.7, RRULE §3.8.5.3 — https://www.rfc-editor.org/rfc/rfc5545
- RFC 6578 (WebDAV sync): sync-collection REPORT §3.2, valid-sync-token precondition, truncation §3.6 — https://www.rfc-editor.org/rfc/rfc6578
- RFC 6638 (CalDAV scheduling) — https://datatracker.ietf.org/doc/html/rfc6638

Libraries and code:

- python-caldav docs (compatibility, URLs, licenses, RFC 6638 status) — https://caldav.readthedocs.io/latest/about.html
- python-caldav HTTP library docs (niquests/requests/httpx, async caveats) — https://caldav.readthedocs.io/latest/http-libraries.html
- python-caldav iCloud quirks issue — https://github.com/python-caldav/caldav/issues/3
- python-caldav sync-token drop issue — https://github.com/python-caldav/caldav/issues/122
- python-caldav iCloud IPv6 issue — https://github.com/python-caldav/caldav/issues/393
- python-caldav compatibility hints source (iCloud profile commented out) — https://github.com/python-caldav/caldav/blob/master/caldav/compatibility_hints.py
- Thunderbird OAuth2 provider registry (no Apple issuer) — https://github.com/mozilla/releases-comm-central/blob/master/mailnews/base/src/OAuth2Providers.sys.mjs
- Home Assistant caldav coordinator (executor pattern, 15-min interval) — https://github.com/home-assistant/core/blob/dev/homeassistant/components/caldav/coordinator.py
- Aurinko: iCloud CalDAV wire captures (sync-collection, getctag, sync-token) — https://www.aurinko.io/blog/caldav-apple-calendar-integration/
- Nylas Apple Calendar cookbook (no official API) — https://developer.nylas.com/docs/cookbook/calendar/apple-calendar-api/
- GAS-ICS-Sync issue #261 (public-calendar URL regeneration) — https://github.com/derekantrican/GAS-ICS-Sync/issues/261
- Evolution timezone-prefix issue — https://gitlab.gnome.org/GNOME/evolution/-/work_items/3332

Package status (PyPI, checked 2026-02):

- caldav 3.2.1 (2026-05) — https://pypi.org/project/caldav/
- icalendar 7.3.0 (2026-08) — https://pypi.org/project/icalendar/
- recurring-ical-events 3.8.2 (2026-04) — https://pypi.org/project/recurring-ical-events/
- vobject 0.9.9 (2024-12) — https://pypi.org/project/vobject/
- python-dateutil 2.9.0.post0 — https://pypi.org/project/python-dateutil/
- icalendar usage docs (zoneinfo default, timezones, VALARM) — https://icalendar.readthedocs.io/en/latest/how-to/usage.html
