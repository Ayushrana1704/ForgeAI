from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.agent_run import AgentRun
from app.domain.entities.agent_step import AgentStep
from app.domain.value_objects.run_status import RunStatus


class RunRepository(ABC):
    @abstractmethod
    async def get_by_id(self, run_id: UUID) -> AgentRun | None: ...

    @abstractmethod
    async def list_by_project(
        self,
        project_id: UUID,
        offset: int = 0,
        limit: int = 20,
    ) -> list[AgentRun]: ...

    @abstractmethod
    async def create(self, run: AgentRun) -> AgentRun: ...

    @abstractmethod
    async def update_status(
        self,
        run_id: UUID,
        status: RunStatus,
        error_message: str | None = None,
    ) -> None: ...

    @abstractmethod
    async def save_graph_state(
        self,
        run_id: UUID,
        graph_state: dict,
    ) -> None: ...

    @abstractmethod
    async def get_steps(self, run_id: UUID) -> list[AgentStep]: ...

    @abstractmethod
    async def upsert_step(self, step: AgentStep) -> AgentStep: ...
