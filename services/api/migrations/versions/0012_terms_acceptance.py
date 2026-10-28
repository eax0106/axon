"""terms acceptance

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("terms_version", sa.String(length=40), nullable=True))
    op.add_column(
        "accounts", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("accounts", "terms_accepted_at")
    op.drop_column("accounts", "terms_version")
