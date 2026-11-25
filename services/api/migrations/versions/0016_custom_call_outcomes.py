"""custom call outcomes

Revision ID: 0016
Revises: 0014

Numbered 0016 because open PR #49 adds 0015. If #49 merges first, set down_revision to "0015".
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("custom_outcome", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("calls", "custom_outcome")
