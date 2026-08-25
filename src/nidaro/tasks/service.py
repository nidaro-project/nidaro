from uuid import UUID

from nidaro.tasks.repository import TaskRepository
from nidaro.tasks.schemas import CreateTaskRequest, TaskView


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository

    async def get_open_tasks(self, household_id: UUID, days: int = 7) -> list[TaskView]:
        return [
            TaskView.model_validate(task) for task in await self.repository.open(household_id, days)
        ]

    async def create_task(self, request: CreateTaskRequest) -> TaskView:
        return TaskView.model_validate(await self.repository.create(request))

    async def complete_task(self, task_id: UUID) -> bool:
        return await self.repository.complete(task_id)
