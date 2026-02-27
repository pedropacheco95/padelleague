"""add shuffle position

Revision ID: b4bb8fdef380
Revises: e1b22811c87e
Create Date: 2026-02-27 09:03:40.999499

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b4bb8fdef380"
down_revision = "e1b22811c87e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "players_in_shuffle_tournament",
        sa.Column("position", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("players_in_shuffle_tournament", "position")
