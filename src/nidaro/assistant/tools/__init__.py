from nidaro.assistant.tools.calendar import build_calendar_tools
from nidaro.assistant.tools.commitments import build_commitment_tools
from nidaro.assistant.tools.family import build_family_tools
from nidaro.assistant.tools.memory import build_memory_tools
from nidaro.assistant.tools.tasks import build_task_tools
from nidaro.container import ApplicationServices


def build_tools(services: ApplicationServices) -> list[object]:
    return [
        *build_family_tools(services),
        *build_calendar_tools(services),
        *build_task_tools(services),
        *build_memory_tools(services),
        *build_commitment_tools(services),
    ]
