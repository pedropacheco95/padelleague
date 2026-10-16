"""Subs ranking uses the main ranking window (Pedro, 2026-10-16)

Revision ID: d7b2e5f8a3c6
Revises: c6a1d9e4b2f7
Create Date: 2026-10-16 14:00:00.000000
"""

from alembic import op

revision = "d7b2e5f8a3c6"
down_revision = "c6a1d9e4b2f7"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE ranking_rules SET options = options || '{\"subs_window\": \"ranking\"}'::jsonb "
        "WHERE key IN ('transitional-2026-27', 'per-slot')"
    )


def downgrade():
    op.execute("UPDATE ranking_rules SET options = options - 'subs_window'")
