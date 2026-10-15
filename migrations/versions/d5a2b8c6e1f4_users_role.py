"""users.role: player | admin | super_admin

Revision ID: d5a2b8c6e1f4
Revises: c4f1a9e2b7d3
Create Date: 2026-10-15 19:00:00.000000

One column replaces the is_admin / super_admin pair for the v2 API. The two
booleans stay until /api/v1 and the editor are gone (phase 4); until then
role is derived from them here and kept in step by the User model.
"""

from alembic import op
import sqlalchemy as sa

revision = "d5a2b8c6e1f4"
down_revision = "c4f1a9e2b7d3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("role", sa.Text(), nullable=False, server_default="player"))
    op.create_check_constraint("users_role_check", "users", "role IN ('player', 'admin', 'super_admin')")
    op.execute(
        "UPDATE users SET role = CASE WHEN super_admin THEN 'super_admin' "
        "WHEN is_admin THEN 'admin' ELSE 'player' END"
    )


def downgrade():
    op.drop_constraint("users_role_check", "users")
    op.drop_column("users", "role")
