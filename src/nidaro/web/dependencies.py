from typing import cast

from fastapi import Request

from nidaro.assistant.runtime import AssistantRuntime
from nidaro.container import ApplicationServices


def get_services(request: Request) -> ApplicationServices:
    return cast(ApplicationServices, request.app.state.services)


def get_runtime(request: Request) -> AssistantRuntime:
    return cast(AssistantRuntime, request.app.state.runtime)
