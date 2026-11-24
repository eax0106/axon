"""prune and summary indexes, suggestion quote key

Revision ID: 0014
Revises: 0013
"""

import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _quote_key(text: str) -> str:
    """app.training.struggle.quote_key as it was when this ran, frozen here so a later change to
    the app cannot change what this migration did."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    spaced = "".join(" " if unicodedata.category(c)[0] in "PS" else c for c in folded)
    return " ".join(spaced.split())[:400]


def upgrade() -> None:
    op.create_index("ix_api_request_log_created", "api_request_log", ["created_at"], unique=False)
    op.create_index(
        "ix_calls_inbound_created",
        "calls",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("direction = 'inbound' AND NOT is_test"),
    )
    op.add_column(
        "training_suggestions", sa.Column("quote_key", sa.String(length=400), nullable=True)
    )
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, caller_quote FROM training_suggestions")).all()
    if rows:
        bind.execute(
            sa.text("UPDATE training_suggestions SET quote_key = :key WHERE id = :id"),
            [{"id": row.id, "key": _quote_key(row.caller_quote)} for row in rows],
        )
    op.alter_column("training_suggestions", "quote_key", nullable=False)
    op.create_index(
        "ix_training_suggestions_quote",
        "training_suggestions",
        ["employee_id", "quote_key"],
        unique=False,
    )
    op.create_index(
        "ix_webhook_events_sent",
        "webhook_events",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("fanned_out_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_events_sent",
        table_name="webhook_events",
        postgresql_where=sa.text("fanned_out_at IS NOT NULL"),
    )
    op.drop_index("ix_training_suggestions_quote", table_name="training_suggestions")
    op.drop_column("training_suggestions", "quote_key")
    op.drop_index(
        "ix_calls_inbound_created",
        table_name="calls",
        postgresql_where=sa.text("direction = 'inbound' AND NOT is_test"),
    )
    op.drop_index("ix_api_request_log_created", table_name="api_request_log")
