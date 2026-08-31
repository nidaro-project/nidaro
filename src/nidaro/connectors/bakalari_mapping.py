"""Deterministic mapping of Bakaláři mobile API v3 payloads to school inputs.

Pure functions only: no HTTP, no services, no clock beyond the household's
gather day. Payload shapes follow the community-documented v3 responses
(docs/research/bakalari.md); every quirk tolerated here (missing Change
objects, hour tables, absent weights) is covered by a fixture test.
"""

from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nidaro.school.schemas import GradeInput, HomeworkInput, LessonInput, SubjectInput

# Change/ChangeType names that mean the lesson does not happen (community-
# documented v3 payloads use English names, some servers Czech ones).
CANCELED_CHANGES = {"removed", "cancelled", "canceled", "zruseno", "zrušeno"}


def gather_day(timezone: str) -> date:
    """Today in the household's timezone, UTC when the zone is unknown."""
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        zone = None
    moment = datetime.now(zone) if zone else datetime.now(UTC)
    return moment.date()


def module_enabled(user: dict[str, Any], name: str) -> bool:
    """EnabledModules discovery: a module counts as enabled when `/api/3/user`
    lists it with a truthy value; a school withholding a module omits it."""
    return bool((user.get("EnabledModules") or {}).get(name))


def _as_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _as_time(value: Any) -> time | None:
    if not value:
        return None
    parts = str(value).split(":")
    try:
        return time(int(parts[0]), int(parts[1]))
    except (IndexError, ValueError):
        return None


def _name(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    return entry.get("Name") or entry.get("Abbrev") or None


def _cancel_state(change: dict[str, Any] | None) -> tuple[bool, str | None]:
    """(canceled, note) from a Change object; no change means a live lesson."""
    change_type = ""
    description = None
    if isinstance(change, dict):
        change_type = str((change.get("ChangeType") or {}).get("Name") or "").strip()
        description = change.get("Description")
    canceled = change_type.lower() in CANCELED_CHANGES
    note = description or (change_type if canceled else None)
    return canceled, note or None


def _subject_of(entry: dict[str, Any]) -> SubjectInput | None:
    subject = entry.get("Subject")
    if not isinstance(subject, dict):
        return None
    code = subject.get("Abbrev") or "?"
    return SubjectInput(
        code=code, name=subject.get("Name") or code, teacher=_name(entry.get("Teacher"))
    )


def _lesson_from_hour(
    hour: dict[str, Any], slots: dict[Any, Any], fallback_position: int
) -> LessonInput | None:
    """One timetable hour entry, or None when it cannot be materialized."""
    subject = _subject_of(hour)
    if subject is None:
        return None
    slot = slots.get(hour.get("HourId"), hour) or {}
    start = _as_time(slot.get("BeginTime"))
    end = _as_time(slot.get("EndTime"))
    if start is None or end is None:
        return None
    canceled, note = _cancel_state(hour.get("Change"))
    return LessonInput(
        subject=subject,
        start=start,
        end=end,
        position=int(hour.get("HourId", fallback_position)),
        teacher=subject.teacher,
        room=_name(hour.get("Room")),
        canceled=canceled,
        substitution=note,
    )


def lessons_from_timetable(payload: dict[str, Any], day: date) -> list[LessonInput]:
    """Materialized lessons for `day` from a `/api/3/timetable/actual` payload.

    Lessons without a subject or without a known timeslot are skipped; lesson
    times come from the payload's hour table (or the entry itself when it
    carries its own times).
    """
    slots = {slot.get("Id"): slot for slot in payload.get("Hours", []) if isinstance(slot, dict)}
    entry = next(
        (
            entry
            for entry in payload.get("Days", [])
            if isinstance(entry, dict) and str(entry.get("Date", "")).startswith(day.isoformat())
        ),
        None,
    )
    if entry is None:
        return []
    lessons: list[LessonInput] = []
    for hour in entry.get("Hours", []):
        lesson = _lesson_from_hour(hour, slots, len(lessons) + 1)
        if lesson is not None:
            lessons.append(lesson)
    return sorted(lessons, key=lambda lesson: lesson.position)


def _apply_substitution(lesson: LessonInput, entry: dict[str, Any]) -> None:
    """Overlay one substitution entry: cancel, note, replacement teacher."""
    change_type = str((entry.get("ChangeType") or {}).get("Name") or "").strip()
    if change_type.lower() in CANCELED_CHANGES:
        lesson.canceled = True
    note = entry.get("Description") or change_type or None
    if note:
        lesson.substitution = note
    teacher = _name(entry.get("Teacher"))
    if teacher:
        lesson.teacher = teacher


def apply_substitutions(
    lessons: list[LessonInput], entries: list[dict[str, Any]], day: date
) -> list[LessonInput]:
    """Overlay `/api/3/substitutions` entries for `day` onto the lessons.

    A matching entry (same day and hour) can cancel the lesson, replace the
    teacher, and carries the note parents see. Entries for other days and
    hours without a lesson are ignored.
    """
    merged = [lesson.model_copy() for lesson in lessons]
    by_position = {lesson.position: lesson for lesson in merged}
    for entry in entries:
        if not isinstance(entry, dict) or _as_date(entry.get("Date")) != day:
            continue
        position = entry.get("Hour")
        if position is not None and position in by_position:
            _apply_substitution(by_position[position], entry)
    return merged


def _grade_from_mark(mark: dict[str, Any], subject: SubjectInput) -> GradeInput | None:
    mark_id = mark.get("MarkId")
    graded_on = _as_date(mark.get("Date"))
    if not mark_id or graded_on is None:
        return None
    weight = mark.get("Weight")
    return GradeInput(
        external_id=str(mark_id),
        subject=subject,
        value=str(mark.get("MarkText") or ""),
        weight=round(float(weight)) if weight is not None else 1,
        graded_on=graded_on,
        teacher=mark.get("Teacher"),
        confirmed=bool(mark.get("IsConfirmed")),
    )


def grades_from_marks(payload: dict[str, Any]) -> list[GradeInput]:
    """Marks per subject from a `/api/3/marks` payload."""
    grades: list[GradeInput] = []
    for block in payload.get("Subjects", []):
        subject = _subject_of(block) or SubjectInput(code="?", name="?")
        for mark in block.get("Marks", []):
            grade = _grade_from_mark(mark, subject)
            if grade is not None:
                grades.append(grade)
    return grades


def _attachment_names(entry: dict[str, Any]) -> list[str]:
    return [
        attachment["Name"]
        for attachment in entry.get("Attachments") or []
        if isinstance(attachment, dict) and attachment.get("Name")
    ]


def _homework_from_entry(entry: dict[str, Any]) -> HomeworkInput | None:
    external_id = entry.get("Id")
    subject = _subject_of(entry)
    if not external_id or subject is None:
        return None
    return HomeworkInput(
        external_id=str(external_id),
        subject=subject,
        text=str(entry.get("Content") or ""),
        due_on=_as_date(entry.get("DateEnd")),
        attachments=_attachment_names(entry),
    )


def homework_from_payload(payload: dict[str, Any]) -> list[HomeworkInput]:
    """Assignments from a `/api/3/homeworks` payload."""
    homework: list[HomeworkInput] = []
    for entry in payload.get("Homeworks", []):
        item = _homework_from_entry(entry)
        if item is not None:
            homework.append(item)
    return homework
