# Google Calendar integration for nidaro — research findings

Researched 2026-08 against Google's primary documentation (developers.google.com, support.google.com). Facts are current as of the "Last updated" dates on the cited pages. Written for an engineer who knows nidaro but not the Calendar API.

## Verdict

Build a `GoogleCalendarConnector` implementing nidaro's `Connector` protocol, backed by OAuth 2.0 per family member (web-server or installed-app flow — one consent per person, refresh tokens stored encrypted in PostgreSQL), never a service account: service accounts cannot reach personal `@gmail.com` calendars without Workspace domain-wide delegation. Sync each consented calendar with `events.list` using `syncToken` as the connector cursor (full sync on `410 GONE`), producing one `ExternalRecord` per event, applied to the `events` table through `CalendarService` — not by the connector. Skip watch channels for now: they require a public HTTPS endpoint with a valid certificate, which a self-hosted nidaro typically lacks; a 5-minute Taskiq poll of the incremental endpoint uses ~4 requests per 5 minutes for a 4-person household, roughly four orders of magnitude under the per-user quota. Do writes (create/update/delete) through a small Google write service called by `CalendarService` at the service boundary, using client-generated event IDs and `extendedProperties.private` markers so the sync loop can recognize nidaro's own writes. Call Google directly over `httpx` (already a dependency) with `google-auth` for token handling; `google-api-python-client` is blocking on top of non-thread-safe `httplib2` and adds nothing for the six endpoints this integration needs.

## 1. OAuth 2.0

### Why not a service account

