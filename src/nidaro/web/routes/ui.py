"""Server-rendered UI shell. Design tokens and conventions live in DESIGN.md."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

WEB_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = WEB_DIR / "static"
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

# (slug, label, icon). Order is the sidebar order.
NAV_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("home", "Home", "home"),
    ("calendar", "Calendar", "calendar"),
    ("meals", "Meals", "meals"),
    ("shopping", "Shopping", "cart"),
    ("school", "School", "school"),
    ("family", "Family", "family"),
    ("notes", "Notes", "notes"),
    ("deals", "Deals", "deals"),
    ("settings", "Settings", "gear"),
)

# Placeholder sections have no route of their own yet; home, school, settings render.
SECTIONS = {
    slug: (label, icon)
    for slug, label, icon in NAV_ITEMS
    if slug not in {"home", "settings", "school"}
}

THEMES: tuple[dict[str, Any], ...] = (
    {"id": "daylight", "name": "Daylight", "description": "Warm paper, deep leaf green."},
    {"id": "meadow", "name": "Meadow", "description": "Light with a fresh green cast."},
    {"id": "dusk", "name": "Dusk", "description": "Dark, mossy, easy on the eyes."},
)

router = APIRouter(include_in_schema=False)


def _nav(active: str) -> list[dict[str, Any]]:
    return [
        {
            "href": "/" if slug == "home" else f"/{slug}",
            "label": label,
            "icon": icon,
            "active": slug == active,
        }
        for slug, label, icon in NAV_ITEMS
    ]


def _demo_home() -> dict[str, Any]:
    """Deterministic demo snapshot for the shell. Real data lands per integration."""
    return {
        "greeting_title": "Good morning, Morgan family",
        "greeting_sub": "Here's your family snapshot for today.",
        "weather": "☀️ 68°F",
        "today": "Friday, May 23",
        "assistant": [
            {
                "tile": "calendar",
                "icon": "calendar",
                "title": "2 upcoming appointments",
                "body": "Emma's dentist at 11:30 AM. Leo's soccer practice at 4:30 PM.",
                "link": "View today's schedule",
                "href": "/calendar",
            },
            {
                "tile": "school",
                "icon": "school",
                "title": "School reminder",
                "body": "Science project due Monday. Don't forget library books.",
                "link": "View school plan",
                "href": "/school",
            },
            {
                "tile": "shopping",
                "icon": "cart",
                "title": "Low on milk & eggs",
                "body": "Add 3 items to your shopping list. Save $12 with current deals.",
                "link": "View shopping list",
                "href": "/shopping",
            },
        ],
        "stats": [
            {
                "tile": "calendar",
                "icon": "calendar",
                "value": "6",
                "label": "Appointments",
                "sub": "This week",
            },
            {
                "tile": "school",
                "icon": "school",
                "value": "8",
                "label": "School items",
                "sub": "To do",
            },
            {
                "tile": "meals",
                "icon": "meals",
                "value": "14",
                "label": "Meals planned",
                "sub": "This week",
            },
            {
                "tile": "deals",
                "icon": "deals",
                "value": "$42",
                "label": "Est. savings",
                "sub": "This week",
            },
        ],
        "events": [
            {
                "day": "FRI",
                "date": "May 23",
                "time": "11:30 AM",
                "what": "Emma - Dentist Appointment",
                "category": "calendar",
            },
            {
                "day": "FRI",
                "date": "May 23",
                "time": "4:30 PM",
                "what": "Leo - Soccer Practice",
                "category": "shopping",
            },
            {
                "day": "SAT",
                "date": "May 24",
                "time": "10:00 AM",
                "what": "Farmers Market",
                "category": "meals",
            },
            {
                "day": "SAT",
                "date": "May 24",
                "time": "2:00 PM",
                "what": "Family Game Afternoon",
                "category": "deals",
            },
            {
                "day": "SUN",
                "date": "May 25",
                "time": "All day",
                "what": "No school - Long Weekend",
                "category": "family",
            },
            {
                "day": "MON",
                "date": "May 26",
                "time": "9:00 AM",
                "what": "Memorial Day - No School",
                "category": "calendar",
            },
        ],
        "meals": [
            {
                "day": "Tonight",
                "photo": 0,
                "title": "Lemon Herb Salmon",
                "sub": "with Roasted Veggies",
            },
            {"day": "Sat", "photo": 1, "title": "Chicken Tacos", "sub": "with Avocado Salad"},
            {"day": "Sun", "photo": None, "title": "Salmon Bowls", "sub": "Use leftovers"},
            {"day": "Mon", "photo": 3, "title": "Pasta Primavera", "sub": "with Garlic Bread"},
        ],
        "shopping": [
            {
                "title": "Needs attention",
                "items": [
                    "Milk",
                    "Eggs",
                    "Chicken breasts",
                    "Paper towels",
                    "Bananas",
                    "Dish soap",
                ],
            },
            {"title": "Pantry staples", "items": ["Rice", "Pasta", "Olive oil", "Cereal"]},
        ],
        "school": {
            "homework": [
                {"who": "Emma", "what": "Math Workbook (p. 45-47)", "due": "Mon"},
                {"who": "Leo", "what": "Reading Log", "due": "Tue"},
            ],
            "bring": [
                {"what": "Science project board", "due": "Mon"},
                {"what": "PE kit", "due": "Wed"},
            ],
            "lunch": ["🥪 Tuna wrap", "🍎 Apple slices", "🥣 Greek yogurt"],
        },
        "deals": [
            {
                "store_initial": "S",
                "name": "Blueberries",
                "size": "6 oz",
                "price": "$2.49",
                "was": "$3.99",
                "save": "$1.50",
            },
            {
                "store_initial": "S",
                "name": "Chicken Breasts",
                "size": "1.5 lbs",
                "price": "$6.49",
                "was": "$8.99",
                "save": "$2.50",
            },
        ],
        "scout": {"sub": "Vitamix 5200 Blender - 20% off at Best Buy", "ends": "Ends May 26"},
        "notes": [
            {
                "tone": "lavender",
                "title": "Talked with the Johnsons",
                "body": "Beach day next Saturday! Bring sunscreen and extra towels.",
                "date": "May 21",
            },
            {
                "tone": "sage",
                "title": "Mom's reminder",
                "body": "Pick up dry cleaning before Sunday.",
                "date": "May 22",
            },
        ],
        "promo": {"deals": "18", "saved": "$42"},
    }


@router.get("/")
async def home(request: Request):
    context = {"nav": _nav("home")} | _demo_home()
    return templates.TemplateResponse(request, "index.html", context)


@router.get("/settings")
async def settings(request: Request):
    themes = [theme | {"active": theme["id"] == "daylight"} for theme in THEMES]
    return templates.TemplateResponse(
        request, "settings.html", {"nav": _nav("settings"), "themes": themes}
    )


@router.get("/{section}")
async def section(section: str, request: Request):
    meta = SECTIONS.get(section)
    if meta is None:
        raise HTTPException(status_code=404, detail="Not found")
    label, icon = meta
    context = {
        "nav": _nav(section),
        "label": label,
        "icon": icon,
        "tile": icon if icon != "gear" else "family",
    }
    return templates.TemplateResponse(request, "placeholder.html", context)
