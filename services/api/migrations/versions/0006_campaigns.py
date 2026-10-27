"""campaigns

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contact_lists",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_contact_lists_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_lists")),
        sa.UniqueConstraint("account_id", "name", name=op.f("uq_contact_lists_account_id_name")),
    )
    op.create_index(
        op.f("ix_contact_lists_account_id"), "contact_lists", ["account_id"], unique=False
    )
    op.create_table(
        "contact_list_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("list_id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column(
            "variables",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["contact_lists.id"],
            name=op.f("fk_contact_list_items_list_id_contact_lists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_list_items")),
        sa.UniqueConstraint("list_id", "phone", name=op.f("uq_contact_list_items_list_id_phone")),
    )
    op.create_index(
        op.f("ix_contact_list_items_list_id"), "contact_list_items", ["list_id"], unique=False
    )
    op.create_table(
        "campaign_exclusions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_campaign_exclusions_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaign_exclusions")),
        sa.UniqueConstraint(
            "campaign_id", "phone", name=op.f("uq_campaign_exclusions_campaign_id_phone")
        ),
    )
    op.create_index(
        op.f("ix_campaign_exclusions_campaign_id"),
        "campaign_exclusions",
        ["campaign_id"],
        unique=False,
    )
    op.add_column("calls", sa.Column("contact_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_calls_contact_id"), "calls", ["contact_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_calls_contact_id_campaign_contacts"),
        "calls",
        "campaign_contacts",
        ["contact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("campaign_contacts", sa.Column("name", sa.String(length=200), nullable=True))
    op.add_column(
        "campaign_contacts",
        sa.Column("priority", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "campaign_contacts", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("campaign_contacts", sa.Column("reason", sa.String(length=300), nullable=True))
    op.add_column(
        "campaign_contacts",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_campaign_contacts_due",
        "campaign_contacts",
        ["campaign_id", "status", "next_attempt_at"],
        unique=False,
    )
    op.add_column("campaigns", sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaigns", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaigns", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaigns", sa.Column("note", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("campaigns", "note")
    op.drop_column("campaigns", "completed_at")
    op.drop_column("campaigns", "started_at")
    op.drop_column("campaigns", "scheduled_at")
    op.drop_index("ix_campaign_contacts_due", table_name="campaign_contacts")
    op.drop_column("campaign_contacts", "created_at")
    op.drop_column("campaign_contacts", "reason")
    op.drop_column("campaign_contacts", "next_attempt_at")
    op.drop_column("campaign_contacts", "priority")
    op.drop_column("campaign_contacts", "name")
    op.drop_constraint(op.f("fk_calls_contact_id_campaign_contacts"), "calls", type_="foreignkey")
    op.drop_index(op.f("ix_calls_contact_id"), table_name="calls")
    op.drop_column("calls", "contact_id")
    op.drop_index(op.f("ix_campaign_exclusions_campaign_id"), table_name="campaign_exclusions")
    op.drop_table("campaign_exclusions")
    op.drop_index(op.f("ix_contact_list_items_list_id"), table_name="contact_list_items")
    op.drop_table("contact_list_items")
    op.drop_index(op.f("ix_contact_lists_account_id"), table_name="contact_lists")
    op.drop_table("contact_lists")
