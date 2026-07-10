"""
Prompt templates for the Database Designer agent.

Output contract
---------------
The LLM MUST return a markdown document with exactly these eight H2 section
headings in this order:

    ## Entities
    ## Attributes
    ## Relationships
    ## Primary Keys
    ## Foreign Keys
    ## Constraints
    ## Suggested Indexes
    ## Normalization Notes
"""
from __future__ import annotations

from app.application.services.llm.types import ChatMessage, MessageRole

# ── Section heading constants (shared with parser in node) ────────────────────

SECTION_ENTITIES = "## Entities"
SECTION_ATTRIBUTES = "## Attributes"
SECTION_RELATIONSHIPS = "## Relationships"
SECTION_PRIMARY_KEYS = "## Primary Keys"
SECTION_FOREIGN_KEYS = "## Foreign Keys"
SECTION_CONSTRAINTS = "## Constraints"
SECTION_INDEXES = "## Suggested Indexes"
SECTION_NORMALIZATION = "## Normalization Notes"

REQUIRED_SECTIONS: tuple[str, ...] = (
    SECTION_ENTITIES,
    SECTION_ATTRIBUTES,
    SECTION_RELATIONSHIPS,
    SECTION_PRIMARY_KEYS,
    SECTION_FOREIGN_KEYS,
    SECTION_CONSTRAINTS,
    SECTION_INDEXES,
    SECTION_NORMALIZATION,
)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT: str = f"""\
You are a Database Architect. Design a PostgreSQL relational schema. \
Output ONLY a structured markdown document with exactly these eight H2 sections. \
Maximum 6 entities, 8 columns per entity, 8 indexes total. \
No explanations outside sections. No preamble. No postamble. Be concise.

{SECTION_ENTITIES}
- **EntityName** — one-sentence purpose. (Max 6 entities.)

{SECTION_ATTRIBUTES}
For each entity list columns as: `column_name TYPE [NOT NULL] — note`
(Max 8 columns per entity. UUID primary keys only.)

{SECTION_RELATIONSHIPS}
- **EntityA** → **EntityB**: cardinality (join column)

{SECTION_PRIMARY_KEYS}
- **EntityName**: id UUID

{SECTION_FOREIGN_KEYS}
- table.column → ref_table.column ON DELETE CASCADE|SET NULL

{SECTION_CONSTRAINTS}
- **EntityName**: UNIQUE/CHECK on (columns) — reason

{SECTION_INDEXES}
- table (columns) — purpose (Max 8 indexes.)

{SECTION_NORMALIZATION}
- Overall form: 3NF
- Any denormalisations with rationale.
"""

# ── Message builder ───────────────────────────────────────────────────────────


def build_database_designer_messages(
    clarified_requirements: str,
    architecture_summary: str,
    task_plan_summary: str,
) -> list[ChatMessage]:
    """
    Build the chat message list for the Database Designer LLM call.

    Inputs are truncated to fit local model context limits.
    """
    user_content = (
        "## CLARIFIED REQUIREMENTS\n\n"
        f"{clarified_requirements.strip()[:2500]}\n\n"
        "---\n\n"
        "## SOFTWARE ARCHITECTURE\n\n"
        f"{architecture_summary.strip()[:2000]}\n\n"
        "---\n\n"
        "## DATABASE TASKS\n\n"
        f"{task_plan_summary.strip()[:1000]}"
    )

    return [
        ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
        ChatMessage(role=MessageRole.USER, content=user_content),
    ]
