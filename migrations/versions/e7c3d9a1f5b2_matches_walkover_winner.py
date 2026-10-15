"""matches.walkover_winner: which side won a walkover

Revision ID: e7c3d9a1f5b2
Revises: d5a2b8c6e1f4
Create Date: 2026-10-15 20:00:00.000000

A walkover stores no sets (Teams: the present pair takes 3-0). Historic
walkovers keep a null winner; their games already carry the result.
"""

from alembic import op
import sqlalchemy as sa

revision = "e7c3d9a1f5b2"
down_revision = "d5a2b8c6e1f4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("matches", sa.Column("walkover_winner", sa.Text(), nullable=True))
    op.create_check_constraint(
        "matches_walkover_winner_check",
        "matches",
        "walkover_winner IS NULL OR (walkover_winner IN ('home', 'away') AND status = 'walkover')",
    )


def downgrade():
    op.drop_constraint("matches_walkover_winner_check", "matches")
    op.drop_column("matches", "walkover_winner")
