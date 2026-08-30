"""Dish configuration page ([mealplan-5]): route handlers over stub-backed services."""

import re
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from nidaro.app import create_app
from nidaro.db.types import new_uuid, utc_now
from nidaro.household.models import Household
from nidaro.household.repository import HouseholdRepository
from nidaro.household.service import HouseholdService
from nidaro.meals.models import Dish
from nidaro.meals.repository import MealsRepository
from nidaro.meals.service import MealsService
from nidaro.web.dependencies import get_services
from nidaro.web.routes.dishes import _parse_tags

HOUSEHOLD_ID = uuid4()
HX = {"HX-Request": "true"}


def _household() -> Household:
    return Household(
        id=HOUSEHOLD_ID,
        name="My Family",
        timezone="UTC",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _dish(
    name="Chili con Carne", notes: str | None = "Freezes well.", tags=("one-pot", "freezer")
) -> Dish:
    return Dish(
        id=new_uuid(),
        household_id=HOUSEHOLD_ID,
        name=name,
        notes=notes,
        tags=list(tags),
        created_at=utc_now(),
        updated_at=utc_now(),
    )


class StubMealsRepository(MealsRepository):
    def __init__(self, dishes=()):
        self.by_id = {d.id: d for d in dishes}

    async def dishes(self, household_id):
        return sorted(
            (d for d in self.by_id.values() if d.household_id == household_id),
            key=lambda d: d.name,
        )

    async def create_dish(self, request):
        dish = Dish(
            id=new_uuid(),
            household_id=request.household_id,
            name=request.name,
            notes=request.notes,
            tags=request.tags,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.by_id[dish.id] = dish
        return dish

    async def update_dish(self, dish_id, request):
        dish = self.by_id.get(dish_id)
        if dish is None:
            return None
        for field, value in request.model_dump().items():
            setattr(dish, field, value)
        return dish

    async def delete_dish(self, dish_id):
        return self.by_id.pop(dish_id, None) is not None


class StubHouseholdRepository(HouseholdRepository):
    def __init__(self, household=None):
        self.value = household

    async def get(self, household_id=None):
        return self.value


def _client(*dishes, seeded=True):
    """TestClient whose services use the stubs; returns it plus the dish stub."""
    meals = StubMealsRepository(dishes)
    household = _household() if seeded else None
    app = create_app()
    app.dependency_overrides[get_services] = lambda: replace(
        app.state.services,
        meals=MealsService(meals),
        household=HouseholdService(StubHouseholdRepository(household)),
    )
    return TestClient(app), meals


# ---- page rendering ----


def test_dishes_page_renders_table_and_week_link():
    client, _ = _client(_dish())
    response = client.get("/meals/dishes")
    assert response.status_code == 200
    assert "Typical dishes" in response.text
    assert 'href="/meals"' in response.text
    assert "Add a dish" in response.text
    assert "Planned meals keep their name." in response.text


def test_dishes_page_lists_name_tags_notes():
    dish = _dish()
    client, _ = _client(dish)
    response = client.get("/meals/dishes")
    assert response.status_code == 200
    assert dish.name in response.text
    for tag in dish.tags:
        assert f">{tag}</span>" in response.text
    assert dish.notes is not None
    assert dish.notes in response.text


def test_dishes_page_has_no_editor_by_default():
    dish = _dish()
    client, _ = _client(dish)
    response = client.get("/meals/dishes")
    assert f'hx-post="/meals/dishes/{dish.id}"' not in response.text
    assert ">Cancel</button>" not in response.text


def test_dishes_page_opens_expanding_editor_on_edit():
    dish = _dish()
    client, _ = _client(dish)
    response = client.get("/meals/dishes", params={"edit": str(dish.id)})
    assert response.status_code == 200
    assert 'class="dishes-edit-row"' in response.text
    editor = response.text[
        response.text.index('class="dishes-edit-row"') : response.text.index("</tbody>")
    ]
    for label in ("Name", "Tags", "Notes"):
        assert re.search(rf">\s*{label}\s*\n", editor)
    assert f'value="{dish.name}"' in response.text
    assert 'value="one-pot, freezer"' in response.text
    assert ">Cancel</button>" in response.text


def test_htmx_edit_request_gets_fragment_not_page():
    dish = _dish()
    client, _ = _client(dish)
    response = client.get("/meals/dishes", params={"edit": str(dish.id)}, headers=HX)
    assert response.status_code == 200
    assert "<html" not in response.text
    assert 'id="dishes-block"' in response.text


def test_dishes_page_without_household_renders_empty_state():
    client, _ = _client(seeded=False)
    response = client.get("/meals/dishes")
    assert response.status_code == 200
    assert "No household yet" in response.text
    assert "Add a dish" not in response.text


def test_dishes_page_empty_list_prompts_first_dish():
    client, _ = _client()
    response = client.get("/meals/dishes")
    assert "No dishes yet" in response.text


# ---- create ----


def test_create_dish_strips_and_parses_form_fields():
    client, meals = _client()
    response = client.post(
        "/meals/dishes",
        data={"name": "  Pancakes  ", "tags": " weekend ; kids ,", "notes": " Buttermilk only "},
        headers=HX,
    )
    assert response.status_code == 200
    assert "Pancakes" in response.text
    dish = next(iter(meals.by_id.values()))
    assert dish.name == "Pancakes"
    assert dish.tags == ["weekend", "kids"]
    assert dish.notes == "Buttermilk only"


def test_create_dish_without_household_is_ignored():
    client, meals = _client(seeded=False)
    client.post("/meals/dishes", data={"name": "Pancakes"}, headers=HX)
    assert meals.by_id == {}


def test_create_dish_with_blank_name_is_ignored():
    client, meals = _client()
    client.post("/meals/dishes", data={"name": "   "}, headers=HX)
    assert meals.by_id == {}


# ---- update ----


def test_update_dish_persists_and_collapses():
    dish = _dish()
    client, meals = _client(dish)
    response = client.post(
        f"/meals/dishes/{dish.id}",
        data={"name": "Chili sin Carne", "tags": "veggie, one-pot", "notes": ""},
        headers=HX,
    )
    assert response.status_code == 200
    updated = meals.by_id[dish.id]
    assert updated.name == "Chili sin Carne"
    assert updated.tags == ["veggie", "one-pot"]
    assert updated.notes is None
    assert 'class="dishes-edit-row"' not in response.text


def test_update_dish_with_blank_name_leaves_dish_untouched():
    dish = _dish()
    client, meals = _client(dish)
    client.post(f"/meals/dishes/{dish.id}", data={"name": "  "}, headers=HX)
    assert meals.by_id[dish.id].name == dish.name


def test_update_missing_dish_still_renders_block():
    dish = _dish()
    client, _ = _client(dish)
    response = client.post(f"/meals/dishes/{uuid4()}", data={"name": "Ghost"}, headers=HX)
    assert response.status_code == 200
    assert 'id="dishes-block"' in response.text
    assert "Ghost" not in response.text


# ---- delete ----


def test_delete_dish_removes_only_target():
    dish = _dish()
    survivor = _dish(name="Pancakes", notes=None, tags=("weekend",))
    client, meals = _client(dish, survivor)
    response = client.post(f"/meals/dishes/{dish.id}/delete", headers=HX)
    assert response.status_code == 200
    assert dish.id not in meals.by_id
    assert survivor.id in meals.by_id
    assert survivor.name in response.text
    assert dish.name not in response.text


def test_delete_missing_dish_still_renders_block():
    client, _ = _client(_dish())
    response = client.post(f"/meals/dishes/{uuid4()}/delete", headers=HX)
    assert response.status_code == 200
    assert 'id="dishes-block"' in response.text


# ---- tag parsing ----


def test_parse_tags_splits_strips_and_drops_empties():
    assert _parse_tags("quick, favorite") == ["quick", "favorite"]
    assert _parse_tags(" weekend ; kids ,") == ["weekend", "kids"]
    assert _parse_tags("one") == ["one"]
    assert _parse_tags(" , ;; , ") == []
    assert _parse_tags("") == []
