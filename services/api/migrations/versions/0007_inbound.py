"""inbound

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_summaries",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_daily_summaries_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("account_id", "day", name=op.f("pk_daily_summaries")),
    )
    op.create_table(
        "inbound_messages",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("callback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_inbound_messages_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name=op.f("fk_inbound_messages_call_id_calls"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["done_by"],
            ["users.id"],
            name=op.f("fk_inbound_messages_done_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_inbound_messages_employee_id_employees"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_inbound_messages_lead_id_leads"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbound_messages")),
        sa.UniqueConstraint("call_id", name=op.f("uq_inbound_messages_call_id")),
    )
    op.create_index(
        op.f("ix_inbound_messages_account_id"), "inbound_messages", ["account_id"], unique=False
    )
    op.create_index(
        "ix_inbound_messages_account_open",
        "inbound_messages",
        ["account_id", "done_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inbound_messages_employee_id"), "inbound_messages", ["employee_id"], unique=False
    )
    op.add_column("calls", sa.Column("miss_reason", sa.String(length=200), nullable=True))
    op.add_column("calls", sa.Column("caller_phone", sa.String(length=20), nullable=True))
    op.add_column("calls", sa.Column("callback_of_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_calls_callback_of_id"), "calls", ["callback_of_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_calls_callback_of_id_calls"),
        "calls",
        "calls",
        ["callback_of_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "employees",
        sa.Column(
            "inbound", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("employees", "inbound")
    op.drop_constraint(op.f("fk_calls_callback_of_id_calls"), "calls", type_="foreignkey")
    op.drop_index(op.f("ix_calls_callback_of_id"), table_name="calls")
    op.drop_column("calls", "callback_of_id")
    op.drop_column("calls", "caller_phone")
    op.drop_column("calls", "miss_reason")
    op.drop_index(op.f("ix_inbound_messages_employee_id"), table_name="inbound_messages")
    op.drop_index("ix_inbound_messages_account_open", table_name="inbound_messages")
    op.drop_index(op.f("ix_inbound_messages_account_id"), table_name="inbound_messages")
    op.drop_table("inbound_messages")
    op.drop_table("daily_summaries")
