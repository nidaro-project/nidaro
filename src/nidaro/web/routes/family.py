from fastapi import APIRouter, Depends, HTTPException

from nidaro.container import ApplicationServices
from nidaro.web.dependencies import get_services

router = APIRouter(prefix="/api/v1/family", tags=["family"])


@router.get("/overview")
async def overview(services: ApplicationServices = Depends(get_services)) -> object:  # noqa: B008
    result = await services.household.get_household()
    if result is None:
        raise HTTPException(status_code=404, detail="Household not seeded")
    return result
