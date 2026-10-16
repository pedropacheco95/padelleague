"""ranking_entries.source: where a line's points come from

Revision ID: c6a1d9e4b2f7
Revises: b3e9f7a2c5d8
Create Date: 2026-10-16 12:00:00.000000

'awards' (the normal case) or 'subs' (Art. 12: a new player with no awards in
the window starts with his substitute points).
"""

from alembic import op
import sqlalchemy as sa

revision = "c6a1d9e4b2f7"
down_revision = "b3e9f7a2c5d8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ranking_entries", sa.Column("source", sa.Text(), nullable=False, server_default="awards"))
    op.create_check_constraint("ranking_entries_source_check", "ranking_entries", "source IN ('awards', 'subs')")


def downgrade():
    op.drop_constraint("ranking_entries_source_check", "ranking_entries")
    op.drop_column("ranking_entries", "source")
