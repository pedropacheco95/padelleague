"""normalize: news.cover_path -> images/News/<file>

Revision ID: a1e2b3c4d5f6
Revises: 63c524cb947d
Create Date: 2025-09-12 12:00:00.000000
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "a1e2b3c4d5f6"
down_revision = "63c524cb947d"
branch_labels = None
depends_on = None


def upgrade():
    # Normalize cover_path to canonical "images/News/<filename>"
    op.execute("""
        WITH src AS (
            SELECT id, trim(cover_path) AS path
            FROM news
            WHERE cover_path IS NOT NULL AND trim(cover_path) <> ''
        ),
        base AS (
            SELECT
                id,
                path,
                regexp_replace(path, '^.*\\/', '') AS filename
            FROM src
        ),
        norm AS (
            SELECT
                id,
                CASE
                    -- GCS URL containing /images/...  -> images/News/<suffix>
                    WHEN path ILIKE 'http%://storage.googleapis.com/%/images/%'
                        THEN 'images/News/' || regexp_replace(path, '^.*?/images/', '')
                    -- already canonical
                    WHEN path ILIKE 'images/News/%'
                        THEN path
                    -- images/<anything> -> images/News/<anything_without_prefix>
                    WHEN path ILIKE 'images/%'
                        THEN 'images/News/' || regexp_replace(path, '^images/(.*)$', '\\1')
                    -- news/<file> or News/<file> -> images/News/<file>
                    WHEN path ILIKE 'news/%'
                        THEN 'images/News/' || regexp_replace(path, '^news/(.*)$', '\\1')
                    WHEN path ILIKE 'News/%'
                        THEN 'images/News/' || regexp_replace(path, '^News/(.*)$', '\\1')
                    -- Just a filename or random path -> images/News/<filename>
                    ELSE 'images/News/' || filename
                END AS new_path
            FROM base
        )
        UPDATE news n
        SET cover_path = x.new_path
        FROM norm x
        WHERE n.id = x.id
          AND n.cover_path IS DISTINCT FROM x.new_path;
    """)


def downgrade():
    # Not safely reversible (data normalization). No-op.
    pass
