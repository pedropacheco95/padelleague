import sqlalchemy as sa
from alembic import op

revision = "9b4588f1992a"
down_revision = "6dcd520eb654"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("divisions", sa.Column("logo_image_id", sa.Integer(), nullable=True))
    op.add_column(
        "divisions", sa.Column("large_picture_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_divisions_logo_image",
        "divisions",
        "images",
        ["logo_image_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_divisions_large_picture",
        "divisions",
        "images",
        ["large_picture_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_divisions_large_picture", "divisions", type_="foreignkey")
    op.drop_constraint("fk_divisions_logo_image", "divisions", type_="foreignkey")
    op.drop_column("divisions", "large_picture_id")
    op.drop_column("divisions", "logo_image_id")
