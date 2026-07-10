"""initial schema

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-07-08 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_superuser",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    # Separate lookup index (unique constraint already enforces uniqueness)
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    # ── projects ───────────────────────────────────────────────────────────────
    op.create_table(
        "projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("requirements", sa.Text(), nullable=False),
        sa.Column(
            "tech_stack",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_projects_owner", "projects", ["owner_id"])
    op.create_index("idx_projects_status", "projects", ["status"])

    # ── agent_runs ─────────────────────────────────────────────────────────────
    op.create_table(
        "agent_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column(
            "trigger",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
        sa.Column(
            "graph_state",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_runs_project", "agent_runs", ["project_id"])
    op.create_index("idx_runs_status", "agent_runs", ["status"])

    # ── agent_steps ────────────────────────────────────────────────────────────
    op.create_table(
        "agent_steps",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_type", sa.String(100), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "input",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "output",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "tokens_used",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cost_usd",
            sa.Numeric(12, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_steps_run", "agent_steps", ["run_id"])
    op.create_index("idx_steps_sequence", "agent_steps", ["run_id", "sequence"])

    # ── artifacts ──────────────────────────────────────────────────────────────
    op.create_table(
        "artifacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_steps.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("artifact_type", sa.String(100), nullable=False),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("language", sa.String(50), nullable=True),
        sa.Column(
            "size_bytes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("storage_key", sa.String(1024), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        # ORM attribute is 'artifact_metadata' but the DB column is 'metadata'
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_artifacts_project", "artifacts", ["project_id"])
    op.create_index("idx_artifacts_run", "artifacts", ["run_id"])

    # ── llm_calls ──────────────────────────────────────────────────────────────
    op.create_table(
        "llm_calls",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_steps.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column(
            "prompt_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "completion_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cost_usd",
            sa.Numeric(12, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_llm_calls_step", "llm_calls", ["step_id"])


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_index("idx_llm_calls_step", table_name="llm_calls")
    op.drop_table("llm_calls")

    op.drop_index("idx_artifacts_run", table_name="artifacts")
    op.drop_index("idx_artifacts_project", table_name="artifacts")
    op.drop_table("artifacts")

    op.drop_index("idx_steps_sequence", table_name="agent_steps")
    op.drop_index("idx_steps_run", table_name="agent_steps")
    op.drop_table("agent_steps")

    op.drop_index("idx_runs_status", table_name="agent_runs")
    op.drop_index("idx_runs_project", table_name="agent_runs")
    op.drop_table("agent_runs")

    op.drop_index("idx_projects_status", table_name="projects")
    op.drop_index("idx_projects_owner", table_name="projects")
    op.drop_table("projects")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
