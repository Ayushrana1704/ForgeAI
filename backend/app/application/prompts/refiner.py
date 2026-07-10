"""
Prompt templates for the Refiner agent.

Output contract
---------------
The LLM MUST return a markdown document with exactly these six H2 section
headings in this order:

    ## Updated Architecture Notes
    ## Updated Task Recommendations
    ## Updated Database Notes
    ## Updated Backend Notes
    ## Updated Frontend Notes
    ## Summary of Improvements Applied
"""
from __future__ import annotations

from app.application.services.llm.types import ChatMessage, MessageRole

# ── Section heading constants (shared with parser in node) ────────────────────

SECTION_ARCH_NOTES = "## Updated Architecture Notes"
SECTION_TASK_RECOMMENDATIONS = "## Updated Task Recommendations"
SECTION_DATABASE_NOTES = "## Updated Database Notes"
SECTION_BACKEND_NOTES = "## Updated Backend Notes"
SECTION_FRONTEND_NOTES = "## Updated Frontend Notes"
SECTION_SUMMARY = "## Summary of Improvements Applied"

REQUIRED_SECTIONS: tuple[str, ...] = (
    SECTION_ARCH_NOTES,
    SECTION_TASK_RECOMMENDATIONS,
    SECTION_DATABASE_NOTES,
    SECTION_BACKEND_NOTES,
    SECTION_FRONTEND_NOTES,
    SECTION_SUMMARY,
)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT: str = f"""\
You are a Staff Engineer. Based on the review findings, produce targeted \
improvement notes. Output ONLY a structured markdown document with exactly \
these six H2 sections. Maximum 3 bullets per section. \
If no changes needed: "- No changes required." \
Do NOT rewrite full documents. Address only specific review findings. \
No preamble. No postamble. No explanations outside sections.

{SECTION_ARCH_NOTES}
- [ARCH-FIX] component: what to change.

{SECTION_TASK_RECOMMENDATIONS}
- [TASK-ADD] category: new task description.

{SECTION_DATABASE_NOTES}
- [DB-FIX] table.column: change needed.

{SECTION_BACKEND_NOTES}
- [BE-FIX] component: change needed.

{SECTION_FRONTEND_NOTES}
- [FE-FIX] component: change needed.

{SECTION_SUMMARY}
- Total findings addressed: N
- Critical fixes: N
- One-sentence readiness assessment.
"""

# ── Message builder ───────────────────────────────────────────────────────────


def build_refiner_messages(
    clarified_requirements: str,
    architecture_summary: str,
    task_plan_summary: str,
    database_schema: str,
    backend_code_summary: str,
    frontend_code_summary: str,
    review_notes_text: str,
) -> list[ChatMessage]:
    """
    Build the chat message list for the Refiner LLM call.

    Inputs are truncated to fit local model context limits.
    """
    user_content = (
        "## REQUIREMENTS\n\n"
        f"{clarified_requirements.strip()[:1000]}\n\n"
        "---\n\n"
        "## ARCHITECTURE\n\n"
        f"{architecture_summary.strip()[:1000]}\n\n"
        "---\n\n"
        "## TASK PLAN\n\n"
        f"{task_plan_summary.strip()[:800]}\n\n"
        "---\n\n"
        "## DATABASE SCHEMA\n\n"
        f"{database_schema.strip()[:800]}\n\n"
        "---\n\n"
        "## BACKEND BLUEPRINT\n\n"
        f"{backend_code_summary.strip()[:2500]}\n\n"
        "---\n\n"
        "## FRONTEND BLUEPRINT\n\n"
        f"{frontend_code_summary.strip()[:2500]}\n\n"
        "---\n\n"
        "## REVIEW FINDINGS\n\n"
        f"{review_notes_text.strip()[:2000]}"
    )

    return [
        ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
        ChatMessage(role=MessageRole.USER, content=user_content),
    ]
