from typing import Any

from fastapi import APIRouter, Request
from redis.asyncio import Redis
from sqlalchemy import text

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> dict[str, str]:
    services = request.app.state.services
    redis: Redis = request.app.state.redis
    try:
        async with services.household.repository.sessions() as session:
            await session.execute(text("SELECT 1"))
        redis_client: Any = redis
        await redis_client.ping()
    except Exception as error:
        raise RuntimeError("Nidaro dependencies are not ready") from error
    return {"status": "ready"}
