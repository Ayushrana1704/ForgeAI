"""
Prompt templates for the Task Planner agent.

Output contract
---------------
The LLM MUST return a markdown document with exactly these six H2 section
headings in this order, each containing H3 task blocks:

    ## Backend Tasks
    ## Frontend Tasks
    ## Database Tasks
    ## Infrastructure Tasks
    ## Testing Tasks
    ## Deployment Tasks

Each H3 task block MUST use this exact structure:

    ### <ID>: <Title>
    - **Priority:** High | Medium | Low
    - **Complexity:** High | Medium | Low
    - **Description:** <one concise sentence>
    - **Dependencies:** <comma-separated IDs, or "None">

ID format: BE-001, FE-001, DB-001, INF-001, TST-001, DEP-001
"""
from __future__ import annotations

from app.application.services.llm.types import ChatMessage, MessageRole

# ── Section heading constants (shared with parser in node) ────────────────────

SECTION_BACKEND = "## Backend Tasks"
SECTION_FRONTEND = "## Frontend Tasks"
SECTION_DATABASE = "## Database Tasks"
SECTION_INFRASTRUCTURE = "## Infrastructure Tasks"
SECTION_TESTING = "## Testing Tasks"
SECTION_DEPLOYMENT = "## Deployment Tasks"

REQUIRED_SECTIONS: tuple[str, ...] = (
    SECTION_BACKEND,
    SECTION_FRONTEND,
    SECTION_DATABASE,
    SECTION_INFRASTRUCTURE,
    SECTION_TESTING,
    SECTION_DEPLOYMENT,
)

# Task field labels (shared with parser so renames stay in sync)
FIELD_PRIORITY = "**Priority:**"
FIELD_COMPLEXITY = "**Complexity:**"
FIELD_DESCRIPTION = "**Description:**"
FIELD_DEPENDENCIES = "**Dependencies:**"

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT: str = f"""\
You are a Technical Lead. Break down the given architecture into implementation \
tasks. Output ONLY a structured markdown document with exactly these six H2 \
sections. Maximum 25 tasks total (3-5 per section). \
No explanations outside sections. No preamble. No postamble.

{SECTION_BACKEND}
{SECTION_FRONTEND}
{SECTION_DATABASE}
{SECTION_INFRASTRUCTURE}
{SECTION_TESTING}
{SECTION_DEPLOYMENT}

For each task use exactly this format:

### <ID>: <Title>
- {FIELD_PRIORITY} High | Medium | Low
- {FIELD_COMPLEXITY} High | Medium | Low
- {FIELD_DESCRIPTION} One sentence.
- {FIELD_DEPENDENCIES} IDs or None

ID format: BE-001, FE-001, DB-001, INF-001, TST-001, DEP-001
"""

# ── Message builder ───────────────────────────────────────────────────────────


def build_task_planner_messages(
    clarified_requirements: str,
    architecture_summary: str,
) -> list[ChatMessage]:
    """
    Build the chat message list for the Task Planner LLM call.

    Inputs are truncated to fit local model context limits.
    """
    user_content = (
        "## CLARIFIED REQUIREMENTS\n\n"
        f"{clarified_requirements.strip()[:2500]}\n\n"
        "---\n\n"
        "## SOFTWARE ARCHITECTURE\n\n"
        f"{architecture_summary.strip()[:2500]}"
    )

    return [
        ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
        ChatMessage(role=MessageRole.USER, content=user_content),
    ]
