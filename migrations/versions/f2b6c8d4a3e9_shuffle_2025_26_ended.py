"""Shuffle 2025/26 (competition 26) is finished

Revision ID: f2b6c8d4a3e9
Revises: e7c3d9a1f5b2
Create Date: 2026-10-15 21:00:00.000000

All 10 jornadas are played, but the competition was stored as running with no
dates. Pedro (2026-10-15): it was played between the 19ª (ended 2026-02-17) and
the 21ª (started 2026-05-12). ends_on is an approximation inside that gap; it
only orders the Shuffle among completed competitions for the ranking window.
rules.has_ended stays as stored: the old Shuffle pages read it (parity).
"""

from alembic import op

revision = "f2b6c8d4a3e9"
down_revision = "e7c3d9a1f5b2"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF (SELECT status FROM competitions WHERE id = 26) IS DISTINCT FROM 'running' THEN
                RAISE EXCEPTION 'competition 26 is not the running Shuffle 2025/26 this fix expects';
            END IF;
        END $$;
        UPDATE competitions SET status = 'ended', ends_on = DATE '2026-05-05' WHERE id = 26;
        """
    )


def downgrade():
    op.execute("UPDATE competitions SET status = 'running', ends_on = NULL WHERE id = 26")
