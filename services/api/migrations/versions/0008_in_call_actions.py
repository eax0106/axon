"""in-call actions

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "google_connections",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("scopes", sa.ARRAY(sa.String(length=200)), server_default="{}", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_google_connections_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("account_id", name=op.f("pk_google_connections")),
    )


def downgrade() -> None:
    op.drop_table("google_connections")
