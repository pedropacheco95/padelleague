"""PPL Teams pair formation; admin limited to the super admins

Revision ID: a1d5c0e7b3f2
Revises: 9c2f1a7d4e21
Create Date: 2026-10-15 15:00:00.000000

- Teams tables: roster, mini-tournaments, partner requests, pairs.
- Roster seeded with the players of the latest edition (Clássica I 2026/27);
  the admin endpoint PUT /api/v1/teams/roster changes it.
- Mini-tournament 1: choices close Sunday 18 Oct 2026, 23:59 Lisbon (22:59 UTC).
- Only the super admins keep is_admin. Every signed-in player can still enter
  results; is_admin now means the editor and competition set-up only.
  The downgrade cannot restore the old flags: restore them from the backup.
"""

from alembic import op
import sqlalchemy as sa

revision = "a1d5c0e7b3f2"
down_revision = "9c2f1a7d4e21"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "teams_players",
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "teams_mini_tournaments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("number", sa.Integer(), nullable=False, unique=True),
        sa.Column("pairing_deadline", sa.DateTime(), nullable=False),
        sa.Column("pairing_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "teams_partner_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mini_tournament_id", sa.Integer(), sa.ForeignKey("teams_mini_tournaments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("partner_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("mini_tournament_id", "player_id"),
        sa.CheckConstraint("player_id <> partner_id"),
    )
    op.create_table(
        "teams_pairs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mini_tournament_id", sa.Integer(), sa.ForeignKey("teams_mini_tournaments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_a_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_b_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("mini_tournament_id", "player_a_id"),
        sa.UniqueConstraint("mini_tournament_id", "player_b_id"),
        sa.CheckConstraint("player_a_id < player_b_id"),
    )
    op.execute(
        """
        INSERT INTO teams_players (player_id)
        SELECT DISTINCT pd.player_id
        FROM players_in_division pd
        JOIN divisions d ON d.id = pd.division_id
        WHERE d.edition_id = (SELECT max(id) FROM editions)
        """
    )
    op.execute(
        "INSERT INTO teams_mini_tournaments (number, pairing_deadline, pairing_closed) "
        "VALUES (1, '2026-10-18 22:59:59', false)"
    )
    op.execute("UPDATE users SET is_admin = coalesce(super_admin, false)")


def downgrade():
    op.drop_table("teams_pairs")
    op.drop_table("teams_partner_requests")
    op.drop_table("teams_mini_tournaments")
    op.drop_table("teams_players")
