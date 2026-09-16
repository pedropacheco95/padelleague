"""add chatbot_logs

Revision ID: 9c2f1a7d4e21
Revises: 37d0294618a5
Create Date: 2026-09-16 15:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "9c2f1a7d4e21"
down_revision = "37d0294618a5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chatbot_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("agent_name", sa.String(length=64), nullable=True),
        sa.Column("agent_questions", sa.Text(), nullable=True),
        sa.Column("sql_queries", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("verdict", sa.String(length=16), nullable=True),
        sa.Column("expected_answer", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chatbot_logs_created_at", "chatbot_logs", ["created_at"], unique=False
    )


def downgrade():
    op.drop_index("ix_chatbot_logs_created_at", table_name="chatbot_logs")
    op.drop_table("chatbot_logs")
