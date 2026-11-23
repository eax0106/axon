"""index consent attestations by subject

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_consent_attestations_subject_id"),
        "consent_attestations",
        ["subject_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_consent_attestations_subject_id"), table_name="consent_attestations")
