"""backfill: images + link division FKs

Revision ID: d44383bea9b4
Revises: 737ed839a327
Create Date: 2025-09-11 19:14:22.824272

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd44383bea9b4'
down_revision = '737ed839a327'
branch_labels = None
depends_on = None


def upgrade():
    # Insert missing images for normalized large_picture_path
    op.execute("""
        INSERT INTO images (filename)
        SELECT DISTINCT d.large_picture_path
        FROM divisions d
        WHERE d.large_picture_path IS NOT NULL
          AND d.large_picture_path <> ''
          AND NOT EXISTS (
              SELECT 1 FROM images i WHERE i.filename = d.large_picture_path
          );
    """)

    # Insert missing images for normalized logo_image_path
    op.execute("""
        INSERT INTO images (filename)
        SELECT DISTINCT d.logo_image_path
        FROM divisions d
        WHERE d.logo_image_path IS NOT NULL
          AND d.logo_image_path <> ''
          AND NOT EXISTS (
              SELECT 1 FROM images i WHERE i.filename = d.logo_image_path
          );
    """)

    # Link FKs to those images
    op.execute("""
        UPDATE divisions d
        SET large_picture_id = i.id
        FROM images i
        WHERE d.large_picture_path IS NOT NULL
          AND d.large_picture_path <> ''
          AND i.filename = d.large_picture_path
          AND (d.large_picture_id IS NULL OR d.large_picture_id <> i.id);
    """)

    op.execute("""
        UPDATE divisions d
        SET logo_image_id = i.id
        FROM images i
        WHERE d.logo_image_path IS NOT NULL
          AND d.logo_image_path <> ''
          AND i.filename = d.logo_image_path
          AND (d.logo_image_id IS NULL OR d.logo_image_id <> i.id);
    """)

def downgrade():
    # keep data (optionally null the FKs)
    pass