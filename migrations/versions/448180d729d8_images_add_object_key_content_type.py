"""images: add object_key/content_type/...

Revision ID: 448180d729d8
Revises: d44383bea9b4
Create Date: 2025-09-11 19:47:30.635435
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "448180d729d8"
down_revision = "d44383bea9b4"
branch_labels = None
depends_on = None


def upgrade():
    # 1) Add new columns (nullable at first so we can backfill)
    op.add_column(
        "images", sa.Column("object_key", sa.String(length=512), nullable=True)
    )
    op.add_column(
        "images", sa.Column("content_type", sa.String(length=128), nullable=True)
    )
    op.add_column("images", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("images", sa.Column("is_public", sa.Boolean(), nullable=True))

    # 2) Backfill object_key from old filename (if filename exists)
    op.execute(
        """
        UPDATE images
        SET object_key = filename
        WHERE object_key IS NULL
          AND filename IS NOT NULL
          AND filename <> ''
    """
    )

    op.execute(
        """
        UPDATE images
        SET is_public = true
    """
    )

    # 3) Make object_key NOT NULL and unique
    op.alter_column(
        "images", "object_key", existing_type=sa.String(length=512), nullable=False
    )
    op.create_unique_constraint("uq_images_object_key", "images", ["object_key"])

    # (Optional) If you want to enforce ON DELETE CASCADE on imageable fk, recreate it:
    # op.drop_constraint('images_imageable_id_fkey', 'images', type_='foreignkey')
    # op.create_foreign_key('images_imageable_id_fkey', 'images', 'imageables',
    #                       ['imageable_id'], ['imageable_id'], ondelete='CASCADE')

    # 4) (Optional) keep filename for now; drop it later in its own migration
    # op.drop_column('images', 'filename')


def downgrade():
    # Reverse unique + not-null first
    op.drop_constraint("uq_images_object_key", "images", type_="unique")
    op.alter_column(
        "images", "object_key", existing_type=sa.String(length=512), nullable=True
    )

    # Drop added cols
    op.drop_column("images", "is_public")
    op.drop_column("images", "size_bytes")
    op.drop_column("images", "content_type")
    op.drop_column("images", "object_key")
