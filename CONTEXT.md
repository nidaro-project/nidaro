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
