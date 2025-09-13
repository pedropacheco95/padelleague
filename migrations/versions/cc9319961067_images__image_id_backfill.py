"""images: add *_image_id columns and backfill from paths

Revision ID: cc9319961067
Revises: a1e2b3c4d5f6
Create Date: 2025-09-12 09:36:53.141748
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "cc9319961067"
down_revision = "a1e2b3c4d5f6"
branch_labels = None
depends_on = None


def upgrade():
    # Clean stray old table if present
    op.execute("DROP TABLE IF EXISTS sponsor;")

    # Ensure a UNIQUE constraint on images.object_key (safe if it already exists)
    op.execute(
        """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM   pg_constraint
            WHERE  conname = 'uq_images_object_key'
        ) THEN
            ALTER TABLE images
            ADD CONSTRAINT uq_images_object_key UNIQUE (object_key);
        END IF;
    END$$;
    """
    )

    # Add new *_image_id columns if they don't exist
    op.execute(
        "ALTER TABLE players  ADD COLUMN IF NOT EXISTS picture_id       INTEGER;"
    )
    op.execute(
        "ALTER TABLE players  ADD COLUMN IF NOT EXISTS large_picture_id INTEGER;"
    )
    op.execute(
        "ALTER TABLE news     ADD COLUMN IF NOT EXISTS cover_image_id   INTEGER;"
    )
    op.execute(
        "ALTER TABLE sponsors ADD COLUMN IF NOT EXISTS image_id         INTEGER;"
    )

    # Add FKs (if not already present)
    op.execute(
        """
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_players_picture_id_images') THEN
            ALTER TABLE players
            ADD CONSTRAINT fk_players_picture_id_images
            FOREIGN KEY (picture_id) REFERENCES images(id) ON DELETE SET NULL;
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_players_large_picture_id_images') THEN
            ALTER TABLE players
            ADD CONSTRAINT fk_players_large_picture_id_images
            FOREIGN KEY (large_picture_id) REFERENCES images(id) ON DELETE SET NULL;
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_news_cover_image_id_images') THEN
            ALTER TABLE news
            ADD CONSTRAINT fk_news_cover_image_id_images
            FOREIGN KEY (cover_image_id) REFERENCES images(id) ON DELETE SET NULL;
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sponsors_image_id_images') THEN
            ALTER TABLE sponsors
            ADD CONSTRAINT fk_sponsors_image_id_images
            FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE SET NULL;
        END IF;
    END$$;
    """
    )

    # Helpful indexes (no-ops if they exist)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_players_picture_id        ON players  (picture_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_players_large_picture_id  ON players  (large_picture_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_news_cover_image_id       ON news     (cover_image_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sponsors_image_id         ON sponsors (image_id);"
    )

    # --- BACKFILL ---

    # Players.picture_path -> players.picture_id  (normalize to images/Player/<...>)
    op.execute(
        """
        WITH src AS (
            SELECT id, trim(picture_path) AS path
            FROM players
            WHERE picture_path IS NOT NULL AND trim(picture_path) <> ''
        ),
        base AS (
            SELECT id, path, regexp_replace(path, '^.*\\/', '') AS filename
            FROM src
        ),
        norm AS (
            SELECT
                id,
                CASE
                    WHEN path LIKE 'images/%' THEN path
                    WHEN path ILIKE 'player/%' OR path ILIKE 'Player/%' THEN 'images/' || path
                    WHEN path ILIKE 'http%://storage.googleapis.com/%/images/%'
                        THEN 'images/' || regexp_replace(path, '^.*?/images/', '')
                    ELSE 'images/Player/' || filename
                END AS object_key
            FROM base
        ),
        ins AS (
            INSERT INTO images (object_key, is_public)
            SELECT DISTINCT object_key, TRUE
            FROM norm
            WHERE object_key IS NOT NULL
            ON CONFLICT (object_key) DO NOTHING
            RETURNING id, object_key
        )
        UPDATE players p
        SET picture_id = i.id
        FROM images i
        JOIN norm n ON n.object_key = i.object_key
        WHERE p.id = n.id
          AND (p.picture_id IS NULL OR p.picture_id = 0);
    """
    )

    # Players.large_picture_path -> players.large_picture_id
    op.execute(
        """
        WITH src AS (
            SELECT id, trim(large_picture_path) AS path
            FROM players
            WHERE large_picture_path IS NOT NULL AND trim(large_picture_path) <> ''
        ),
        base AS (
            SELECT id, path, regexp_replace(path, '^.*\\/', '') AS filename
            FROM src
        ),
        norm AS (
            SELECT
                id,
                CASE
                    WHEN path LIKE 'images/%' THEN path
                    WHEN path ILIKE 'player/%' OR path ILIKE 'Player/%' THEN 'images/' || path
                    WHEN path ILIKE 'http%://storage.googleapis.com/%/images/%'
                        THEN 'images/' || regexp_replace(path, '^.*?/images/', '')
                    ELSE 'images/Player/' || filename
                END AS object_key
            FROM base
        ),
        ins AS (
            INSERT INTO images (object_key, is_public)
            SELECT DISTINCT object_key, TRUE
            FROM norm
            WHERE object_key IS NOT NULL
            ON CONFLICT (object_key) DO NOTHING
            RETURNING id, object_key
        )
        UPDATE players p
        SET large_picture_id = i.id
        FROM images i
        JOIN norm n ON n.object_key = i.object_key
        WHERE p.id = n.id
          AND (p.large_picture_id IS NULL OR p.large_picture_id = 0);
    """
    )

    # NEWS.cover_path (already normalized in previous migration) -> news.cover_image_id
    op.execute(
        """
        INSERT INTO images (object_key, is_public)
        SELECT DISTINCT trim(cover_path), TRUE
        FROM news
        WHERE cover_path IS NOT NULL AND trim(cover_path) <> ''
        ON CONFLICT (object_key) DO NOTHING;
    """
    )
    op.execute(
        """
        UPDATE news n
        SET cover_image_id = i.id
        FROM images i
        WHERE i.object_key = trim(n.cover_path)
          AND (n.cover_image_id IS NULL OR n.cover_image_id = 0);
    """
    )

    # SPONSORS.image (varchar) -> sponsors.image_id (normalize to images/Sponsor/<...>)
    op.execute(
        """
        WITH src AS (
            SELECT id, trim(image) AS path
            FROM sponsors
            WHERE image IS NOT NULL AND trim(image) <> ''
        ),
        base AS (
            SELECT id, path, regexp_replace(path, '^.*\\/', '') AS filename
            FROM src
        ),
        norm AS (
            SELECT
                id,
                CASE
                    WHEN path LIKE 'images/Sponsor/%' THEN path
                    WHEN path LIKE 'images/%'
                        THEN 'images/Sponsor/' || regexp_replace(path, '^images/(.*)$', '\\1')
                    WHEN path ILIKE 'sponsor/%'
                        THEN 'images/' || path
                    WHEN path ILIKE 'http%://storage.googleapis.com/%/images/%'
                        THEN 'images/Sponsor/' || regexp_replace(path, '^.*?/images/', '')
                    ELSE 'images/Sponsor/' || filename
                END AS object_key
            FROM base
        ),
        ins AS (
            INSERT INTO images (object_key, is_public)
            SELECT DISTINCT object_key, TRUE
            FROM norm
            WHERE object_key IS NOT NULL
            ON CONFLICT (object_key) DO NOTHING
            RETURNING id, object_key
        )
        UPDATE sponsors s
        SET image_id = i.id
        FROM images i
        JOIN norm n ON n.object_key = i.object_key
        WHERE s.id = n.id
          AND (s.image_id IS NULL OR s.image_id = 0);
    """
    )

    # Make existing images public and enforce default TRUE
    op.execute(
        "UPDATE images SET is_public = TRUE WHERE is_public IS DISTINCT FROM TRUE;"
    )

    with op.batch_alter_table("images") as batch_op:
        batch_op.alter_column(
            "is_public",
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        )


def downgrade():
    # Data-preserving; leave columns and links in place
    pass
