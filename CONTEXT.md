# Nidaro

Nidaro is an open-source family operating assistant. This is the shared language for the whole repo; domain areas refine it here until a context split is needed.

## Language

**Activity**:
A thing the household needs to know about, shown on the family calendar — practices, lessons, appointments, special days. The user-facing word for an Event.
_Avoid_: meeting (implies a data distinction that does not exist)

**Event**:
The stored form of an activity; the only calendar entry type. Everything on the calendar is family-relevant — there is no work/personal-kind filter.
_Avoid_: calendar entry, appointment (as a type)

**Recurring activity**:
An activity that repeats every week on chosen days, with a fixed time window or no time at all.
_Avoid_: series (code speech), regular event

**Occurrence**:
One dated instance of a recurring activity, computed when the calendar is read; it has no stored row of its own.
_Avoid_: instance row, expanded event

**All-day activity**:
An activity that fills a day without a time.
_Avoid_: full-day event

**Household-wide activity**:
An activity with no named members; it belongs to the whole household.
_Avoid_: everyone event, family event (as a type)

**Household timezone**:
The timezone that defines a household's days — when its days, weeks, and occurrences begin and end.
_Avoid_: server time, UTC (that is only the fallback)

**Dish**:
A reusable meal idea the household eats typically, configured once with a name, notes, and tags. A Dish is not tied to any date.
_Avoid_: recipe, meal idea, template

**Planned meal**:
A Dish (or a one-off name) placed on a specific date and slot. A planned meal keeps the dish's name at planning time and is unaffected by later edits to or deletion of the Dish.
_Avoid_: meal entry, calendar event

**Slot**:
One of the fixed eating times a day is planned in: breakfast, lunch, dinner, snacks. A slot may hold more than one planned meal.
_Avoid_: mealtime, category

**School portal**:
The passive, read-only school section of Nidaro. It shows information gathered from school systems and never writes back or triggers a change there.
_Avoid_: school integration (implies interactivity that does not exist)

**Today at school**:
One kid's lessons for the day — the timetable with substitution applied. The first thing the school portal shows per kid.
_Avoid_: daily view, rozvrh (the Czech term for the raw timetable)

**What-to-pack overview**:
A derived view naming what a kid needs for today's and the next day's lessons, computed from the school portal's timetable. Not school data; computed and kept by Nidaro.
_Avoid_: packing list (derived per school day, not a stored list)

**Bakaláři**:
The Czech school information system; the primary source of the school portal.
_Avoid_: Baccalauréat (the French exam), Bacalaji

**Škola OnLine**:
A Czech school information system, second to Bakaláři. Observed for a future gatherer, not built.

**Bakaláři account**:
One parent login at a Bakaláři server, bound to one kid. A household may hold several — in this family, each kid has their own parent account on the same server.
_Avoid_: Bakaláři login (as the stored thing), child (the account is the linkage, not a child picked from a list)

**Gather**:
The school portal's read of a school system: log in, read what the school enables, land it, leave. Runs on a cadence and on demand from the school page; a failed gather changes nothing in Nidaro.
_Avoid_: sync (code speech), import, scrape

**Subject**:
A school course a kid is taught, named by the school with a short code and a long name. The anchor the what-to-pack mapping keys on.
_Avoid_: class (the kid's school class group, třída), course

**Lesson**:
One teaching slot a kid has on a date — subject, teacher, room, time window — with substitutions already applied. What the school portal shows for Today at school.
_Avoid_: timetable entry, period, hodina

**Grade**:
A mark a kid received for a subject, kept with its weight and confirmation state. The value may be a number or not.
_Avoid_: mark, známka (as code terms)

**Homework**:
A task a kid must do for a subject by a due date, gathered from the school system. Shown with attachment names only, never file bodies. Empty when the school does not enter homework.
_Avoid_: assignment

**Connector**:
A read-only gatherer for one external source (iCloud, a school system, WhatsApp). It pulls on a per-household schedule and produces external records; it never edits Nidaro's own tables and never writes back to the source.
_Avoid_: integration (implies two-way), plugin

**External record**:
The envelope one connector sync hands to a domain service: connector, type, stable external id, payload, content hash. The only shape external data may arrive in.
_Avoid_: raw event (the payload is just one field)

**Mirror**:
An Event kept in step with an external record by a domain service, identified by connector plus external id. Edited only by re-sync, removed when a tombstone arrives — the family edits their own events, not mirrors.
_Avoid_: synced event, copy

**Tombstone**:
The signal that a source deleted an item, or marked it cancelled; it removes the mirror instead of updating it. A cancelled external activity disappears from the calendar rather than showing struck-through.
_Avoid_: deletion flag, cancelled status (the source's word for its own state)

**App-specific password**:
A per-member, individually revocable password Apple requires before any iCloud access; the Apple ID must have two-factor authentication. Stored encrypted, referenced by name in the connector config; when it stops working the fix is reconnect, not data loss.
_Avoid_: Apple password (the account password — changing it revokes every app-specific password at once)

**iCloud calendars**:
The family's Apple calendars, read over CalDAV on a poll — Apple offers no push channel, so fresh means within one poll cycle. Nidaro reads only; write-back does not exist.
_Avoid_: calendar sync (which source?), push (none exists)