A service account "belongs to your application instead of to an individual end user", and to access user data it must be granted domain-wide delegation by a **Google Workspace super administrator** ([service-account doc](https://developers.google.com/identity/protocols/oauth2/service-account)). Personal `@gmail.com` accounts are not part of a Workspace domain, so there is no admin to grant delegation and no way for a service account to read a personal calendar. The events reference states the same limitation from the write side: "Service accounts need to use domain-wide delegation of authority to populate the attendee list" ([events: insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert)). Conclusion for nidaro: three-legged OAuth, one consent per family member.

### Flow choice: web-server vs installed-app loopback

Both are authorization-code flows against `https://accounts.google.com/o/oauth2/v2/auth` with token exchange at `https://oauth2.googleapis.com/token`:

- **Web application client** ([web-server flow](https://developers.google.com/identity/protocols/oauth2/web-server)): requires a client secret, redirect URI must exactly match a registered URI; `http://localhost:8080`-style URIs are explicitly allowed for testing. Send `access_type=offline` to get a refresh token "so that your app can refresh the access token without user interaction". This is the natural fit for nidaro, which is a FastAPI web app with a `web/` layer — the household admin clicks "connect Google Calendar", nidaro redirects, and the callback route exchanges the code server-side.
- **Desktop/installed client with loopback redirect** ([native-app flow](https://developers.google.com/identity/protocols/oauth2/native-app)): PKCE (`code_challenge`/`code_verifier`, S256), `client_secret` optional, `redirect_uri` of the form `http://127.0.0.1:port` with a temporary local listener (loopback is deprecated for mobile but recommended for desktop). Refresh tokens are "always returned for installed applications". Relevant only if you add a CLI-based connect flow; the web flow covers the actual product.

Detail that bites in both flows: the Node.js sample in the web-server doc notes "The `refresh_token` is only returned on the first authorization". Pass `prompt=consent` on re-auth to force a new refresh token, and treat a token response without `refresh_token` as "we already hold it".

### Refresh-token lifetime and revocation

The [OAuth 2.0 overview](https://developers.google.com/identity/protocols/oauth2#expiration) lists the cases where a refresh token stops working; code must anticipate all of them:

- user revokes access (myaccount.google.com/permissions or programmatic revoke at `https://oauth2.googleapis.com/revoke`);
- refresh token unused for **six months** (not a risk for a poller);
- user changed password and the token has Gmail scopes (not ours);
- the account exceeded its live-token budget: there is a **limit of 100 refresh tokens per Google account per OAuth client ID**, and creating a new one silently invalidates the oldest; plus a larger account-wide limit across all clients;
- time-based access expired;
- **testing mode**: "A Google Cloud Platform project with an OAuth consent screen configured for an external user type and a publishing status of 'Testing' is issued a refresh token expiring in **7 days**" (unless only userinfo scopes are requested — Calendar scopes don't qualify).

Failure mode on any of these is `invalid_grant` on refresh; the only recovery is sending the user through consent again ([web-server doc, `invalid_grant`](https://developers.google.com/identity/protocols/oauth2/web-server)).

### Publishing status for a hobby app

Calendar scopes are **sensitive scopes** — Google's own [sensitive-scope verification page](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification) uses `https://www.googleapis.com/auth/calendar` as its example. Consequences:

- **Testing status**: no verification required, but every refresh token expires after 7 days (above). For nidaro this means every family member re-consents weekly. Unusable for a always-on sync.
- **Published to production without verification** (the pragmatic hobby path): users see an "unverified app" screen before consent, and the app is **limited to 100 new users until it is verified** ([Unverified apps](https://support.google.com/cloud/answer/7454865)); the FAQ adds that exhausting the 100-user cap disables sign-in ([FAQ](https://support.google.com/cloud/answer/13463817)). For a household (2–6 users) the cap is irrelevant. Refresh tokens no longer carry the 7-day expiry once the project is out of Testing status.
- Full verification is possible later if nidaro is ever distributed; it requires a privacy policy, scope justification, and possibly a security assessment for restricted scopes — out of scope for this slice.

**Recommendation**: configure the consent screen as External, add family members as test users during development, then switch publishing status to In production (unverified) before real use. Document in the README that each user must click through the unverified-app screen.

### Scopes

Full list in the [Calendar auth doc](https://developers.google.com/workspace/calendar/api/auth). The relevant pair:

| Scope | Meaning | Use |
| --- | --- | --- |
| `.../auth/calendar.events` | View and edit events on **all your calendars** | read + write, including calendars shared with the user but owned by someone else (e.g. a partner shares their calendar with the household) |
| `.../auth/calendar.events.owned` | See, create, change, delete events on calendars **you own** | narrower; misses calendars merely shared to the user |
| `.../auth/calendar.events.readonly` / `calendar.readonly` | read-only variants | read-only households |

`events.list` authorizes with any of the read scopes ([events: list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)); `events.insert` needs `calendar`, `calendar.events`, `calendar.app.created`, or `calendar.events.owned` ([events: insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert)). Request `calendar.events` once per user: it covers sync and write, avoids incremental-authorization complexity, and granular consent lets users see exactly what they grant. Verify granted scopes from the response `scope` field and degrade to read-only if the write scope was denied (granular permissions may grant a subset — [native-app doc, step 6](https://developers.google.com/identity/protocols/oauth2/native-app)).

### Per-user tokens for a family

Each family member consents individually; the resulting refresh token authorizes access to that person's calendars (whatever they own or were granted access to). One token row per (household, person) is the whole story — the API has no household concept.

## 2. Sync mechanisms

The [sync guide](https://developers.google.com/workspace/calendar/api/guides/sync) defines a two-stage protocol that maps one-to-one onto nidaro's cursor contract:

1. **Full sync**: `GET /calendars/{calendarId}/events` (optionally with `timeMin` to bound history — the guide's sample syncs one year back). The response's `nextSyncToken` appears **only on the last page**; persist it.
2. **Incremental sync**: repeat the same request with `syncToken=<stored token>`. The result contains only changes, **always including deletions** (`showDeleted=false` is rejected with a syncToken), plus a fresh `nextSyncToken` on the last page.

Hard rules from [events: list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list):

- With `syncToken` you may **not** pass `iCalUID`, `orderBy`, `privateExtendedProperty`, `q`, `sharedExtendedProperty`, `timeMin`, `timeMax`, or `updatedMin`. All other parameters (e.g. `singleEvents`, `maxResults`, `eventTypes`) must match the initial full sync "to avoid undefined behavior".
- Large change sets paginate: you get `nextPageToken` and must re-send the same `syncToken` plus the `pageToken` until a page carries `nextSyncToken`. `maxResults` defaults to 250, max 2500.
- If the token is expired or invalidated the server returns **410 GONE**; the guide's instruction is to clear client state and full-sync again. In nidaro terms: catch 410, discard the cursor, re-run with `cursor=None`.

Pitfalls:

- `updatedMin`-based ("legacy") sync is explicitly discouraged: "no longer recommended because it is more error-prone" ([sync guide](https://developers.google.com/workspace/calendar/api/guides/sync)). Use syncTokens.
- Deletions arrive as events with `status: "cancelled"`. Per the [Events resource](https://developers.google.com/workspace/calendar/api/v3/reference/events#resource) a cancelled event is one of two things: (a) a **cancelled exception** of a recurring series (keep it locally for the life of the parent; only `id`, `recurringEventId`, `originalStartTime` are guaranteed populated) or (b) a **true deletion** (only `id` is guaranteed; remove your copy). The applier must branch on `recurringEventId`.
- `singleEvents=true` expands recurring events into instances server-side; `orderBy=startTime` requires it. Expansion is tempting (nidaro's `Event` model is flat) but churns rows: every edit to a series re-emits many instances, and unbounded RRULEs are expanded far into the future. With `singleEvents=false` you sync the series master (`recurrence[]` holds RRULE/RDATE/EXRULE/EXDATE lines per RFC 5545, with DTSTART/DTEND disallowed — start/end live in `start`/`end`) plus cancelled/moved exceptions, and expand deterministically in nidaro at read time. Timezone correctness is delegated to Google either way only with `singleEvents=true`; local expansion must handle `start.timeZone` (IANA name, required for recurring expansion per the resource doc) and floating/all-day events (`start.date`, no time).

## 3. Push notifications (watch channels)

Mechanics from the [push guide](https://developers.google.com/workspace/calendar/api/guides/push):

- Register by `POST /calendar/v3/calendars/{id}/events/watch` with `id` (unique per project, ≤64 chars), `type: "web_hook"`, `address` (must be **HTTPS with a valid, non-self-signed certificate**), optional `token` (≤256 chars, echoed back for spoofing checks) and `expiration`. The response adds a `resourceId` needed later for `channels.stop`.
- The first notification is a `sync` message (`X-Goog-Resource-State: sync`); real changes arrive as `X-Goog-Resource-State: exists`.
- **The notification body is empty.** "These messages don't contain specific information about updated resources; you must make another API call to see full change details" — a channel is a hint to re-run an incremental sync, not a data feed.
- **No auto-renewal**: "there's no automatic way to renew a notification channel... you must replace it with a new one by calling the watch method" before expiration; overlapping channels are expected. Google may cap your requested expiration at an internal limit — store the `expiration` the server returns, not the one you asked for.

Practical verdict for self-hosted nidaro: the deployment model (Quadlet pod, API published on `0.0.0.0:8100` on the LAN, per `docs/deployment.md`) has no public HTTPS endpoint, and the API rejects everything else. Treat webhooks as an optional add-on for instances that sit behind a public domain, and make **scheduled polling the baseline** (§7). Polling cost is negligible: one incremental `events.list` per account per tick; the quota guide itself lists push notifications as a quota optimization for large user counts, not small ones ([quota guide](https://developers.google.com/workspace/calendar/api/guides/quota)).

## 4. Rate limits, quota, backoff

From the [quota guide](https://developers.google.com/workspace/calendar/api/guides/quota):

| Limit | Value |
| --- | --- |
| Per minute per project | 10,000 requests |
| Per minute per user per project | 600 requests |
| Per day per project (billing threshold) | 1,000,000 requests — free below, charges planned "later in 2026" |

- Quotas are computed over a sliding minute; bursts get throttled in the following window. Exceeding them yields `403` or `429` `usageLimits`.
- Backoff: `min((2^n) + random(0..1000ms), maximum_backoff)`, `maximum_backoff` typically 32–64 s, retry a bounded number of times.
- Batching does **not** save quota: "A set of n requests batched together counts toward your usage limit as n requests" ([batch guide](https://developers.google.com/workspace/calendar/api/guides/batch), which also caps a batch at 1000 calls). Batching saves connections only.
- `events.patch` consumes **three** quota units; the docs recommend get-then-update instead ([Events: patch note](https://developers.google.com/workspace/calendar/api/v3/reference/events#methods)).
- Traffic shaping: vary periodic job intervals ±25% and avoid midnight full syncs — directly applicable to the Taskiq cron.

Quota math for nidaro: 4 members × 1 incremental request per 5-minute poll ≈ 0.8 requests/min/user against a 600/min/user limit. Even a daily full re-sync (a few pages at `maxResults=2500`) is noise. Quota will never be the constraint at household scale; token revocation and 410 resyncs are the operational events to handle.

## 5. Python client reality

- `google-api-python-client` is **synchronous and built on `httplib2`**, whose `Http()` objects "are not thread-safe" — each thread needs its own instance ([thread-safety doc](https://googleapis.github.io/google-api-python-client/docs/thread_safety.html)). There is no async API; full async support remains a long-open feature request ([issue #1637](https://github.com/googleapis/google-api-python-client/issues/1637)). Under asyncio your options are `asyncio.to_thread(...)` per call (sync, extra dependency tree: httplib2, uritemplate, google-auth-httplib2, google-auth-oauthlib) or bypassing the library.
- Well-maintained async alternatives don't really exist as of 2025. `google-auth` (the credential library, which is worth keeping) has an aiohttp-based transport, but its own source marks it "experimental and marked internal... may change in minor releases" ([google/auth/transport/_aiohttp_requests.py](https://github.com/googleapis/google-auth-library-python/blob/main/google/auth/transport/_aiohttp_requests.py)). Everything else on PyPI is thin or dormant.
- **Recommendation**: call the documented JSON endpoints directly with `httpx.AsyncClient` (already in nidaro's dependencies) and use `google-auth` only as a token container — or skip it too, because the token protocol is two plain POSTs:
  - exchange: `POST https://oauth2.googleapis.com/token` with `code`, `client_id`, `client_secret`, `redirect_uri`, `grant_type=authorization_code` ([web-server doc, step 5](https://developers.google.com/identity/protocols/oauth2/web-server));
  - refresh: same endpoint, `grant_type=refresh_token` with the stored refresh token; returns a new `access_token` with `expires_in` (seconds) — the installed-app doc shows the exact response shape ([native-app doc](https://developers.google.com/identity/protocols/oauth2/native-app)).
- The REST surface this integration needs is small and fully documented: `events.list`, `events.insert`, `events.update`, `events.delete`, `events.watch`, `channels.stop`. Discovery-document magic buys nothing here, and direct REST keeps the async boundary honest (no blocked event loop) and the dependency list clean.

## 6. Two-way write

All from [events: insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert) and the [Events resource](https://developers.google.com/workspace/calendar/api/v3/reference/events#resource) unless noted:

- **Create**: `POST /calendars/{calendarId}/events` with `start`/`end` (`dateTime` RFC3339 with offset, or `date` for all-day; `timeZone` as IANA name), `summary`, `description` (may contain HTML), `location`, `attendees[]` (RFC5322 `email` required per attendee). Query params: `sendUpdates` = `all` | `externalOnly` | `none` (default: no notifications; the old `sendNotifications` is deprecated), `conferenceDataVersion=1` to create a Meet link via `conferenceData.createRequest` — the request's `requestId` makes conference creation idempotent ("If an ID provided is the same as for the previous request, the request is ignored").
- **Client-supplied event IDs are allowed and recommended**: base32hex alphabet (`a–v`, `0–9`), 5–1024 chars, unique per calendar, "we recommend using an established UUID algorithm such as one described in RFC4122". `nidaro` is valid base32hex, so `nidaro<uuid4 hex>` works — this makes nidaro→Google creates idempotent and self-identifying. (`iCalUID` is a different field; all instances of one series share an `iCalUID` but have distinct `id`s.)
- **Update**: `PUT /calendars/{calendarId}/events/{eventId}` replaces the entire resource (no patch semantics); "To do a partial update, perform a `get` followed by an `update` **using etags to ensure atomicity**". Every event carries an `etag`, and `If-Match` is the conditional-write mechanism (the batch guide shows `If-Match: "etag/sheep"` in a batched PUT). For nidaro: on write, GET the event, apply field changes, PUT with `If-Match` of the stored etag; a `412` means someone (a family member, in the Google UI) changed it mid-flight — surface a conflict instead of silently clobbering.
- **Delete**: `DELETE .../events/{eventId}`; the subsequent incremental sync returns it as `status: "cancelled"`.
- **Mirror-loop risk**: an event nidaro wrote will come back on the next incremental sync. Stamp written events with `extendedProperties.private` (e.g. `{"nidaro": "1", "nidaroEventId": "<uuid>"}`) and carry the Google `id` + `etag` in `Event.metadata_`. The applier (§7) then distinguishes three cases: event nidaro has never seen (insert), event whose stored etag differs and whose `extendedProperties` marker is absent (external edit → update domain row), marker present (own write echo → update bookkeeping only, no user-visible change). This is the same last-write-wins-with-etag-check discipline the API docs prescribe.
- Attendee responses (`responseStatus`) and organizer-only fields flow through sync; `eventType`s like `fromGmail` exist in reads but "cannot be created" — sync payload keeps the raw event so the applier can be lossy at the domain boundary without losing data.

## 7. Plugin design for nidaro

Everything below is contract-level, using the repo's actual types. Boundary rule holds: connector/tool/worker → service → repository → database; the connector never touches the `events` table.

### Layout

```
src/nidaro/connectors/google_calendar/
    __init__.py
    connector.py      # GoogleCalendarConnector (implements Connector)
    client.py         # Async GoogleCalendarClient (httpx) — list/insert/update/delete/watch
    tokens.py         # token refresh + encryption helpers
    mapping.py        # event JSON -> ExternalRecord payload, content_hash
```

### Credential + cursor storage (new repository/service, PostgreSQL)

One table, e.g. `google_calendar_accounts`: `household_id` (FK), `google_email` (unique per household), `encrypted_refresh_token` (Fernet/AES-GCM with a key from `NIDARO_SECRET_KEY` env — no secrets in source, per AGENTS.md), `granted_scopes`, `sync_token` (the connector cursor), `etag_cache` implied by records, optional `watch_channel_id` / `watch_resource_id` / `watch_expiration`. Expose it through an application service (e.g. `GoogleCalendarAccountService`) so routes/tools/workers never touch the repository directly. The `syncToken` **is** the `cursor` string of the `Connector` protocol — no separate cursor format needed beyond per-account multiplexing (below).

### The connector

```python
class GoogleCalendarConnector:
    name = "google_calendar"

    async def sync(self, context: ConnectorContext, cursor: str | None) -> SyncResult:
        accounts = await self.accounts.for_household(context.household_id)
        # cursor = JSON {"<google_email>": {"calendar_id": ..., "sync_token": ...}, ...}
        # None => full sync for every account (first run or after 410)
        records: list[ExternalRecord] = []
        for account in accounts:
            for page in await self.client.incremental_or_full(account, cursor, context.timezone):
                records.extend(to_external_records(account, page.items))
                new_cursor[account.email] = page.next_sync_token
            on HttpError 410: restart this account's full sync (drop its cursor entry,
                              optionally bound with timeMin, re-collect records)
        return SyncResult(records=records, next_cursor=json.dumps(new_cursor))
```

- One `ExternalRecord` per event: `connector="google_calendar"`, `external_type="event"`, `external_id=f"{google_email}/{calendar_id}/{event.id}"` (Google event `id` is only unique per calendar), `payload` = the raw event JSON (id, status, summary, description, location, start, end, recurrence, recurringEventId, originalStartTime, attendees, extendedProperties, eventType, htmlLink, iCalUID, etag, updated), `observed_at` = fetch time.
- `content_hash` = SHA-256 over a canonical JSON of the semantically relevant fields (summary, description, location, status, start, end, recurrence, attendee emails, extendedProperties) — *not* `updated`/`etag` alone, since reminders-only changes bump `updated` without touching event content, and `etag` changes on fields nidaro ignores.
- Pagination: loop `pageToken` inside `sync` until `nextSyncToken` (§2); the protocol's `SyncResult` only needs the final cursor.
- Deleted events stay in the stream (`status: "cancelled"`); the applier interprets them.

### Applying records: service, not connector

New method on `CalendarService` (or a sibling `ExternalEventApplier` service called by `CalendarService`), because only a service may write domain tables:

```python
class CalendarService:
    async def apply_external_records(self, household_id: UUID,
                                     records: list[ExternalRecord]) -> int:
        # upsert into `events` keyed by Event.metadata_["google"]["id"]
        #   + metadata_["google"]["email"]
        # cancelled + recurringEventId absent  -> mark row status="cancelled" (or delete)
        # cancelled + recurringEventId present -> cancelled exception of a series
        # recurring master (recurrence[])      -> store master; expansion is a read-time concern
        # rows carry metadata_["google"]["etag"] for the two-way conflict check
```

`Event.metadata_` (JSONB, already on the model) holds the Google bookkeeping: `{"google": {"email": ..., "calendar_id": ..., "id": ..., "etag": ..., "html_link": ...}}`. Optionally register each account as a `Source` via the existing `SourceService` and set `Event.source_id`, so provenance is queryable without JSONB gymnastics.

### Triggering sync

The placeholder in `src/nidaro/jobs/tasks.py` becomes real:

```python
@broker.task(schedule=[{"cron": "*/5 * * * *"}])
async def connector_sync(connector_name: str): ...
# body: for each household with accounts -> services.connectors.sync(name, context, stored_cursor)
#       -> calendar.apply_external_records(...) -> persist next_cursor
```

`ConnectorService.sync(name, context, cursor)` already exists and dispatches through `ConnectorRegistry` — the worker is a thin loop around it plus cursor persistence. Add jitter (±25%, per the quota guide) inside the task rather than the cron. The webhook path, when an instance has a public HTTPS endpoint: a `POST /webhooks/google-calendar` route validates `X-Goog-Channel-Token`, then enqueues the same `connector_sync` task via the broker — the notification carries no data, so both paths converge on identical code. A small renewal job re-`watch`es before each stored `watch_expiration`.

### Write path

`CalendarService.create_event(CreateEventRequest)` keeps its signature (the assistant tool in `assistant/tools/calendar.py` is untouched). Internally it branches:

- request carries no external target → current repository path;
- request (or the tool, via a new optional `CreateEventRequest.google_calendar: bool = False`) targets Google → `CalendarService` calls a `GoogleCalendarWriteService` (application service, injected into `ApplicationServices`): builds the event JSON (`sendUpdates="all"` when attendees exist, `extendedProperties.private={"nidaro": "1"}`, client-supplied `id="nidaro"+uuid4().hex`), POSTs it, then writes the domain `Event` with `metadata_.google` filled from the response — a single transaction per repository call, with the Google call made *before* the local insert (Google is not transactional; on failure raise and let the tool report it).

Edits/deletes of Google-origin events go through the same write service with etag-checked GET→PUT; deletes of nidaro-origin events call `events.delete`. The next incremental sync observes the echoes and updates bookkeeping without user-visible changes (§6).

## Open questions / risks

1. **Testing-mode token expiry is the deployment blocker.** In Testing status all refresh tokens die in 7 days ([oauth2#expiration](https://developers.google.com/identity/protocols/oauth2#expiration)). Decide early: publish unverified (unverified-app screen + 100-user cap, tolerable for a household) or schedule weekly re-consent during development only.
2. **Scope granularity vs family reality.** `calendar.events.owned` is least-privilege but misses calendars *shared with* a member (partner's calendar). `calendar.events` covers the household use case at the cost of broader consent. Users can grant a subset (granular consent) — the code must handle read-without-write grants.
3. **Recurring events.** Server-side expansion (`singleEvents=true`) is simplest but churns `ExternalRecord` volume and hides recurrence semantics from the assistant; masters + deterministic local expansion needs an RFC 5545 engine (e.g. `python-dateutil` + hand-rolled EXDATE/RDATE handling) and careful timezone handling for `start.timeZone`. Recommend masters in v1.5, expansion at read time; v1 can ship `singleEvents=true` bounded to a window.
4. **All-day events** have `start.date` and no timezone; nidaro's `Event.starts_at` is `timestamptz`. Needs a convention (midnight in `ConnectorContext.timezone` + a flag in `metadata_`).
5. **Watch channels** require valid public HTTPS; without it, latency is bounded by the poll interval. Channels also cap expiration server-side at undocumented internal limits — store what the server returns.
6. **Quota billing change**: exceeding 1M requests/day/project "is planned to incur charges... later in 2026" ([quota guide](https://developers.google.com/workspace/calendar/api/guides/quota)) — irrelevant at household scale, but worth a line in the docs.
7. **Conflict UX**: a `412` from an etag-checked PUT means a human edited the event in Google mid-flight. Decide: fail the tool call and tell the assistant, or auto-rebase. v1: fail loudly.
8. **Access-role limits**: calendars where the member is `freeBusyReader`/`reader` expose less or no event detail ([events: list response](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)) — sync what's visible, mark the access role in payload.

## Sources

- Calendar API sync guide (syncToken, 410, legacy updatedMin): https://developers.google.com/workspace/calendar/api/guides/sync
- Calendar API push notifications (channels, HTTPS requirement, empty body, renewal): https://developers.google.com/workspace/calendar/api/guides/push
- Calendar API usage limits & backoff (10k/600 per minute, 1M/day, backoff formula): https://developers.google.com/workspace/calendar/api/guides/quota
- Calendar API batch (n requests count as n, 1000-call cap): https://developers.google.com/workspace/calendar/api/guides/batch
- Calendar API scopes: https://developers.google.com/workspace/calendar/api/auth and https://developers.google.com/identity/protocols/oauth2/scopes
- Events: list (syncToken parameter restrictions, showDeleted, singleEvents, maxResults): https://developers.google.com/workspace/calendar/api/v3/reference/events/list
- Events: insert (sendUpdates, conferenceDataVersion, client IDs, attendee rules): https://developers.google.com/workspace/calendar/api/v3/reference/events/insert
- Events resource (etag, status=cancelled semantics, recurrence, iCalUID, update/patch notes): https://developers.google.com/workspace/calendar/api/v3/reference/events
- OAuth 2.0 overview (refresh-token expiration incl. 7-day testing rule, 100-token limit): https://developers.google.com/identity/protocols/oauth2#expiration
- OAuth 2.0 web-server flow (access_type=offline, refresh-once behavior, localhost redirect for testing): https://developers.google.com/identity/protocols/oauth2/web-server
- OAuth 2.0 installed-app flow (PKCE, loopback redirect, refresh tokens always returned): https://developers.google.com/identity/protocols/oauth2/native-app
- Service accounts & domain-wide delegation: https://developers.google.com/identity/protocols/oauth2/service-account
- Sensitive-scope verification (auth/calendar as the example sensitive scope): https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification
- Unverified apps (warning screen, 100-user cap): https://support.google.com/cloud/answer/7454865 and https://support.google.com/cloud/answer/13463817
- google-api-python-client thread safety (httplib2 not thread-safe): https://googleapis.github.io/google-api-python-client/docs/thread_safety.html
- google-api-python-client async feature request (open): https://github.com/googleapis/google-api-python-client/issues/1637
- google-auth experimental async transport: https://github.com/googleapis/google-auth-library-python/blob/main/google/auth/transport/_aiohttp_requests.py
- Python quickstart (canonical google-api-python-client usage): https://developers.google.com/workspace/calendar/api/quickstart/python
