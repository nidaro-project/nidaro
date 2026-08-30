"""PROTOTYPE — throwaway UI explorations. Delete before merge.

- [mealplan-1]: three variants of the meals week view on /prototype/week-view.
- [mealplan-2]: dish configuration variants on /prototype/dishes.

All state lives in in-memory stubs; nothing touches the database or the real
domains.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
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
