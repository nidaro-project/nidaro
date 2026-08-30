from fastapi.testclient import TestClient

from nidaro.app import create_app


def _client() -> TestClient:
    # No lifespan context: UI pages must render without touching PostgreSQL or Redis.
    return TestClient(create_app())


def test_home_renders_shell():
    response = _client().get("/")
    assert response.status_code == 200
    assert "Good morning, Morgan family" in response.text
    assert 'data-theme="daylight"' in response.text
    assert response.text.count('class="nav__link"') == 9


def test_home_links_static_assets():
    response = _client().get("/")
    for asset in (
        "/static/css/tokens.css",
        "/static/css/app.css",
        "/static/js/htmx.min.js",
        "/static/img/plant.png",
    ):
        assert asset in response.text


def test_settings_renders_theme_picker():
    response = _client().get("/settings")
    assert response.status_code == 200
    for theme in ("daylight", "meadow", "dusk"):
        assert f'data-theme-choice="{theme}"' in response.text


def test_section_renders_placeholder():
    response = _client().get("/calendar")
    assert response.status_code == 200
    assert "Calendar is on its way" in response.text


def test_unknown_section_is_not_found():
    assert _client().get("/does-not-exist").status_code == 404


def test_static_asset_is_served():
    response = _client().get("/static/js/htmx.min.js")
    assert response.status_code == 200
