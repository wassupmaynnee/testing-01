"""billing: user tier + stripe_customer_id, stripe_events idempotency ledger

Revision ID: 0002_billing
Revises: 0001_baseline
Create Date: 2026-06-29

Additive only — applies cleanly on a fresh DB (after 0001) and on the seeded one
(existing user rows pick up the server_default tier='free'). Never edits 0001.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_billing"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("tier", sa.String(32), nullable=False, server_default="free"),
    )
    op.add_column(
        "users",
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
    )

    op.create_table(
        "stripe_events",
        sa.Column("id", sa.String(255), primary_key=True),  # Stripe event id (evt_...)
        sa.Column("type", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=True),
        sa.Column("credits_granted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("stripe_events")
    op.drop_column("users", "stripe_customer_id")
    op.drop_column("users", "tier")
