"""initial schema

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("business_name", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
    )
    op.create_table(
        "voices",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_voice_id", sa.String(length=200), nullable=False),
        sa.Column(
            "tier",
            sa.Enum(
                "value",
                "standard",
                "premium",
                name="voice_tier",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("public_name", sa.String(length=100), nullable=False),
        sa.Column("native_language", sa.String(length=10), nullable=False),
        sa.Column("accent", sa.String(length=50), nullable=True),
        sa.Column("tone_tags", sa.ARRAY(sa.String(length=50)), server_default="{}", nullable=False),
        sa.Column(
            "language_scores",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_voices")),
        sa.UniqueConstraint(
            "provider", "provider_voice_id", name=op.f("uq_voices_provider_provider_voice_id")
        ),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_api_keys_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_api_keys_key_hash")),
    )
    op.create_index(op.f("ix_api_keys_account_id"), "api_keys", ["account_id"], unique=False)
    op.create_table(
        "dnc_entries",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "manual",
                "bulk",
                "caller_request",
                name="dnc_source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_dnc_entries_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dnc_entries")),
        sa.UniqueConstraint("account_id", "phone", name=op.f("uq_dnc_entries_account_id_phone")),
    )
    op.create_index(op.f("ix_dnc_entries_account_id"), "dnc_entries", ["account_id"], unique=False)
    op.create_table(
        "leads",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column(
            "fields", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
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
            name=op.f("fk_leads_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leads")),
        sa.UniqueConstraint("account_id", "phone", name=op.f("uq_leads_account_id_phone")),
    )
    op.create_index(op.f("ix_leads_account_id"), "leads", ["account_id"], unique=False)
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_notifications_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(
        op.f("ix_notifications_account_id"), "notifications", ["account_id"], unique=False
    )
    op.create_table(
        "numbers",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("e164", sa.String(length=20), nullable=False),
        sa.Column(
            "number_type",
            sa.Enum(
                "regular",
                "140",
                "1600",
                name="number_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("channels", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "grace",
                "released",
                name="number_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("renews_on", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("channels >= 1", name=op.f("ck_numbers_channels_positive")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_numbers_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_numbers")),
        sa.UniqueConstraint("e164", name=op.f("uq_numbers_e164")),
    )
    op.create_index(op.f("ix_numbers_account_id"), "numbers", ["account_id"], unique=False)
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_order_id", sa.String(length=100), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=100), nullable=True),
        sa.Column("amount_inr", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "created",
                "paid",
                "failed",
                name="payment_status",
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
            name=op.f("fk_payments_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("provider_order_id", name=op.f("uq_payments_provider_order_id")),
    )
    op.create_index(op.f("ix_payments_account_id"), "payments", ["account_id"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "owner",
                "member",
                "admin",
                name="user_role",
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
            name=op.f("fk_users_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_account_id"), "users", ["account_id"], unique=False)
    op.create_index(
        "uq_users_email_lower", "users", [sa.literal_column("lower(email)")], unique=True
    )
    op.create_table(
        "wallet_ledger",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "topup",
                "call",
                "number",
                "refund",
                "bonus",
                "adjustment",
                name="ledger_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("balance_after", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("ref_type", sa.String(length=50), nullable=True),
        sa.Column("ref_id", sa.String(length=100), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_wallet_ledger_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wallet_ledger")),
    )
    op.create_index(
        op.f("ix_wallet_ledger_account_id"), "wallet_ledger", ["account_id"], unique=False
    )
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("secret", sa.String(length=100), nullable=False),
        sa.Column("events", sa.ARRAY(sa.String(length=50)), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_webhook_endpoints_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_endpoints")),
    )
    op.create_index(
        op.f("ix_webhook_endpoints_account_id"), "webhook_endpoints", ["account_id"], unique=False
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("impersonator_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=True),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column(
            "data", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
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
            name=op.f("fk_audit_log_account_id_accounts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_log_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["impersonator_user_id"],
            ["users.id"],
            name=op.f("fk_audit_log_impersonator_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_account_id"), "audit_log", ["account_id"], unique=False)
    op.create_table(
        "consent_attestations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "scope",
            sa.Enum(
                "campaign",
                "lead_source",
                name="consent_scope",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_consent_attestations_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_consent_attestations_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_attestations")),
    )
    op.create_index(
        op.f("ix_consent_attestations_account_id"),
        "consent_attestations",
        ["account_id"],
        unique=False,
    )
    op.create_table(
        "employees",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("role_title", sa.String(length=200), nullable=True),
        sa.Column(
            "channel",
            sa.Enum(
                "instant",
                "bulk",
                "inbound",
                name="channel",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "purpose",
            sa.Enum(
                "promotional",
                "service",
                "transactional",
                name="purpose",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "training",
                "live",
                "paused",
                name="employee_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column(
            "extra_languages", sa.ARRAY(sa.String(length=10)), server_default="{}", nullable=False
        ),
        sa.Column("voice_id", sa.Uuid(), nullable=True),
        sa.Column("number_id", sa.Uuid(), nullable=True),
        sa.Column(
            "draft", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_employees_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["number_id"],
            ["numbers.id"],
            name=op.f("fk_employees_number_id_numbers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["voices.id"],
            name=op.f("fk_employees_voice_id_voices"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employees")),
        sa.UniqueConstraint("number_id", name=op.f("uq_employees_number_id")),
    )
    op.create_index(op.f("ix_employees_account_id"), "employees", ["account_id"], unique=False)
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("event", sa.String(length=50), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "delivered",
                "failed",
                name="delivery_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["webhook_endpoints.id"],
            name=op.f("fk_webhook_deliveries_endpoint_id_webhook_endpoints"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
    )
    op.create_index(
        op.f("ix_webhook_deliveries_endpoint_id"),
        "webhook_deliveries",
        ["endpoint_id"],
        unique=False,
    )
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "scheduled",
                "running",
                "paused",
                "completed",
                "canceled",
                name="campaign_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "settings", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
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
            name=op.f("fk_campaigns_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_campaigns_employee_id_employees"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaigns")),
    )
    op.create_index(op.f("ix_campaigns_account_id"), "campaigns", ["account_id"], unique=False)
    op.create_table(
        "employee_versions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("bundle", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_employee_versions_employee_id_employees"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employee_versions")),
        sa.UniqueConstraint(
            "employee_id", "version", name=op.f("uq_employee_versions_employee_id_version")
        ),
    )
    op.create_index(
        op.f("ix_employee_versions_employee_id"), "employee_versions", ["employee_id"], unique=False
    )
    op.create_table(
        "calls",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("number_id", sa.Uuid(), nullable=True),
        sa.Column(
            "direction",
            sa.Enum(
                "inbound",
                "outbound",
                name="direction",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "channel",
            sa.Enum(
                "instant",
                "bulk",
                "inbound",
                name="channel",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "ringing",
                "in_progress",
                "completed",
                "no_answer",
                "busy",
                "failed",
                "canceled",
                name="call_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column(
            "credits_charged", sa.Numeric(precision=14, scale=4), server_default="0", nullable=False
        ),
        sa.Column("outcome", sa.String(length=50), nullable=True),
        sa.Column("sentiment", sa.String(length=20), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "transcript",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "captured", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("recording_key", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_calls_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_calls_campaign_id_campaigns"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_calls_employee_id_employees"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"], name=op.f("fk_calls_lead_id_leads"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["number_id"],
            ["numbers.id"],
            name=op.f("fk_calls_number_id_numbers"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calls")),
    )
    op.create_index(op.f("ix_calls_account_id"), "calls", ["account_id"], unique=False)
    op.create_index(op.f("ix_calls_campaign_id"), "calls", ["campaign_id"], unique=False)
    op.create_index(op.f("ix_calls_employee_id"), "calls", ["employee_id"], unique=False)
    op.create_index(op.f("ix_calls_lead_id"), "calls", ["lead_id"], unique=False)
    op.create_table(
        "campaign_contacts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column(
            "variables",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "calling",
                "callback",
                "done",
                "exhausted",
                "skipped",
                "canceled",
                name="contact_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_campaign_contacts_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaign_contacts")),
        sa.UniqueConstraint(
            "campaign_id", "phone", name=op.f("uq_campaign_contacts_campaign_id_phone")
        ),
    )
    op.create_index(
        op.f("ix_campaign_contacts_campaign_id"), "campaign_contacts", ["campaign_id"], unique=False
    )
    op.create_table(
        "call_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column(
            "data", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["call_id"], ["calls.id"], name=op.f("fk_call_events_call_id_calls"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_events")),
    )
    op.create_index(op.f("ix_call_events_call_id"), "call_events", ["call_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_call_events_call_id"), table_name="call_events")
    op.drop_table("call_events")
    op.drop_index(op.f("ix_campaign_contacts_campaign_id"), table_name="campaign_contacts")
    op.drop_table("campaign_contacts")
    op.drop_index(op.f("ix_calls_lead_id"), table_name="calls")
    op.drop_index(op.f("ix_calls_employee_id"), table_name="calls")
    op.drop_index(op.f("ix_calls_campaign_id"), table_name="calls")
    op.drop_index(op.f("ix_calls_account_id"), table_name="calls")
    op.drop_table("calls")
    op.drop_index(op.f("ix_employee_versions_employee_id"), table_name="employee_versions")
    op.drop_table("employee_versions")
    op.drop_index(op.f("ix_campaigns_account_id"), table_name="campaigns")
    op.drop_table("campaigns")
    op.drop_index(op.f("ix_webhook_deliveries_endpoint_id"), table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_index(op.f("ix_employees_account_id"), table_name="employees")
    op.drop_table("employees")
    op.drop_index(op.f("ix_consent_attestations_account_id"), table_name="consent_attestations")
    op.drop_table("consent_attestations")
    op.drop_index(op.f("ix_audit_log_account_id"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index(op.f("ix_webhook_endpoints_account_id"), table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")
    op.drop_index(op.f("ix_wallet_ledger_account_id"), table_name="wallet_ledger")
    op.drop_table("wallet_ledger")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_index(op.f("ix_users_account_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_payments_account_id"), table_name="payments")
    op.drop_table("payments")
    op.drop_index(op.f("ix_numbers_account_id"), table_name="numbers")
    op.drop_table("numbers")
    op.drop_index(op.f("ix_notifications_account_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_leads_account_id"), table_name="leads")
    op.drop_table("leads")
    op.drop_index(op.f("ix_dnc_entries_account_id"), table_name="dnc_entries")
    op.drop_table("dnc_entries")
    op.drop_index(op.f("ix_api_keys_account_id"), table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("voices")
    op.drop_table("accounts")
