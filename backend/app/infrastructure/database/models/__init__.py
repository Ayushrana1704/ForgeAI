# Import all models so SQLAlchemy registers them with the metadata.
# Alembic's env.py imports this module before autogenerating migrations.
from app.infrastructure.database.models.agent_run import AgentRunModel
from app.infrastructure.database.models.agent_step import AgentStepModel
from app.infrastructure.database.models.artifact import ArtifactModel
from app.infrastructure.database.models.llm_call import LLMCallModel
from app.infrastructure.database.models.project import ProjectModel
from app.infrastructure.database.models.user import UserModel

__all__ = [
    "UserModel",
    "ProjectModel",
    "AgentRunModel",
    "AgentStepModel",
    "ArtifactModel",
    "LLMCallModel",
]
