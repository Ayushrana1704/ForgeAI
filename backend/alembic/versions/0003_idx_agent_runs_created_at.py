"""Add index on agent_runs.created_at for analytics sort performance

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-07-09 12:00:00.000000

Background
----------
analytics_repository.list_runs() orders results by AgentRunModel.created_at
DESC but the table only had indexes on project_id and status.  On large
accounts this caused a full sequential scan for every analytics request.
This migration adds a single-column B-tree index that satisfies the
ORDER BY without touching unrelated rows.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c3d4e5f6a1b2"
down_revision: Union[str, None] = "b2c3d4e5f6a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_runs_created_at",
        "agent_runs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_runs_created_at", table_name="agent_runs")
