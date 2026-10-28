"""reliability and admin

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_balances",
        sa.Column("vendor", sa.String(length=50), nullable=False),
        sa.Column("balance_inr", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alert_below_inr", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.PrimaryKeyConstraint("vendor", name=op.f("pk_provider_balances")),
    )
    op.create_table(
        "provider_outcomes",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("vendor", sa.String(length=50), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_outcomes")),
    )
    op.create_index("ix_provider_outcomes_at", "provider_outcomes", ["at"], unique=False)
    op.create_table(
        "provider_rates",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("vendor", sa.String(length=50), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("inr_per_unit", sa.Numeric(precision=16, scale=8), nullable=False),
        sa.PrimaryKeyConstraint("kind", "vendor", "unit", name=op.f("pk_provider_rates")),
    )
    op.create_table(
        "support_messages",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("from_staff", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("call_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name=op.f("ck_support_messages_rating_range")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_support_messages_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name=op.f("fk_support_messages_call_id_calls"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_support_messages_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_messages")),
    )
    op.create_index(
        "ix_support_messages_account_created",
        "support_messages",
        ["account_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_messages_account_id"), "support_messages", ["account_id"], unique=False
    )
    op.add_column(
        "accounts", sa.Column("max_call_s", sa.Integer(), server_default="600", nullable=False)
    )
    op.create_check_constraint(
        op.f("ck_accounts_max_call_s_range"), "accounts", "max_call_s BETWEEN 10 AND 3600"
    )
    op.add_column(
        "calls", sa.Column("analysis_attempts", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "calls", sa.Column("analysis_retry_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("tokens_valid_after", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "tokens_valid_after")
    op.drop_column("calls", "analysis_retry_at")
    op.drop_column("calls", "analysis_attempts")
    op.drop_constraint(op.f("ck_accounts_max_call_s_range"), "accounts", type_="check")
    op.drop_column("accounts", "max_call_s")
    op.drop_index(op.f("ix_support_messages_account_id"), table_name="support_messages")
    op.drop_index("ix_support_messages_account_created", table_name="support_messages")
    op.drop_table("support_messages")
    op.drop_table("provider_rates")
    op.drop_index("ix_provider_outcomes_at", table_name="provider_outcomes")
    op.drop_table("provider_outcomes")
    op.drop_table("provider_balances")
