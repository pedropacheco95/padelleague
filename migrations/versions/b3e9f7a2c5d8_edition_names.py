"""Edition names: one running edition number across every format

Revision ID: b3e9f7a2c5d8
Revises: a8d4e2f6c1b7
Create Date: 2026-10-15 16:00:00.000000

Pedro (2026-10-15): the edition number keeps counting whatever the format
(the Shuffle was already the 20ª). The 22ª gets its name, and Teams 2026/27 is
the 23ª. New competitions take the next number (services.editions).
"""

from alembic import op

revision = "b3e9f7a2c5d8"
down_revision = "a8d4e2f6c1b7"
branch_labels = None
depends_on = None

RENAMES = {
    25: ("22ª Edição", "22ª Edição Masters de Outono"),
    27: ("PPL Teams 2026/27", "23ª Edição Teams 2026/27"),
}


def upgrade():
    for cid, (old, new) in RENAMES.items():
        op.execute(
            f"""
            DO $$
            BEGIN
                IF (SELECT name FROM competitions WHERE id = {cid}) IS DISTINCT FROM '{old}' THEN
                    RAISE EXCEPTION 'competition {cid} is not named {old}';
                END IF;
            END $$;
            UPDATE competitions SET name = '{new}' WHERE id = {cid};
            """
        )


def downgrade():
    for cid, (old, new) in RENAMES.items():
        op.execute(f"UPDATE competitions SET name = '{old}' WHERE id = {cid}")
