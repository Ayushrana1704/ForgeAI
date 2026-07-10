"""
Prompt templates for the Requirements Analyst agent.

Output contract
---------------
The LLM MUST return a markdown document with exactly these six H2 headings:

    ## Functional Requirements
    ## Non-Functional Requirements
    ## Assumptions
    ## Missing Information
    ## Risks
    ## Suggested Improvements
"""
from __future__ import annotations

from app.application.services.llm.types import ChatMessage, MessageRole

# ── Section heading constants (shared with parser in node) ────────────────────

SECTION_FUNCTIONAL = "## Functional Requirements"
SECTION_NON_FUNCTIONAL = "## Non-Functional Requirements"
SECTION_ASSUMPTIONS = "## Assumptions"
SECTION_MISSING = "## Missing Information"
SECTION_RISKS = "## Risks"
SECTION_IMPROVEMENTS = "## Suggested Improvements"

REQUIRED_SECTIONS: tuple[str, ...] = (
    SECTION_FUNCTIONAL,
    SECTION_NON_FUNCTIONAL,
    SECTION_ASSUMPTIONS,
    SECTION_MISSING,
    SECTION_RISKS,
    SECTION_IMPROVEMENTS,
)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT: str = f"""\
You are a Requirements Analyst. Analyse the given project requirements and output \
a structured markdown document with exactly these six H2 sections in order. \
Be concise. Use bullet points only. Maximum 3 bullets per section. \
No explanations outside the sections. No preamble. No postamble.

{SECTION_FUNCTIONAL}
- List core features only.

{SECTION_NON_FUNCTIONAL}
- List performance, security, and scalability constraints.

{SECTION_ASSUMPTIONS}
- List assumptions made to fill gaps.

{SECTION_MISSING}
- List missing information that blocks implementation. If none: "- None identified."

{SECTION_RISKS}
- List top risks. If none: "- None identified."

{SECTION_IMPROVEMENTS}
- List top improvements. If none: "- None identified."
"""

# ── Message builder ───────────────────────────────────────────────────────────


def build_requirements_analyst_messages(raw_requirements: str) -> list[ChatMessage]:
    """
    Build the chat message list for the Requirements Analyst LLM call.

    Args:
        raw_requirements: The unprocessed requirements text submitted by the user.

    Returns:
        A two-element list: [system_message, user_message].
    """
    return [
        ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
        ChatMessage(role=MessageRole.USER, content=raw_requirements.strip()),
    ]
