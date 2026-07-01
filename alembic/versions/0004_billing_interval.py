"""users.billing_interval: record monthly vs annual chosen at checkout

Revision ID: 0004_billing_interval
Revises: 0003_oauth_accounts
Create Date: 2026-06-30

Additive only and introspective — adds the nullable users.billing_interval column
iff it does not already exist, so it applies cleanly on a fresh DB (after 0003)
and is a safe no-op where the column was already created on startup. Never edits
0001/0002/0003.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_billing_interval"
down_revision = "0003_oauth_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "billing_interval" not in cols:
        op.add_column("users", sa.Column("billing_interval", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "billing_interval")
