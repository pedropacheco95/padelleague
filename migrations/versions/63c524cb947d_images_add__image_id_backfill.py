"""images: add *_image_id + backfill

Revision ID: 63c524cb947d
Revises: 448180d729d8
Create Date: 2025-09-12 09:12:40.035768

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "63c524cb947d"
down_revision = "448180d729d8"
branch_labels = None
depends_on = None


def _column_exists(insp, table, column):
    return any(c["name"] == column for c in insp.get_columns(table))


def _fk_exists(insp, table, name):
    fks = insp.get_foreign_keys(table)
    return any(fk.get("name") == name for fk in fks if fk.get("name"))


def _add_fk_if_missing(
    insp, table, column, ref_table, ref_col="id", ondelete="SET NULL", name=None
):
    if name is None:
        name = f"fk_{table}_{column}_{ref_table}"
    if not _fk_exists(insp, table, name):
        op.create_foreign_key(
            name, table, ref_table, [column], [ref_col], ondelete=ondelete
        )


def _backfill_fk(table, id_col, path_col, fk_col, folder):
    """
    Normalize legacy path -> images/<Folder>/... object_key
    Create missing rows in images(object_key)
    Update table.<fk_col> with images.id
    """
    op.execute(
        sa.text(
            f"""
        WITH src AS (
            SELECT
                {id_col} AS src_id,
                CASE
                  WHEN {path_col} IS NULL OR {path_col} = '' THEN NULL
                  WHEN {path_col} LIKE 'images/%'          THEN {path_col}
                  WHEN {path_col} ILIKE '{folder}/%'       THEN 'images/' || {path_col}
                  ELSE 'images/{folder}/' || {path_col}
                END AS object_key
            FROM {table}
        ),
        ins AS (
            INSERT INTO images (object_key, is_public)
            SELECT DISTINCT object_key, TRUE
            FROM src
            WHERE object_key IS NOT NULL
            ON CONFLICT (object_key) DO NOTHING
            RETURNING id, object_key
        )
        UPDATE {table} t
        SET {fk_col} = i.id
        FROM (SELECT id, object_key FROM images) i
        JOIN src s ON s.object_key = i.object_key
        WHERE t.{id_col} = s.src_id
          AND s.object_key IS NOT NULL
          AND (t.{fk_col} IS NULL OR t.{fk_col} = 0);
    """
        )
    )


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # Drop stray/old table if present
    op.execute(sa.text("DROP TABLE IF EXISTS sponsor"))

    # --- Add columns if missing ---
    if not _column_exists(insp, "players", "picture_id"):
        op.add_column("players", sa.Column("picture_id", sa.Integer(), nullable=True))
    if not _column_exists(insp, "players", "large_picture_id"):
        op.add_column(
            "players", sa.Column("large_picture_id", sa.Integer(), nullable=True)
        )

    if not _column_exists(insp, "news", "cover_image_id"):
        op.add_column("news", sa.Column("cover_image_id", sa.Integer(), nullable=True))

    if not _column_exists(insp, "sponsors", "image_id"):
        op.add_column("sponsors", sa.Column("image_id", sa.Integer(), nullable=True))

    # --- Add FKs if missing ---
    _add_fk_if_missing(
        insp, "players", "picture_id", "images", name="fk_players_picture_id_images"
    )
    _add_fk_if_missing(
        insp,
        "players",
        "large_picture_id",
        "images",
        name="fk_players_large_picture_id_images",
    )
    _add_fk_if_missing(
        insp, "news", "cover_image_id", "images", name="fk_news_cover_image_id_images"
    )
    _add_fk_if_missing(
        insp, "sponsors", "image_id", "images", name="fk_sponsors_image_id_images"
    )

    # --- Data backfill from legacy columns ---
    _backfill_fk("players", "id", "picture_path", "picture_id", "Player")
    _backfill_fk("players", "id", "large_picture_path", "large_picture_id", "Player")
    _backfill_fk("news", "id", "cover_path", "cover_image_id", "News")
    _backfill_fk("sponsors", "id", "image", "image_id", "Sponsor")

    # (optional) add indexes for faster lookups
    if not any(
        i["name"] == "ix_players_picture_id" for i in insp.get_indexes("players")
    ):
        op.create_index("ix_players_picture_id", "players", ["picture_id"])
    if not any(
        i["name"] == "ix_players_large_picture_id" for i in insp.get_indexes("players")
    ):
        op.create_index("ix_players_large_picture_id", "players", ["large_picture_id"])
    if not any(i["name"] == "ix_news_cover_image_id" for i in insp.get_indexes("news")):
        op.create_index("ix_news_cover_image_id", "news", ["cover_image_id"])
    if not any(
        i["name"] == "ix_sponsors_image_id" for i in insp.get_indexes("sponsors")
    ):
        op.create_index("ix_sponsors_image_id", "sponsors", ["image_id"])


def downgrade():
    # keep simple; optionally drop FKs/columns if you need full reversibility
    pass
