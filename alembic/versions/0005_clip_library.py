"""clips.thumb_path / aspect / featured: clip-library + homepage showcase fields

Revision ID: 0005_clip_library
Revises: 0004_billing_interval
Create Date: 2026-07-03

Additive only and introspective — adds the three columns iff missing, so it
applies cleanly on a fresh DB (after 0004) and is a safe no-op where the
columns were already created on startup. Never edits earlier revisions.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_clip_library"
down_revision = "0004_billing_interval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("clips")}
    if "thumb_path" not in cols:
        op.add_column("clips", sa.Column("thumb_path", sa.Text, nullable=True))
    if "aspect" not in cols:
        op.add_column("clips", sa.Column("aspect", sa.String(8), nullable=False,
                                         server_default="9:16"))
    if "featured" not in cols:
        op.add_column("clips", sa.Column("featured", sa.Boolean, nullable=False,
                                         server_default=sa.text("false")))
        op.create_index("ix_clips_featured", "clips", ["featured"])


def downgrade() -> None:
    op.drop_index("ix_clips_featured", table_name="clips")
    op.drop_column("clips", "featured")
    op.drop_column("clips", "aspect")
    op.drop_column("clips", "thumb_path")
