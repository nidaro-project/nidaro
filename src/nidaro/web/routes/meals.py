"""Meals week view: a rolling 7-day planner over the meals domain service.

Server-rendered Jinja2 + HTMX. Add/remove swap one day x slot cell fragment in
place, so planning never reloads the page. Routes stay thin: household and
meals application services only, never repositories.
"""

from datetime import date, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from nidaro.container import ApplicationServices
from nidaro.household.schemas import HouseholdView
from nidaro.meals.schemas import PlanMealRequest, PlannedMealView, Slot
from nidaro.web.dependencies import get_services
from nidaro.web.routes.ui import _nav, templates

router = APIRouter(prefix="/meals", include_in_schema=False)

SLOTS: tuple[Slot, ...] = ("breakfast", "lunch", "dinner", "snacks")


def _window(w: int) -> list[date]:
    start = date.today() + timedelta(weeks=w)
    return [start + timedelta(days=i) for i in range(7)]


def _range_label(days: list[date]) -> str:
    return f"{days[0].strftime('%b %-d')} - {days[-1].strftime('%b %-d')}"


def _day_view(day: date, index: int) -> dict[str, Any]:
    return {
        "date": day,
        "index": index,
        "iso": day.isoformat(),
        "weekday": day.strftime("%a"),
        "day_num": day.strftime("%-d"),
        "month": day.strftime("%b"),
        "is_today": day == date.today(),
    }


def _group_by_cell(
    meals: list[PlannedMealView],
) -> dict[tuple[date, Slot], list[PlannedMealView]]:
    grouped: dict[tuple[date, Slot], list[PlannedMealView]] = {}
    for meal in meals:
        grouped.setdefault((meal.date, meal.slot), []).append(meal)
    return grouped


def _day_views(days: list[date], grouped: dict[tuple[date, Slot], list[PlannedMealView]]):
    return [
        _day_view(day, index) | {"entries": {slot: grouped.get((day, slot), []) for slot in SLOTS}}
        for index, day in enumerate(days)
    ]


async def _guard(services: ApplicationServices, w: int, on: date):
    # Shared preconditions for the mutation endpoints: a seeded household and a
    # date inside the displayed window. Runs BEFORE any service mutation.
    household = await services.household.get_household()
    if household is None:
        raise HTTPException(status_code=404, detail="Household not seeded")
    days = _window(w)
    if on not in days:
        raise HTTPException(status_code=404, detail="Date outside the displayed week")
    return household, days


async def _cell_fragment(
    request: Request,
    services: ApplicationServices,
    household: HouseholdView,
    days: list[date],
    on: date,
    slot: Slot,
    w: int,
):
    dishes = await services.meals.list_dishes(household.id)
    planned = await services.meals.list_planned_meals(household.id, on, on)
    day = _day_view(on, days.index(on)) | {
        "entries": {slot: [m for m in planned if m.slot == slot]}
    }
    return templates.TemplateResponse(
        request,
        "meals_cell.html",
        {"w": w, "dishes": dishes, "day": day, "slot": slot},
    )


@router.get("")
async def week(
    request: Request,
    w: int = 0,
    services: ApplicationServices = Depends(get_services),  # noqa: B008
):
    household = await services.household.get_household()
    if household is None:
        return templates.TemplateResponse(request, "meals.html", {"nav": _nav("meals")})
    days = _window(w)
    dishes = await services.meals.list_dishes(household.id)
    planned = await services.meals.list_planned_meals(household.id, days[0], days[-1])
    return templates.TemplateResponse(
        request,
        "meals.html",
        {
            "nav": _nav("meals"),
            "w": w,
            "slots": SLOTS,
            "dishes": dishes,
            "days": _day_views(days, _group_by_cell(planned)),
            "range_label": _range_label(days),
            "prev_w": w - 1,
            "next_w": w + 1,
        },
    )


@router.post("/plan")
async def plan(
    request: Request,
    w: Annotated[int, Form()],
    on: Annotated[date, Form()],
    slot: Annotated[Slot, Form()],
    dish_id: Annotated[str, Form()] = "",
    name: Annotated[str, Form()] = "",
    services: ApplicationServices = Depends(get_services),  # noqa: B008
):
    household, days = await _guard(services, w, on)
    clean = name.strip()
    if not dish_id and not clean:
        # Nothing picked and nothing typed: just re-render the cell as-is.
        return await _cell_fragment(request, services, household, days, on, slot, w)
    # The dropdown wins over a typed name: a one-off name only applies when
    # the dropdown is left on its empty "One-off…" option.
    try:
        if dish_id:
            planned = PlanMealRequest(
                household_id=household.id, date=on, slot=slot, dish_id=UUID(dish_id)
            )
        else:
            planned = PlanMealRequest(household_id=household.id, date=on, slot=slot, name=clean)
        await services.meals.plan_meal(planned)
    except ValueError:
        raise HTTPException(status_code=404, detail="Dish not found") from None
    return await _cell_fragment(request, services, household, days, on, slot, w)


@router.post("/planned/remove")
async def remove(
    request: Request,
    w: Annotated[int, Form()],
    on: Annotated[date, Form()],
    slot: Annotated[Slot, Form()],
    meal_id: Annotated[UUID, Form()],
    services: ApplicationServices = Depends(get_services),  # noqa: B008
):
    household, days = await _guard(services, w, on)
    await services.meals.remove_planned_meal(meal_id)
    return await _cell_fragment(request, services, household, days, on, slot, w)
