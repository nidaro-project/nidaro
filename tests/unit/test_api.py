import pytest


@pytest.mark.anyio
async def test_health_route_has_no_dependency_call():
    from nidaro.web.routes.health import health

    assert await health() == {"status": "ok"}
