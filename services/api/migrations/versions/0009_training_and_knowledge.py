"""training and knowledge

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_docs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("chars", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_knowledge_docs_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_knowledge_docs_employee_id_employees"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_docs")),
    )
    op.create_index(
        op.f("ix_knowledge_docs_account_id"), "knowledge_docs", ["account_id"], unique=False
    )
    op.create_index(
        op.f("ix_knowledge_docs_employee_id"), "knowledge_docs", ["employee_id"], unique=False
    )
    op.create_table(
        "knowledge_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "fact",
                "rule",
                name="knowledge_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("text", sa.String(length=300), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_knowledge_items_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_knowledge_items_employee_id_employees"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_items")),
    )
    op.create_index(
        op.f("ix_knowledge_items_account_id"), "knowledge_items", ["account_id"], unique=False
    )
    op.create_index(
        op.f("ix_knowledge_items_employee_id"), "knowledge_items", ["employee_id"], unique=False
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("doc_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.ARRAY(sa.REAL()), nullable=False),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["knowledge_docs.id"],
            name=op.f("fk_knowledge_chunks_doc_id_knowledge_docs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_knowledge_chunks_employee_id_employees"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_chunks")),
    )
    op.create_index(
        op.f("ix_knowledge_chunks_doc_id"), "knowledge_chunks", ["doc_id"], unique=False
    )
    op.create_index(
        op.f("ix_knowledge_chunks_employee_id"), "knowledge_chunks", ["employee_id"], unique=False
    )
    op.create_table(
        "training_suggestions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "fact",
                "rule",
                name="suggestion_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("caller_quote", sa.String(length=200), nullable=False),
        sa.Column("agent_quote", sa.String(length=200), nullable=True),
        sa.Column("text", sa.String(length=300), server_default="", nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "accepted",
                "dismissed",
                name="suggestion_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_training_suggestions_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name=op.f("fk_training_suggestions_call_id_calls"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_training_suggestions_employee_id_employees"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_training_suggestions")),
    )
    op.create_index(
        op.f("ix_training_suggestions_account_id"),
        "training_suggestions",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_training_suggestions_employee_id"),
        "training_suggestions",
        ["employee_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_training_suggestions_employee_id"), table_name="training_suggestions")
    op.drop_index(op.f("ix_training_suggestions_account_id"), table_name="training_suggestions")
    op.drop_table("training_suggestions")
    op.drop_index(op.f("ix_knowledge_chunks_employee_id"), table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_doc_id"), table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_items_employee_id"), table_name="knowledge_items")
    op.drop_index(op.f("ix_knowledge_items_account_id"), table_name="knowledge_items")
    op.drop_table("knowledge_items")
    op.drop_index(op.f("ix_knowledge_docs_employee_id"), table_name="knowledge_docs")
    op.drop_index(op.f("ix_knowledge_docs_account_id"), table_name="knowledge_docs")
    op.drop_table("knowledge_docs")
