"""v2 core data model

Archives every table to schema `legacy`, creates the v2 competition tables,
copies all data across (keeping public ids), and exposes the old table shapes
as views in schema `compat`. See docs/v2/PLAN.md and migrations/sql/.

Revision ID: b7d2e4c1a9f0
Revises: a1d5c0e7b3f2
Create Date: 2026-10-14
"""

from pathlib import Path

from alembic import op

revision = "b7d2e4c1a9f0"
down_revision = "a1d5c0e7b3f2"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def upgrade():
    # Run on the raw DBAPI cursor: the scripts contain format() placeholders
    # (%I) and casts that must not go through bind-parameter processing.
    cursor = op.get_bind().connection.cursor()
    for name in ("v2_core.sql", "v2_compat.sql"):
        cursor.execute((SQL_DIR / name).read_text())


def downgrade():
    # The pre-v2 tables are preserved untouched in schema `legacy`, and a full
    # backup is taken before deploying. Restoring is a deliberate manual step.
    raise RuntimeError(
        "v2 is not reversible by Alembic. Restore the pre-migration backup, "
        "or copy the tables back from schema `legacy`."
    )
