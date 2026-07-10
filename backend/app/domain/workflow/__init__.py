"""
ForgeAI workflow domain — shared state and supporting types.

Public surface area for the rest of the codebase:

    from app.domain.workflow import (
        ForgeState,
        create_forge_state,
        forge_state_to_json,
        forge_state_from_json,
        forge_state_log_context,
        ExecutionStatus,
        ArtifactInfo,
        AgentResult,
    )
"""
from app.domain.workflow.forge_state import (
    ForgeState,
    create_forge_state,
    forge_state_from_json,
    forge_state_log_context,
    forge_state_to_json,
)
from app.domain.workflow.types import AgentResult, ArtifactInfo, ExecutionStatus

__all__ = [
    "ForgeState",
    "create_forge_state",
    "forge_state_to_json",
    "forge_state_from_json",
    "forge_state_log_context",
    "ExecutionStatus",
    "ArtifactInfo",
    "AgentResult",
]
