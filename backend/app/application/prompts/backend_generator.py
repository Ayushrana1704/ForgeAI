"""
Prompt templates for the Backend Generator agent.

Output contract
---------------
The LLM MUST return a markdown document with exactly these ten H2 section
headings in this order:

    ## Project Structure
    ## API Modules
    ## Database Layer
    ## Repository Layer
    ## Service Layer
    ## Authentication
    ## Dependency Injection
    ## Middleware
    ## Validation
    ## Testing Strategy
"""
from __future__ import annotations

from app.application.services.llm.types import ChatMessage, MessageRole

# ── Section heading constants (shared with parser in node) ────────────────────

SECTION_PROJECT_STRUCTURE = "## Project Structure"
SECTION_API_MODULES = "## API Modules"
SECTION_DATABASE_LAYER = "## Database Layer"
SECTION_REPOSITORY_LAYER = "## Repository Layer"
SECTION_SERVICE_LAYER = "## Service Layer"
SECTION_AUTHENTICATION = "## Authentication"
SECTION_DEPENDENCY_INJECTION = "## Dependency Injection"
SECTION_MIDDLEWARE = "## Middleware"
SECTION_VALIDATION = "## Validation"
SECTION_TESTING_STRATEGY = "## Testing Strategy"

REQUIRED_SECTIONS: tuple[str, ...] = (
    SECTION_PROJECT_STRUCTURE,
    SECTION_API_MODULES,
    SECTION_DATABASE_LAYER,
    SECTION_REPOSITORY_LAYER,
    SECTION_SERVICE_LAYER,
    SECTION_AUTHENTICATION,
    SECTION_DEPENDENCY_INJECTION,
    SECTION_MIDDLEWARE,
    SECTION_VALIDATION,
    SECTION_TESTING_STRATEGY,
)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT: str = f"""\
You are a Backend Engineer. Produce a concise backend implementation blueprint. \
Output ONLY a structured markdown document with exactly these ten H2 sections. \
Maximum 3 bullets per section. Implementation-ready only. No source code bodies. \
No explanations outside sections. No preamble. No postamble.

{SECTION_PROJECT_STRUCTURE}
- List key directories and their purpose only.

{SECTION_API_MODULES}
- List routers: name, path prefix, key endpoints.

{SECTION_DATABASE_LAYER}
- ORM, engine config, migration tool.

{SECTION_REPOSITORY_LAYER}
- Abstract repo interface pattern, CRUD methods.

{SECTION_SERVICE_LAYER}
- Service classes, DI pattern, business rules location.

{SECTION_AUTHENTICATION}
- Token type, signing, password hashing, FastAPI dependency.

{SECTION_DEPENDENCY_INJECTION}
- Provider chain: settings → session → repo → service.

{SECTION_MIDDLEWARE}
- CORS, request ID, error handling order.

{SECTION_VALIDATION}
- Pydantic models, field validators, error surfacing.

{SECTION_TESTING_STRATEGY}
- Framework, fixtures, mocking strategy.
"""

# ── Message builder ───────────────────────────────────────────────────────────


def build_backend_generator_messages(
    clarified_requirements: str,
    architecture_summary: str,
    database_schema: str,
    backend_task_summary: str,
) -> list[ChatMessage]:
    """
    Build the chat message list for the Backend Generator LLM call.

    Inputs are truncated to fit local model context limits.
    """
    user_content = (
        "## CLARIFIED REQUIREMENTS\n\n"
        f"{clarified_requirements.strip()[:2000]}\n\n"
        "---\n\n"
        "## SOFTWARE ARCHITECTURE\n\n"
        f"{architecture_summary.strip()[:2000]}\n\n"
        "---\n\n"
        "## DATABASE SCHEMA\n\n"
        f"{database_schema.strip()[:2000]}\n\n"
        "---\n\n"
        "## BACKEND TASKS\n\n"
        f"{backend_task_summary.strip()[:1500]}"
    )

    return [
        ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
        ChatMessage(role=MessageRole.USER, content=user_content),
    ]
