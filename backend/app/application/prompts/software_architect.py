"""
Prompt templates for the Software Architect agent.

Output contract
---------------
The LLM MUST return a markdown document with exactly these eight H2 headings:

    ## Recommended Architecture Pattern
    ## Backend Structure
    ## Frontend Structure
    ## Database Design Overview
    ## API Design Overview
    ## Security Considerations
    ## Scalability Considerations
    ## Deployment Recommendations
"""
from __future__ import annotations

from app.application.services.llm.types import ChatMessage, MessageRole

# ── Section heading constants (shared with parser in node) ────────────────────

SECTION_ARCHITECTURE_PATTERN = "## Recommended Architecture Pattern"
SECTION_BACKEND = "## Backend Structure"
SECTION_FRONTEND = "## Frontend Structure"
SECTION_DATABASE = "## Database Design Overview"
SECTION_API = "## API Design Overview"
SECTION_SECURITY = "## Security Considerations"
SECTION_SCALABILITY = "## Scalability Considerations"
SECTION_DEPLOYMENT = "## Deployment Recommendations"

REQUIRED_SECTIONS: tuple[str, ...] = (
    SECTION_ARCHITECTURE_PATTERN,
    SECTION_BACKEND,
    SECTION_FRONTEND,
    SECTION_DATABASE,
    SECTION_API,
    SECTION_SECURITY,
    SECTION_SCALABILITY,
    SECTION_DEPLOYMENT,
)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT: str = f"""\
You are a Software Architect. Design a software architecture based on the given \
requirements. Output ONLY a structured markdown document with exactly these eight \
H2 sections in order. Maximum 12 components total across all sections. \
Use bullet points. Be concise. No explanations outside sections. \
No preamble. No postamble. Each section: 2-4 bullets maximum.

{SECTION_ARCHITECTURE_PATTERN}
- State the architecture style and justify briefly.

{SECTION_BACKEND}
- Framework, language, key patterns (e.g. FastAPI, Python, repository pattern).

{SECTION_FRONTEND}
- Framework, state management, routing.

{SECTION_DATABASE}
- Database type, key entities, ORM.

{SECTION_API}
- API style, auth mechanism, versioning.

{SECTION_SECURITY}
- Auth, authorisation, input validation, secrets.

{SECTION_SCALABILITY}
- Caching, horizontal scaling, bottlenecks.

{SECTION_DEPLOYMENT}
- Container/cloud target, CI/CD, monitoring.
"""

# ── Message builder ───────────────────────────────────────────────────────────


def build_software_architect_messages(
    clarified_requirements: str,
    architecture_notes: str | None,
) -> list[ChatMessage]:
    """
    Build the chat message list for the Software Architect LLM call.

    Inputs are truncated to fit local model context limits.
    """
    notes_block = (
        architecture_notes.strip()[:500]
        if architecture_notes
        else "No initial architecture notes provided."
    )

    user_content = (
        "## CLARIFIED REQUIREMENTS\n\n"
        f"{clarified_requirements.strip()[:2500]}\n\n"
        "---\n\n"
        "## INITIAL ARCHITECTURE NOTES\n\n"
        f"{notes_block}"
    )

    return [
        ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
        ChatMessage(role=MessageRole.USER, content=user_content),
    ]
