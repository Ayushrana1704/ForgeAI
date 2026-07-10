"""Update projects.status server_default from 'pending' to 'draft'

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-07-09 00:00:00.000000

Background
----------
The ProjectStatus enum was renamed to match domain semantics:
  PENDING  → DRAFT      (project exists, no agent run started)
  RUNNING  → GENERATING (agents are active)
  (new)      REVIEWING  (generation done, awaiting human review)
  COMPLETED / FAILED unchanged

There is no production data to migrate.  The only change is the
DB-level server_default so fresh INSERTs that omit the status column
receive 'draft' rather than 'pending'.

The application always supplies an explicit status value via the ORM,
so this server_default is a safety net rather than the primary path.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a1"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "projects",
        "status",
        server_default=sa.text("'draft'"),
        existing_type=sa.String(50),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "projects",
        "status",
        server_default=sa.text("'pending'"),
        existing_type=sa.String(50),
        existing_nullable=False,
    )
