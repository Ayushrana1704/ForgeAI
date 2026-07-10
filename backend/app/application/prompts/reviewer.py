"""
Prompt templates for the Reviewer agent.

Output contract
---------------
The LLM MUST return a markdown document with exactly these nine H2 section
headings in this order:

    ## Missing Requirements
    ## Architectural Inconsistencies
    ## Database Issues
    ## Backend Gaps
    ## Frontend Gaps
    ## Security Concerns
    ## Performance Concerns
    ## Testing Gaps
    ## Deployment Concerns
"""
from __future__ import annotations

from app.application.services.llm.types import ChatMessage, MessageRole

# ── Section heading constants (shared with parser in node) ────────────────────

SECTION_MISSING_REQUIREMENTS = "## Missing Requirements"
SECTION_ARCH_INCONSISTENCIES = "## Architectural Inconsistencies"
SECTION_DATABASE_ISSUES = "## Database Issues"
SECTION_BACKEND_GAPS = "## Backend Gaps"
SECTION_FRONTEND_GAPS = "## Frontend Gaps"
SECTION_SECURITY_CONCERNS = "## Security Concerns"
SECTION_PERFORMANCE_CONCERNS = "## Performance Concerns"
SECTION_TESTING_GAPS = "## Testing Gaps"
SECTION_DEPLOYMENT_CONCERNS = "## Deployment Concerns"

REQUIRED_SECTIONS: tuple[str, ...] = (
    SECTION_MISSING_REQUIREMENTS,
    SECTION_ARCH_INCONSISTENCIES,
    SECTION_DATABASE_ISSUES,
    SECTION_BACKEND_GAPS,
    SECTION_FRONTEND_GAPS,
    SECTION_SECURITY_CONCERNS,
    SECTION_PERFORMANCE_CONCERNS,
    SECTION_TESTING_GAPS,
    SECTION_DEPLOYMENT_CONCERNS,
)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT: str = f"""\
You are a Staff Engineer performing a plan review. \
Output ONLY a structured markdown document with exactly these nine H2 sections. \
Maximum 3 bullets per section. If no issues: "- No issues found." \
No explanations outside sections. No preamble. No postamble. \
Do NOT rewrite documents. Only list findings as bullet points.

{SECTION_MISSING_REQUIREMENTS}
{SECTION_ARCH_INCONSISTENCIES}
{SECTION_DATABASE_ISSUES}
{SECTION_BACKEND_GAPS}
{SECTION_FRONTEND_GAPS}
{SECTION_SECURITY_CONCERNS}
{SECTION_PERFORMANCE_CONCERNS}
{SECTION_TESTING_GAPS}
{SECTION_DEPLOYMENT_CONCERNS}
"""

# ── Message builder ───────────────────────────────────────────────────────────


def build_reviewer_messages(
    clarified_requirements: str,
    architecture_summary: str,
    task_plan_summary: str,
    database_schema: str,
    backend_code_summary: str,
    frontend_code_summary: str,
) -> list[ChatMessage]:
    """
    Build the chat message list for the Reviewer LLM call.

    Inputs are truncated to fit local model context limits.
    """
    user_content = (
        "## REQUIREMENTS\n\n"
        f"{clarified_requirements.strip()[:1500]}\n\n"
        "---\n\n"
        "## ARCHITECTURE\n\n"
        f"{architecture_summary.strip()[:1500]}\n\n"
        "---\n\n"
        "## TASK PLAN\n\n"
        f"{task_plan_summary.strip()[:1000]}\n\n"
        "---\n\n"
        "## DATABASE SCHEMA\n\n"
        f"{database_schema.strip()[:1500]}\n\n"
        "---\n\n"
        "## BACKEND BLUEPRINT\n\n"
        f"{backend_code_summary.strip()[:3000]}\n\n"
        "---\n\n"
        "## FRONTEND BLUEPRINT\n\n"
        f"{frontend_code_summary.strip()[:3000]}"
    )

    return [
        ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
        ChatMessage(role=MessageRole.USER, content=user_content),
    ]
