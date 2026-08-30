from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis

from nidaro.assistant.runtime import AssistantRuntime
from nidaro.config import get_settings
from nidaro.container import ApplicationServices
from nidaro.db.engine import create_engine, create_session_factory
from nidaro.web.routes import assistant, calendar, family, health, meals, prototype, ui


def create_app() -> FastAPI:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)  # pyright: ignore[reportUnknownMemberType]
    services = ApplicationServices.build(sessions)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            await redis.aclose()
            await engine.dispose()

    app = FastAPI(title="Nidaro", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.services = services
    app.state.redis = redis
    app.state.runtime = AssistantRuntime(settings, services)
    app.include_router(health.router)
    app.include_router(family.router)
    app.include_router(assistant.router)
    app.include_router(prototype.router)
    app.include_router(calendar.router)
    app.include_router(meals.router)
    app.include_router(ui.router)
    app.mount("/static", StaticFiles(directory=ui.STATIC_DIR), name="static")

    if settings.logfire_token:
        import logfire

        logfire.configure(token=settings.logfire_token)
        logfire.instrument_fastapi(app)
        logfire.instrument_httpx()
        logfire.instrument_sqlalchemy()
    return app
