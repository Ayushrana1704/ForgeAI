from enum import StrEnum


class ProjectStatus(StrEnum):
    """Lifecycle states of a ForgeAI project.

    Transitions (valid paths for the AI workflow):
        DRAFT → GENERATING → REVIEWING → COMPLETED
                           ↘ FAILED     ↗ FAILED
    """

    # Project has been created and its requirements can still be edited.
    # No agent run has started.
    DRAFT = "draft"

    # An agent run is in progress — requirements are locked until the run ends.
    GENERATING = "generating"

    # Agent run completed successfully; output is awaiting human review.
    REVIEWING = "reviewing"

    # Human accepted the generated output.  Terminal state.
    COMPLETED = "completed"

    # Agent run encountered an unrecoverable error.  Terminal state.
    FAILED = "failed"
