from typing import Any

from pydantic_deep import create_deep_agent

from nidaro.assistant.prompt import SYSTEM_PROMPT
from nidaro.assistant.tools import build_tools
from nidaro.config import Settings
from nidaro.container import ApplicationServices


def create_agent(settings: Settings, services: ApplicationServices, model: Any = None) -> Any:
    configured_model = model or settings.model
    if configured_model is None:
        raise RuntimeError("NIDARO_MODEL is not configured; assistant calls are disabled")
    return create_deep_agent(
        model=configured_model,
        instructions=SYSTEM_PROMPT,
        tools=build_tools(services),
        include_todo=True,
        include_filesystem=False,
        include_execute=False,
        include_subagents=False,
        include_builtin_subagents=False,
        include_skills=False,
        include_plan=False,
        include_memory=False,
        web_search=False,
        web_fetch=False,
        context_manager=True,
        stuck_loop_detection=True,
        cost_tracking=True,
        instrument=True,
    )
