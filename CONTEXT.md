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
