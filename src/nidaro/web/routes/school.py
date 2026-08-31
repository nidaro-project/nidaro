"""School portal: per-kid Today at school, Grades, Homework, what-to-pack.

Adopted shape from [portal-4] (variant B, "Module feed"): kid rail, module stacks.
Reads go through the school domain service only. The gatherer ([portal-7]) fills
the refresh action and the gather-failure notice; the freshness stamp renders
from the gathered rows themselves. The packing overview ([portal-9]) is derived on
read: materialized lessons joined with household-maintained subject equipment.
"""

from datetime import date, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from nidaro.connectors.bakalari import BAKALARI
from nidaro.connectors.models import ConnectorContext
from nidaro.container import ApplicationServices
from nidaro.web.dependencies import get_services
from nidaro.web.routes.ui import _nav, templates

router = APIRouter(prefix="/school", include_in_schema=False)

Services = Annotated[ApplicationServices, Depends(get_services)]

GATHER_ERROR = "The gather failed — check the household's Bakaláři accounts."


def _kids(household) -> list[Any]:
    return [m for m in household.members if m.role == "child"]


async def _packing(services: ApplicationServices, kid_id: UUID) -> dict[str, Any]:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    packing = await services.school.pack_list(kid_id, [today, tomorrow])
    return {
        "subjects": await services.school.subjects_for(kid_id),
        "pack_today": packing[0].entries,
        "pack_tomorrow": packing[1].entries,
        "today": today,
        "tomorrow": tomorrow,
    }


@router.get("")
async def school(
    request: Request,
    services: Services,
    kid: UUID | None = None,
):
    household = await services.household.get_household()
    if household is None:
        raise HTTPException(status_code=404, detail="Household not seeded")
    kids = _kids(household)
    selected = next((k for k in kids if k.id == kid), kids[0] if kids else None)

    context: dict[str, Any] = {
        "nav": _nav("school"),
        "kids": kids,
        "kid": selected,
        "today": date.today(),
        "gather_error": GATHER_ERROR if request.query_params.get("gather") == "error" else None,
        "lessons": [],
        "grades": [],
        "homework": [],
    }
    if selected is not None:
        context["lessons"] = await services.school.lessons_on(selected.id, date.today())
        context["grades"] = await services.school.grades_for(selected.id)
        context["homework"] = await services.school.homework_for(selected.id)
        context |= await _packing(services, selected.id)
    return templates.TemplateResponse(request, "school.html", context)


async def _render_packing(request: Request, services: ApplicationServices, kid_id: UUID):
    context = {"kid": None, "gather_error": None} | await _packing(services, kid_id)
    return templates.TemplateResponse(request, "school_packing.html", context)


def _back(kid: UUID | None, gather_error: bool) -> str:
    parts: list[str] = []
    if kid is not None:
        parts.append(f"kid={kid}")
    if gather_error:
        parts.append("gather=error")
    return "/school" + ("?" + "&".join(parts) if parts else "")


@router.post("/refresh")
async def refresh_gather(services: Services, kid: Annotated[UUID | None, Form()] = None):
    """Manual gather: sync the household's Bakaláři accounts now, then redirect.

    The sync rides the same ConnectorService seam as the hourly worker, so a
    failed gather leaves the config un-stamped and stays due. A failure message
    rides the redirect; success is visible as fresh data and its stamp.
    """
    household = await services.household.get_household()
    if household is None:
        raise HTTPException(status_code=404, detail="Household not seeded")
    failed = False
    try:
        await services.connectors.sync(
            BAKALARI,
            ConnectorContext(household_id=str(household.id), timezone=household.timezone),
        )
    except Exception:
        failed = True
    return RedirectResponse(_back(kid, failed), status_code=303)


@router.post("/subjects/{subject_id}/equipment")
async def save_equipment(
    request: Request,
    subject_id: UUID,
    services: Services,
    items: Annotated[str, Form()] = "",
    kid: Annotated[UUID | None, Form()] = None,
    kid_query: UUID | None = None,
):
    """One equipment item per line; HTMX swaps the packing card, plain posts redirect."""
    kid_id = kid_query or kid
    household = await services.household.get_household()
    if household is None or kid_id is None or kid_id not in {k.id for k in _kids(household)}:
        raise HTTPException(status_code=404, detail="Kid not found")
    clean = [line.strip() for line in items.splitlines() if line.strip()]
    saved = await services.school.set_equipment(kid_id, subject_id, clean)
    if saved is None:
        raise HTTPException(status_code=404, detail="Subject not found for this kid")
    if "HX-Request" in request.headers:
        return await _render_packing(request, services, kid_id)
    return RedirectResponse(f"/school?kid={kid_id}", status_code=303)
