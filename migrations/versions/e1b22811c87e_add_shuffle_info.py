"""add shuffle info

Revision ID: e1b22811c87e
Revises: 4e1e938e6510
Create Date: 2026-02-26 14:12:47.888850

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e1b22811c87e"
down_revision = "4e1e938e6510"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "shuffle_tournaments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("current_matchweek", sa.Integer(), nullable=False),
        sa.Column("max_players", sa.Integer(), nullable=False),
        sa.Column("number_of_divisions", sa.Integer(), nullable=False),
        sa.Column("has_ended", sa.Boolean(), nullable=True),
        sa.Column("division_multipliers_raw", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "shuffle_matches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("shuffle_tournament_id", sa.Integer(), nullable=False),
        sa.Column("matchweek", sa.Integer(), nullable=False),
        sa.Column("division", sa.Integer(), nullable=False),
        sa.Column("score1", sa.Integer(), nullable=True),
        sa.Column("score2", sa.Integer(), nullable=True),
        sa.Column("played", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["shuffle_tournament_id"],
            ["shuffle_tournaments.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "players_in_shuffle_match",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("shuffle_match_id", sa.Integer(), nullable=False),
        sa.Column(
            "team", sa.Enum("Home", "Away", name="shuffle_teams"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
        ),
        sa.ForeignKeyConstraint(
            ["shuffle_match_id"],
            ["shuffle_matches.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "players_in_shuffle_tournament",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("shuffle_tournament_id", sa.Integer(), nullable=False),
        sa.Column("division_number", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=True),
        sa.Column("wins", sa.Integer(), nullable=True),
        sa.Column("draws", sa.Integer(), nullable=True),
        sa.Column("losses", sa.Integer(), nullable=True),
        sa.Column("games_played", sa.Integer(), nullable=True),
        sa.Column("games_won", sa.Integer(), nullable=True),
        sa.Column("games_lost", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
        ),
        sa.ForeignKeyConstraint(
            ["shuffle_tournament_id"],
            ["shuffle_tournaments.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("players_in_shuffle_tournament")
    op.drop_table("players_in_shuffle_match")
    op.drop_table("shuffle_matches")
    op.drop_table("shuffle_tournaments")
