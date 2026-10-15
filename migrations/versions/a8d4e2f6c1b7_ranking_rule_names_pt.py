"""Ranking rule names in Portuguese (shown on the ranking page)

Revision ID: a8d4e2f6c1b7
Revises: f2b6c8d4a3e9
Create Date: 2026-10-15 22:00:00.000000
"""

from alembic import op

revision = "a8d4e2f6c1b7"
down_revision = "f2b6c8d4a3e9"
branch_labels = None
depends_on = None

NAMES = {
    "legacy-last-4-by-id": ("Últimas 4 edições (regra até 2026)", "Last 4 editions by id (rule until 2026)"),
    "transitional-2026-27": ("Últimas 3 terminadas + a atual (2026/27)", "Last 3 completed + current (2026/27)"),
    "per-slot": ("Cada prova substitui a equivalente do ano anterior (a partir de 2027/28)", "Each event replaces its counterpart (from 2027/28)"),
}


def upgrade():
    for key, (pt, _) in NAMES.items():
        op.execute(f"UPDATE ranking_rules SET name = '{pt}' WHERE key = '{key}'")


def downgrade():
    for key, (_, en) in NAMES.items():
        op.execute(f"UPDATE ranking_rules SET name = '{en}' WHERE key = '{key}'")
