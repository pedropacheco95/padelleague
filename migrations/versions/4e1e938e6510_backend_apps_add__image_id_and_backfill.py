"""backend_apps: add *_image_id and backfill

Revision ID: 4e1e938e6510
Revises: cc9319961067
Create Date: 2025-09-12 10:13:24.240343

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "4e1e938e6510"
down_revision = "cc9319961067"
branch_labels = None
depends_on = None


def upgrade():
    # 1) Add FK column
    op.add_column(
        "backend_app",
        sa.Column("image_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        None, "backend_app", "images", ["image_id"], ["id"], ondelete="SET NULL"
    )

    # 2) Backfill: create images from existing app_image values
    # Normalize to live under images/Backend_App/
    op.execute(
        """
        WITH candidates AS (
            SELECT DISTINCT
                CASE
                    WHEN app_image IS NULL OR app_image = '' OR lower(app_image) = 'none' THEN NULL
                    WHEN app_image LIKE 'images/%' THEN app_image
                    WHEN app_image LIKE '%/%' THEN 'images/' || app_image
                    ELSE 'images/Backend_App/' || app_image
                END AS object_key
            FROM backend_app
        ),
        to_insert AS (
            SELECT c.object_key
            FROM candidates c
            WHERE c.object_key IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM images i WHERE i.object_key = c.object_key)
        )
        INSERT INTO images (object_key, is_public)
        SELECT object_key, TRUE FROM to_insert;
    """
    )

    # 3) Link backend_app.image_id to the new/existing images
    op.execute(
        """
        UPDATE backend_app ba
        SET image_id = i.id
        FROM images i
        WHERE i.object_key = CASE
            WHEN ba.app_image IS NULL OR ba.app_image = '' OR lower(ba.app_image) = 'none' THEN NULL
            WHEN ba.app_image LIKE 'images/%' THEN ba.app_image
            WHEN ba.app_image LIKE '%/%' THEN 'images/' || ba.app_image
            ELSE 'images/Backend_App/' || ba.app_image
        END;
    """
    )

    # 4) Ensure all images are public (defensive, won’t hurt)
    op.execute(
        "UPDATE images SET is_public = TRUE WHERE is_public IS DISTINCT FROM TRUE;"
    )

    # 5) Optionally drop old column once app is updated
    op.drop_column("backend_app", "app_image")


def downgrade():
    # Re-create old column
    op.add_column(
        "backend_app", sa.Column("app_image", sa.String(length=200), nullable=True)
    )

    # Best-effort restore filename from object_key
    op.execute(
        """
        UPDATE backend_app ba
        SET app_image = CASE
            WHEN i.object_key LIKE 'images/Backend_App/%'
                THEN substring(i.object_key from '^images/Backend_App/(.*)$')
            WHEN i.object_key LIKE 'images/%'
                THEN substring(i.object_key from '^images/(.*)$')
            ELSE i.object_key
        END
        FROM images i
        WHERE ba.image_id = i.id;
    """
    )

    op.drop_constraint(
        constraint_name=None, table_name="backend_app", type_="foreignkey"
    )
    op.drop_column("backend_app", "image_id")
