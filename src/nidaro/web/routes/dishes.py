"""Typical dishes — the dish configuration page ([mealplan-5]).

Server-rendered table of the household's dish rotation, backed by the meals
domain service. HTMX actions re-render the table block; deleting a dish never
dangles planned meals because planning copies the name.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request

from nidaro.container import ApplicationServices
from nidaro.meals.schemas import CreateDishRequest, UpdateDishRequest
from nidaro.web.dependencies import get_services
from nidaro.web.routes.ui import _nav, templates

router = APIRouter(prefix="/meals", include_in_schema=False)

Services = Annotated[ApplicationServices, Depends(get_services)]


def _parse_tags(raw: str) -> list[str]:
    """One comma-separated input -> clean tag list. Semicolons count as commas."""
    return [tag.strip() for tag in raw.replace(";", ",").split(",") if tag.strip()]


async def _dish_context(services: ApplicationServices, edit: UUID | None) -> dict[str, Any]:
    household = await services.household.get_household()
    dishes = await services.meals.list_dishes(household.id) if household else []
    return {"has_household": household is not None, "dishes": dishes, "edit": edit}


def _page(request: Request, context: dict[str, Any]):
    return templates.TemplateResponse(request, "dishes.html", {"nav": _nav("meals")} | context)


def _block(request: Request, context: dict[str, Any]):
    return templates.TemplateResponse(request, "dishes_table.html", context)


async def _render_block(request: Request, services: ApplicationServices, edit: UUID | None):
    return _block(request, await _dish_context(services, edit))


@router.get("/dishes")
async def dishes_page(request: Request, services: Services, edit: UUID | None = None):
    """Full page on plain navigations; the table block alone for HTMX (Edit/Cancel)."""
    context = await _dish_context(services, edit)
    if "HX-Request" in request.headers:
        return _block(request, context)
    return _page(request, context)


@router.post("/dishes")
async def create_dish(
    request: Request,
    services: Services,
    name: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    household = await services.household.get_household()
    clean = name.strip()
    if household and clean:
        await services.meals.create_dish(
            CreateDishRequest(
                household_id=household.id,
                name=clean,
                notes=notes.strip() or None,
                tags=_parse_tags(tags),
            )
        )
    return await _render_block(request, services, None)


@router.post("/dishes/{dish_id}")
async def edit_dish(
    request: Request,
    dish_id: UUID,
    services: Services,
    name: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    clean = name.strip()
    if clean:
        await services.meals.update_dish(
            dish_id,
            UpdateDishRequest(name=clean, notes=notes.strip() or None, tags=_parse_tags(tags)),
        )
    return await _render_block(request, services, None)


@router.post("/dishes/{dish_id}/delete")
async def delete_dish(request: Request, dish_id: UUID, services: Services):
    await services.meals.delete_dish(dish_id)
    return await _render_block(request, services, None)
