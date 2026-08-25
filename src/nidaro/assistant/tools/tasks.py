from collections.abc import Callable
from typing import Any
from uuid import UUID

from nidaro.container import ApplicationServices
from nidaro.tasks.schemas import CreateTaskRequest, TaskView


def build_task_tools(services: ApplicationServices) -> list[Callable[..., Any]]:
    async def get_open_tasks(household_id: UUID) -> list[TaskView]:
        """Get open household tasks due in the next seven days."""
        return await services.tasks.get_open_tasks(household_id)

    async def create_task(request: CreateTaskRequest) -> TaskView:
        """Create an open household task."""
        return await services.tasks.create_task(request)

    async def complete_task(task_id: UUID) -> bool:
        """Mark a household task as done."""
        return await services.tasks.complete_task(task_id)

    return [get_open_tasks, create_task, complete_task]
