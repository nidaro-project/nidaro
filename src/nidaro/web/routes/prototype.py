"""PROTOTYPE — throwaway UI explorations. Delete before merge.

- [mealplan-1]: three variants of the meals week view on /prototype/week-view.
- [mealplan-2]: dish configuration variants on /prototype/dishes.
- [cal-3]: three variants of the family calendar page on /prototype/calendar.

All state lives in in-memory stubs; nothing touches the database or the real
domains.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Form, Query, Request
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/prototype", include_in_schema=False)
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent.parent / "web" / "templates")
)

SLOTS: tuple[str, ...] = ("breakfast", "lunch", "dinner", "snacks")
VARIANTS: dict[str, str] = {
    "grid": "A · Week grid",
    "day": "B · Day focus",
    "palette": "C · Dish palette",
}
DISH_VARIANTS: dict[str, str] = {
    "table": "A · Table rows",
    "cards": "B · Card grid",
    "detail": "C · Select and edit",
}


@dataclass
class Dish:
    id: str
    name: str
    tags: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Entry:
    id: str
    on: date
    slot: str
    name: str
    dish_id: str | None


DISHES: list[Dish] = [
    Dish(
        "d1",
        "Spaghetti Bolognese",
        ["quick", "favorite"],
        "Sunday sauce, double batch. Leo picks out the carrots.",
    ),
    Dish("d2", "Pancakes", ["weekend", "kids"], "Buttermilk only. Emma likes blueberries in hers."),
    Dish(
        "d3",
        "Chili con Carne",
        ["one-pot", "freezer"],
        "Mild for the kids, hot sauce on the side. Freezes well.",
    ),
    Dish("d4", "Sunday Roast Chicken", ["sunday"], "Leftovers become Monday's bowls."),
    Dish("d5", "Lentil Curry", ["veggie", "quick"], "Coconut milk version. Serve with rice."),
    Dish(
        "d6",
        "Sushi Night",
        ["special", "weekend"],
        "Everyone rolls their own. Needs a shopping run.",
    ),
]
ENTRIES: list[Entry] = []


def _seed() -> None:
    if ENTRIES:
        return
    today = date.today()

    def add(offset: int, slot: str, name: str, dish_id: str | None = None) -> None:
        ENTRIES.append(
            Entry(str(uuid.uuid4()), today + timedelta(days=offset), slot, name, dish_id)
        )

    add(-1, "dinner", "Lentil Curry", "d5")
    add(0, "dinner", "Spaghetti Bolognese", "d1")
    add(0, "snacks", "Ice cream (leftover)")
    add(1, "breakfast", "Pancakes", "d2")
    add(1, "dinner", "Chili con Carne", "d3")
    add(2, "dinner", "Chili con Carne", "d3")
    add(2, "dinner", "Pizza for the guests")
    add(5, "dinner", "Sushi Night", "d6")


def _window(w: int) -> list[date]:
    start = date.today() + timedelta(weeks=w)
    return [start + timedelta(days=i) for i in range(7)]


def _entries_for(day: date, slot: str) -> list[Entry]:
    return [e for e in ENTRIES if e.on == day and e.slot == slot]


def _dish_name(dish_id: str | None) -> str:
    return next((d.name for d in DISHES if d.id == dish_id), "?")


def _day_view(day: date) -> dict[str, Any]:
    return {
        "date": day,
        "iso": day.isoformat(),
        "weekday": day.strftime("%a"),
        "day_num": day.strftime("%-d"),
        "month": day.strftime("%b"),
        "is_today": day == date.today(),
        "entries": {slot: _entries_for(day, slot) for slot in SLOTS},
    }


def _context(variant: str, w: int, picked: str | None = None) -> dict[str, Any]:
    _seed()
    days = [_day_view(day) for day in _window(w)]
    start, end = days[0]["date"], days[-1]["date"]
    return {
        "variant": variant,
        "variant_label": VARIANTS[variant],
        "variant_keys": list(VARIANTS),
        "w": w,
        "picked": picked,
        "slots": SLOTS,
        "dishes": DISHES,
        "days": days,
        "range_label": f"{start.strftime('%b %-d')} - {end.strftime('%b %-d')}",
        "prev_w": w - 1,
        "next_w": w + 1,
    }


def _page_context(variant: str, w: int, picked: str | None = None) -> dict[str, Any]:
    from nidaro.web.routes.ui import _nav

    return {"nav": _nav("meals")} | _context(variant, w, picked)


@router.get("/week-view")
async def week_view(
    request: Request,
    variant: Annotated[str, Query(pattern="grid|day|palette")] = "grid",
    w: int = 0,
    picked: str | None = None,
):
    return templates.TemplateResponse(request, "pw.html", _page_context(variant, w, picked))


def _frag_template(variant: str) -> str:
    return {
        "grid": "pw_frag_grid_slot.html",
        "day": "pw_frag_day_day.html",
        "palette": "pw_frag_palette_day.html",
    }[variant]


def _frag_response(request: Request, variant: str, w: int, iso: str, slot: str, picked: str | None):
    day = _day_view(date.fromisoformat(iso))
    return templates.TemplateResponse(
        request,
        _frag_template(variant),
        _page_context(variant, w, picked) | {"day": day, "slot": slot},
    )


@router.post("/week-view/entries")
async def create_entry(
    request: Request,
    variant: Annotated[str, Form()],
    w: Annotated[int, Form()],
    on: Annotated[str, Form()],
    slot: Annotated[str, Form()],
    name: Annotated[str, Form()] = "",
    picked: Annotated[str | None, Form()] = None,
    dish_id: Annotated[str | None, Form()] = None,
):
    clean = name.strip() or (_dish_name(dish_id) if dish_id else "")
    if clean:
        ENTRIES.append(Entry(str(uuid.uuid4()), date.fromisoformat(on), slot, clean, dish_id))
    return _frag_response(request, variant, w, on, slot, picked)


@router.post("/week-view/entries/delete")
async def delete_entry(
    request: Request,
    variant: Annotated[str, Form()],
    w: Annotated[int, Form()],
    on: Annotated[str, Form()],
    slot: Annotated[str, Form()],
    entry_id: Annotated[str, Form()],
    picked: Annotated[str | None, Form()] = None,
):
    ENTRIES[:] = [e for e in ENTRIES if e.id != entry_id]
    return _frag_response(request, variant, w, on, slot, picked)


@router.post("/week-view/place")
async def place_dish(
    request: Request,
    variant: Annotated[str, Form()],
    w: Annotated[int, Form()],
    on: Annotated[str, Form()],
    slot: Annotated[str, Form()],
    picked: Annotated[str | None, Form()] = None,
):
    if picked:
        name = _dish_name(picked)
        if name != "?":
            ENTRIES.append(Entry(str(uuid.uuid4()), date.fromisoformat(on), slot, name, picked))
    return _frag_response(request, variant, w, on, slot, picked)


# ---- PROTOTYPE: dish configuration page ([mealplan-2]) ----


def _parse_tags(raw: str) -> list[str]:
    return [t.strip() for t in raw.replace(";", ",").split(",") if t.strip()]


def _dish_context(
    variant: str, edit: str | None = None, picked: str | None = None
) -> dict[str, Any]:
    from nidaro.web.routes.ui import _nav

    keys = list(DISH_VARIANTS)
    return {
        "nav": _nav("meals"),
        "variant": variant,
        "variant_label": DISH_VARIANTS[variant],
        "variant_keys": keys,
        "dishes": DISHES,
        "edit": edit,
        "picked": picked or (DISHES[0].id if DISHES else None),
    }


def _dish_frag_template(variant: str) -> str:
    return {"table": "pd_table.html", "cards": "pd_cards.html", "detail": "pd_detail.html"}[variant]


@router.get("/dishes")
async def dishes_page(
    request: Request,
    variant: Annotated[str, Query(pattern="table|cards|detail")] = "table",
    edit: str | None = None,
    picked: str | None = None,
):
    return templates.TemplateResponse(request, "pd.html", _dish_context(variant, edit, picked))


def _dish_frag(request: Request, variant: str, edit: str | None, picked: str | None):
    return templates.TemplateResponse(
        request, _dish_frag_template(variant), _dish_context(variant, edit, picked)
    )


@router.post("/dishes/save")
async def save_dish(
    request: Request,
    variant: Annotated[str, Form()],
    name: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
    dish_id: Annotated[str, Form()] = "",
    picked: Annotated[str | None, Form()] = None,
):
    clean = name.strip()
    if not clean:
        return _dish_frag(request, variant, None, picked)
    parsed = _parse_tags(tags)
    if dish_id:
        dish = next((d for d in DISHES if d.id == dish_id), None)
        if dish:
            dish.name, dish.notes, dish.tags = clean, notes.strip(), parsed
    else:
        dish = Dish(f"d{uuid.uuid4().hex[:6]}", clean, parsed, notes.strip())
        DISHES.append(dish)
        dish_id = dish.id
    return _dish_frag(request, variant, None, dish_id if variant == "detail" else picked)


@router.post("/dishes/delete")
async def delete_dish(
    request: Request,
    variant: Annotated[str, Form()],
    dish_id: Annotated[str, Form()],
    picked: Annotated[str | None, Form()] = None,
):
    DISHES[:] = [d for d in DISHES if d.id != dish_id]
    new_picked = picked if picked != dish_id else (DISHES[0].id if DISHES else None)
    return _dish_frag(request, variant, None, new_picked)


# ---- PROTOTYPE: family calendar page ([cal-3]) ----

CAL_VARIANTS: dict[str, str] = {
    "wall": "A · Wall calendar",
    "agenda": "B · Agenda list",
    "board": "C · Week board",
}
CAL_VIEWS: dict[str, str] = {"month": "Month", "week": "Week", "day": "Day"}


@dataclass(frozen=True)
class CalMember:
    key: str
    name: str
    avatar: int


CAL_MEMBERS: dict[str, CalMember] = {
    "emma": CalMember("emma", "Emma", 0),
    "leo": CalMember("leo", "Leo", 1),
    "mom": CalMember("mom", "Mom", 2),
    "dad": CalMember("dad", "Dad", 3),
}


@dataclass(frozen=True)
class CalActivity:
    """One activity. `weekdays` non-empty means a weekly series ([cal-1]/[cal-2])."""

    key: str
    title: str
    location: str
    weekdays: tuple[int, ...] = ()  # 0=Mon .. 6=Sun; empty = one-off
    on: date | None = None  # one-off anchor
    start: time | None = None  # None = all-day
    end: time | None = None
    who: tuple[str, ...] = ()  # member keys; empty = household-wide


def _d(days: int) -> date:
    return date.today() + timedelta(days=days)


CAL_ACTIVITIES: tuple[CalActivity, ...] = (
    CalActivity(
        "volleyball",
        "Volleyball practice",
        "The gym",
        (0, 3),
        start=time(16, 0),
        end=time(17, 30),
        who=("emma",),
    ),
    CalActivity(
        "dancing",
        "Dancing lesson",
        "Dance studio",
        (2,),
        start=time(15, 0),
        end=time(16, 0),
        who=("leo",),
    ),
    CalActivity(
        "soccer",
        "Soccer practice",
        "The fields",
        (5,),
        start=time(10, 0),
        end=time(11, 30),
        who=("leo",),
    ),
    CalActivity(
        "games", "Family game afternoon", "Living room", (5,), start=time(14, 0), end=time(16, 0)
    ),
    CalActivity(
        "dentist",
        "Dentist appointment",
        "Dr. Patel",
        on=_d(2),
        start=time(11, 30),
        end=time(12, 15),
        who=("emma",),
    ),
    CalActivity("noschool", "No school — long weekend", "", on=_d(4)),
    CalActivity("birthday", "Grandma's birthday", "", on=_d(9)),
)

CAL_OCCS: list["CalOcc"] = []


@dataclass(frozen=True)
class CalOcc:
    activity: CalActivity
    on: date


def _cal_seed() -> None:
    """Expand series over a fixed window at stub time — the [cal-2] shape, in memory."""
    if CAL_OCCS:
        return
    today = date.today()
    lo, hi = today - timedelta(days=90), today + timedelta(days=180)
    for act in CAL_ACTIVITIES:
        if act.weekdays:
            day = lo
            while day <= hi:
                if day.weekday() in act.weekdays:
                    CAL_OCCS.append(CalOcc(act, day))
                day += timedelta(days=1)
        elif act.on is not None:
            CAL_OCCS.append(CalOcc(act, act.on))


def _cal_item(occ: CalOcc) -> dict[str, Any]:
    a = occ.activity
    if a.start is None:
        time_long, time_short = "All day", "All day"
    else:
        begin = a.start.strftime("%-I:%M %p").lstrip("0")
        finish = a.end.strftime("%-I:%M %p").lstrip("0") if a.end else ""
        time_long = f"{begin} - {finish}" if finish else begin
        time_short = a.start.strftime("%H:%M")
    return {
        "title": a.title,
        "location": a.location,
        "repeat": bool(a.weekdays),
        "allday": a.start is None,
        "time_long": time_long,
        "time_short": time_short,
        "who": [CAL_MEMBERS[k] for k in a.who],
        "who_initials": "".join(CAL_MEMBERS[k].name[0] for k in a.who),
        "household": not a.who,
    }


def _cal_day(day: date, by_day: dict[date, list[CalOcc]]) -> dict[str, Any]:
    items = sorted(
        by_day.get(day, []), key=lambda o: (o.activity.start or time.min, o.activity.title)
    )
    return {
        "date": day,
        "iso": day.isoformat(),
        "weekday": day.strftime("%a"),
        "day_long": day.strftime("%A, %B %-d"),
        "day_num": day.strftime("%-d"),
        "is_today": day == date.today(),
        "in_month": True,
        "offset": (day - date.today()).days,
        "occs": [_cal_item(o) for o in items],
    }


def _cal_month_days(o: int, by_day: dict[date, list[CalOcc]]) -> list[dict[str, Any]]:
    anchor = (date.today().replace(day=1) + timedelta(days=32 * o)).replace(day=1)
    month_end = (anchor.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    first = anchor - timedelta(days=anchor.weekday())
    last = month_end + timedelta(days=6 - month_end.weekday())
    days = []
    day = first
    while day <= last:
        d = _cal_day(day, by_day)
        d["in_month"] = day.month == anchor.month
        days.append(d)
        day += timedelta(days=1)
    return days


def _cal_week_days(o: int, by_day: dict[date, list[CalOcc]]) -> list[dict[str, Any]]:
    start = date.today() + timedelta(days=7 * o - date.today().weekday())
    return [_cal_day(start + timedelta(days=i), by_day) for i in range(7)]


def _cal_range_label(view: str, days: list[dict[str, Any]], o: int) -> str:
    if view == "month":
        anchor = date.today().replace(day=1) + timedelta(days=32 * o)
        return anchor.strftime("%B %Y")
    if view == "week":
        start = days[0]["date"].strftime("%b %-d")
        end = days[-1]["date"].strftime("%b %-d")
        return f"{start} - {end}"
    return days[0]["date"].strftime("%A, %B %-d")


def _cal_context(variant: str, view: str, o: int) -> dict[str, Any]:
    _cal_seed()
    by_day: dict[date, list[CalOcc]] = {}
    for occ in CAL_OCCS:
        by_day.setdefault(occ.on, []).append(occ)
    if view == "month":
        days = _cal_month_days(o, by_day)
    elif view == "week":
        days = _cal_week_days(o, by_day)
    else:
        days = [_cal_day(date.today() + timedelta(days=o), by_day)]
    days_list = days
    weeks = []
    if view == "month":
        this_monday = date.today() - timedelta(days=date.today().weekday())
        for i in range(0, len(days_list), 7):
            band = days_list[i : i + 7]
            band_start = band[0]["date"].strftime("%b %-d")
            band_end = band[6]["date"].strftime("%b %-d")
            weeks.append(
                {
                    "offset": (band[0]["date"] - this_monday).days // 7,
                    "label": f"{band_start} - {band_end}",
                    "days": band,
                }
            )
    return {
        "variant": variant,
        "variant_label": CAL_VARIANTS[variant],
        "variant_keys": list(CAL_VARIANTS),
        "view": view,
        "view_label": CAL_VIEWS[view],
        "view_keys": list(CAL_VIEWS.items()),
        "o": o,
        "range_label": _cal_range_label(view, days, o),
        "days": days,
        "weeks": weeks,
    }


def _cal_page_context(variant: str, view: str, o: int) -> dict[str, Any]:
    from nidaro.web.routes.ui import _nav

    return {"nav": _nav("calendar")} | _cal_context(variant, view, o)


@router.get("/calendar")
async def calendar_proto(
    request: Request,
    variant: Annotated[str, Query(pattern="wall|agenda|board")] = "wall",
    view: Annotated[str, Query(pattern="month|week|day")] = "month",
    o: int = 0,
):
    return templates.TemplateResponse(request, "pc.html", _cal_page_context(variant, view, o))
