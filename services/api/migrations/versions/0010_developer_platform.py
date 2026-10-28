"""developer platform

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nothing ever wrote to webhook_deliveries before this phase; the new NOT NULL columns need it
    # empty.
    op.execute("DELETE FROM webhook_deliveries")
    op.create_table(
        "api_request_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("key_id", sa.Uuid(), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=300), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_api_request_log_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["key_id"],
            ["api_keys.id"],
            name=op.f("fk_api_request_log_key_id_api_keys"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_request_log")),
    )
    op.create_index(
        "ix_api_request_log_account_created",
        "api_request_log",
        ["account_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_api_request_log_account_id"), "api_request_log", ["account_id"], unique=False
    )
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("fanned_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_webhook_events_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_webhook_events_employee_id_employees"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_events")),
    )
    op.create_index(
        op.f("ix_webhook_events_account_id"), "webhook_events", ["account_id"], unique=False
    )
    op.create_index(
        "ix_webhook_events_unsent",
        "webhook_events",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("fanned_out_at IS NULL"),
    )
    op.add_column(
        "calls", sa.Column("voicemail", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column(
        "calls", sa.Column("events_emitted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_calls_unannounced",
        "calls",
        ["ended_at"],
        unique=False,
        postgresql_where=sa.text(
            "events_emitted_at IS NULL AND ended_at IS NOT NULL AND NOT is_test"
            " AND status IN ('completed', 'no_answer', 'busy', 'failed')"
        ),
    )
    # Calls that ended before webhooks existed are history, not news.
    op.execute("UPDATE calls SET events_emitted_at = now() WHERE ended_at IS NOT NULL")
    op.add_column("webhook_deliveries", sa.Column("account_id", sa.Uuid(), nullable=False))
    op.add_column("webhook_deliveries", sa.Column("event_id", sa.Uuid(), nullable=False))
    op.add_column("webhook_deliveries", sa.Column("employee_id", sa.Uuid(), nullable=True))
    op.add_column(
        "webhook_deliveries", sa.Column("target_url", sa.String(length=2000), nullable=False)
    )
    op.add_column(
        "webhook_deliveries", sa.Column("target_secret", sa.String(length=500), nullable=True)
    )
    op.add_column(
        "webhook_deliveries",
        sa.Column("is_test", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "webhook_deliveries", sa.Column("last_error", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "webhook_deliveries",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("webhook_deliveries", "endpoint_id", existing_type=sa.UUID(), nullable=True)
    op.create_index(
        "ix_webhook_deliveries_account_created",
        "webhook_deliveries",
        ["account_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_webhook_deliveries_account_id"), "webhook_deliveries", ["account_id"], unique=False
    )
    op.create_index(
        "ix_webhook_deliveries_due",
        "webhook_deliveries",
        ["next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        op.f("ix_webhook_deliveries_event_id"), "webhook_deliveries", ["event_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_webhook_deliveries_account_id_accounts"),
        "webhook_deliveries",
        "accounts",
        ["account_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_webhook_deliveries_employee_id_employees"),
        "webhook_deliveries",
        "employees",
        ["employee_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_webhook_deliveries_event_id_webhook_events"),
        "webhook_deliveries",
        "webhook_events",
        ["event_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.add_column(
        "webhook_endpoints",
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "webhook_endpoints", sa.Column("description", sa.String(length=200), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("webhook_endpoints", "description")
    op.drop_column("webhook_endpoints", "active")
    op.drop_constraint(
        op.f("fk_webhook_deliveries_event_id_webhook_events"),
        "webhook_deliveries",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_webhook_deliveries_employee_id_employees"),
        "webhook_deliveries",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_webhook_deliveries_account_id_accounts"), "webhook_deliveries", type_="foreignkey"
    )
    op.drop_index(op.f("ix_webhook_deliveries_event_id"), table_name="webhook_deliveries")
    op.drop_index(
        "ix_webhook_deliveries_due",
        table_name="webhook_deliveries",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index(op.f("ix_webhook_deliveries_account_id"), table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_account_created", table_name="webhook_deliveries")
    op.alter_column("webhook_deliveries", "endpoint_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("webhook_deliveries", "next_attempt_at")
    op.drop_column("webhook_deliveries", "last_error")
    op.drop_column("webhook_deliveries", "is_test")
    op.drop_column("webhook_deliveries", "target_secret")
    op.drop_column("webhook_deliveries", "target_url")
    op.drop_column("webhook_deliveries", "employee_id")
    op.drop_column("webhook_deliveries", "event_id")
    op.drop_column("webhook_deliveries", "account_id")
    op.drop_index(
        "ix_calls_unannounced",
        table_name="calls",
        postgresql_where=sa.text(
            "events_emitted_at IS NULL AND ended_at IS NOT NULL AND NOT is_test"
            " AND status IN ('completed', 'no_answer', 'busy', 'failed')"
        ),
    )
    op.drop_column("calls", "events_emitted_at")
    op.drop_column("calls", "voicemail")
    op.drop_index(
        "ix_webhook_events_unsent",
        table_name="webhook_events",
        postgresql_where=sa.text("fanned_out_at IS NULL"),
    )
    op.drop_index(op.f("ix_webhook_events_account_id"), table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_index(op.f("ix_api_request_log_account_id"), table_name="api_request_log")
    op.drop_index("ix_api_request_log_account_created", table_name="api_request_log")
    op.drop_table("api_request_log")
