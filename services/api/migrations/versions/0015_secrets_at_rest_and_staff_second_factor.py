"""encrypt stored secrets (AXON_SECRETS_KEY) and add the staff second factor

Revision ID: 0015
Revises: 0014

Every stored secret is rewritten encrypted, so the key must be set before this runs on a database
that holds any (it fails saying what to set). The downgrade writes them back in the clear and
drops the second factor: staff then sign in with their password alone.
"""

from collections.abc import Callable, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from app.secretbox import box

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, primary key, column) of every plain-text secret column; widened to text first where it
# was a short varchar, since the encrypted form is longer.
COLUMNS = [
    ("lead_connections", "id", "secret"),
    ("lead_connections", "id", "meta_page_token"),
    ("lead_connections", "id", "google_refresh_token"),
    ("google_connections", "account_id", "refresh_token"),
    ("webhook_endpoints", "id", "secret"),
    ("webhook_deliveries", "id", "target_secret"),
]
WIDENED = [
    ("lead_connections", "secret", 64, False),
    ("webhook_endpoints", "secret", 100, False),
    ("webhook_deliveries", "target_secret", 500, True),
]
BUNDLES = [("employees", "draft"), ("employee_versions", "bundle")]


def _bundle(bundle: dict[str, Any], change: Callable[[str], str]) -> dict[str, Any]:
    """app.secretbox.map_bundle_secrets as it was when this ran: an HTTP action's key and the
    result webhook's secret, frozen here so a later change cannot change what this did."""
    out = dict(bundle)
    if isinstance(out.get("actions"), list):
        out["actions"] = [
            {**a, "auth": {**a["auth"], "secret": change(a["auth"]["secret"])}}
            if isinstance(a, dict) and isinstance(a.get("auth"), dict) and a["auth"].get("secret")
            else a
            for a in out["actions"]
        ]
    hook = out.get("result_webhook")
    if isinstance(hook, dict) and hook.get("secret"):
        out["result_webhook"] = {**hook, "secret": change(hook["secret"])}
    return out


def _rewrite(change: Callable[[str], str]) -> None:
    bind = op.get_bind()
    for table, key, column in COLUMNS:
        rows = bind.execute(
            sa.text(f"SELECT {key}, {column} FROM {table} WHERE {column} IS NOT NULL")  # noqa: S608
        ).all()
        for row_key, value in rows:
            bind.execute(
                sa.text(f"UPDATE {table} SET {column} = :v WHERE {key} = :k"),  # noqa: S608
                {"v": change(value), "k": row_key},
            )
    for table, column in BUNDLES:
        rows = bind.execute(sa.text(f"SELECT id, {column} FROM {table}")).all()  # noqa: S608
        for row_id, bundle in rows:
            if not bundle:
                continue
            new = _bundle(bundle, change)
            if new != bundle:
                bind.execute(
                    sa.text(f"UPDATE {table} SET {column} = :v WHERE id = :k").bindparams(  # noqa: S608
                        sa.bindparam("v", type_=JSONB)
                    ),
                    {"v": new, "k": row_id},
                )


def _seal(value: str) -> str:
    return box().encrypt(value.encode()).decode()


def _unseal(value: str) -> str:
    return box().decrypt(value.encode()).decode()


def upgrade() -> None:
    for table, column, length, nullable in WIDENED:
        op.alter_column(
            table, column, existing_type=sa.String(length), type_=sa.Text(),
            existing_nullable=nullable,
        )  # fmt: skip
    op.add_column("users", sa.Column("totp_secret", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("totp_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "recovery_code_hashes",
            sa.ARRAY(sa.String(length=64)),
            server_default="{}",
            nullable=False,
        ),
    )
    _rewrite(_seal)


def downgrade() -> None:
    _rewrite(_unseal)
    op.drop_column("users", "recovery_code_hashes")
    op.drop_column("users", "totp_last_step")
    op.drop_column("users", "totp_enabled_at")
    op.drop_column("users", "totp_secret")
    for table, column, length, nullable in WIDENED:
        op.alter_column(
            table, column, existing_type=sa.Text(), type_=sa.String(length),
            existing_nullable=nullable,
        )  # fmt: skip
