"""School portal: per-kid Today at school, Grades, Homework — information-portal reads.

Adopted shape from [portal-4] (variant B, "Module feed"): kid rail, module stacks.
Reads go through the school domain service only. The freshness stamp and manual
refresh action land with the gatherer ([portal-7]); the page renders the gather
state the data carries today.
"""

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from nidaro.container import ApplicationServices
from nidaro.web.dependencies import get_services
from nidaro.web.routes.ui import _nav, templates

router = APIRouter(prefix="/school", include_in_schema=False)

Services = Annotated[ApplicationServices, Depends(get_services)]


def _kids(household) -> list[Any]:
    return [m for m in household.members if m.role == "child"]


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
        "gather_error": None,
        "lessons": [],
        "grades": [],
        "homework": [],
    }
    if selected is not None:
        context["lessons"] = await services.school.lessons_on(selected.id, date.today())
        context["grades"] = await services.school.grades_for(selected.id)
        context["homework"] = await services.school.homework_for(selected.id)
    return templates.TemplateResponse(request, "school.html", context)
