"""Teams pairs can stay together from the previous mini-tournament (Pedro, 2026-11-05)

Revision ID: a3f7c1d9e2b4
Revises: d7b2e5f8a3c6
Create Date: 2026-11-05 19:00:00.000000
"""

from alembic import op

revision = "a3f7c1d9e2b4"
down_revision = "d7b2e5f8a3c6"
branch_labels = None
depends_on = None


def _allow(values):
    op.execute("ALTER TABLE pairs DROP CONSTRAINT pairs_formed_by_check")
    op.execute(f"ALTER TABLE pairs ADD CONSTRAINT pairs_formed_by_check CHECK (formed_by IN ({values}))")


def upgrade():
    _allow("'mutual', 'ranking', 'draw', 'rotation', 'manual', 'previous'")


def downgrade():
    op.execute("UPDATE pairs SET formed_by = 'ranking' WHERE formed_by = 'previous'")
    _allow("'mutual', 'ranking', 'draw', 'rotation', 'manual'")
