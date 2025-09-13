"""normalize: division image paths to images/Division/*

Revision ID: 737ed839a327
Revises: 9b4588f1992a
Create Date: 2025-09-11 19:12:23.309795

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "737ed839a327"
down_revision = "9b4588f1992a"
branch_labels = None
depends_on = None


def upgrade():
    # --- Normalize large_picture_path ---
    op.execute(
        """
        UPDATE divisions
        SET large_picture_path = CASE
            WHEN large_picture_path ~ '^images/Division/' THEN large_picture_path
            WHEN large_picture_path ~ '^images/'          THEN regexp_replace(large_picture_path, '^images/', 'images/Division/')
            WHEN large_picture_path ~ '^Division/'        THEN 'images/' || large_picture_path
            ELSE 'images/Division/' || large_picture_path
        END
        WHERE large_picture_path IS NOT NULL
          AND large_picture_path <> '';
    """
    )

    # --- Normalize logo_image_path (same rules) ---
    op.execute(
        """
        UPDATE divisions
        SET logo_image_path = CASE
            WHEN logo_image_path ~ '^images/Division/' THEN logo_image_path
            WHEN logo_image_path ~ '^images/'          THEN regexp_replace(logo_image_path, '^images/', 'images/Division/')
            WHEN logo_image_path ~ '^Division/'        THEN 'images/' || logo_image_path
            ELSE 'images/Division/' || logo_image_path
        END
        WHERE logo_image_path IS NOT NULL
          AND logo_image_path <> '';
    """
    )


def downgrade():
    # no-op (we keep normalized keys)
    pass
