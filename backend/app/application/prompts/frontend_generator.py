"""
Prompt templates for the Frontend Generator agent.

Output contract
---------------
The LLM MUST return a markdown document with exactly these ten H2 section
headings in this order:

    ## Application Structure
    ## Feature Organization
    ## Routing
    ## State Management
    ## API Integration
    ## Authentication Flow
    ## UI Components
    ## Forms & Validation
    ## Error Handling
    ## Testing Strategy
"""
from __future__ import annotations

from app.application.services.llm.types import ChatMessage, MessageRole

# ── Section heading constants (shared with parser in node) ────────────────────

SECTION_APP_STRUCTURE = "## Application Structure"
SECTION_FEATURE_ORGANIZATION = "## Feature Organization"
SECTION_ROUTING = "## Routing"
SECTION_STATE_MANAGEMENT = "## State Management"
SECTION_API_INTEGRATION = "## API Integration"
SECTION_AUTH_FLOW = "## Authentication Flow"
SECTION_UI_COMPONENTS = "## UI Components"
SECTION_FORMS_VALIDATION = "## Forms & Validation"
SECTION_ERROR_HANDLING = "## Error Handling"
SECTION_TESTING_STRATEGY = "## Testing Strategy"

REQUIRED_SECTIONS: tuple[str, ...] = (
    SECTION_APP_STRUCTURE,
    SECTION_FEATURE_ORGANIZATION,
    SECTION_ROUTING,
    SECTION_STATE_MANAGEMENT,
    SECTION_API_INTEGRATION,
    SECTION_AUTH_FLOW,
    SECTION_UI_COMPONENTS,
    SECTION_FORMS_VALIDATION,
    SECTION_ERROR_HANDLING,
    SECTION_TESTING_STRATEGY,
)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT: str = f"""\
You are a Frontend Engineer. Produce a concise frontend implementation blueprint. \
Output ONLY a structured markdown document with exactly these ten H2 sections. \
Maximum 3 bullets per section. No source code. No explanations outside sections. \
No preamble. No postamble.

{SECTION_APP_STRUCTURE}
- Key directories and purpose.

{SECTION_FEATURE_ORGANIZATION}
- Feature modules and their components.

{SECTION_ROUTING}
- Router library, route paths, auth guards.

{SECTION_STATE_MANAGEMENT}
- Library, global slices, persistence policy.

{SECTION_API_INTEGRATION}
- HTTP client, interceptors, API module structure.

{SECTION_AUTH_FLOW}
- Login flow, token storage, refresh strategy.

{SECTION_UI_COMPONENTS}
- Shared components: Button, Input, Modal, Table, Spinner.

{SECTION_FORMS_VALIDATION}
- Form library, validation library, error display.

{SECTION_ERROR_HANDLING}
- ErrorBoundary placement, API error categories, toast system.

{SECTION_TESTING_STRATEGY}
- Framework, component tests, E2E tool, mock strategy.
"""

# ── Message builder ───────────────────────────────────────────────────────────


def build_frontend_generator_messages(
    clarified_requirements: str,
    architecture_summary: str,
    backend_code_summary: str,
    frontend_task_summary: str,
) -> list[ChatMessage]:
    """
    Build the chat message list for the Frontend Generator LLM call.

    Inputs are truncated to fit local model context limits.
    """
    user_content = (
        "## CLARIFIED REQUIREMENTS\n\n"
        f"{clarified_requirements.strip()[:2000]}\n\n"
        "---\n\n"
        "## SOFTWARE ARCHITECTURE\n\n"
        f"{architecture_summary.strip()[:1500]}\n\n"
        "---\n\n"
        "## BACKEND BLUEPRINT (summary)\n\n"
        f"{backend_code_summary.strip()[:1500]}\n\n"
        "---\n\n"
        "## FRONTEND TASKS\n\n"
        f"{frontend_task_summary.strip()[:1200]}"
    )

    return [
        ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
        ChatMessage(role=MessageRole.USER, content=user_content),
    ]
