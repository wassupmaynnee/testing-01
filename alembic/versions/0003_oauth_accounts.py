"""oauth_accounts: encrypted OAuth tokens for private clip publishing

Revision ID: 0003_oauth_accounts
Revises: 0002_billing
Create Date: 2026-06-30

Additive only and introspective — creates the oauth_accounts table iff it does
not already exist, so it applies cleanly on a fresh DB (after 0002) and is a
safe no-op on a DB where the table was already created on startup. Never edits
0001/0002.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_oauth_accounts"
down_revision = "0002_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "oauth_accounts" in inspector.get_table_names():
        return

    op.create_table(
        "oauth_accounts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),  # e.g. "youtube"
        sa.Column("access_token_enc", sa.Text, nullable=False),
        sa.Column("refresh_token_enc", sa.Text, nullable=True),
        sa.Column("token_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope", sa.Text, nullable=True),
        sa.Column("account_label", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "provider", name="uq_oauth_user_provider"),
    )
    op.create_index("ix_oauth_accounts_user_id", "oauth_accounts", ["user_id"])
    op.create_index("ix_oauth_accounts_provider", "oauth_accounts", ["provider"])


def downgrade() -> None:
    op.drop_index("ix_oauth_accounts_provider", table_name="oauth_accounts")
    op.drop_index("ix_oauth_accounts_user_id", table_name="oauth_accounts")
    op.drop_table("oauth_accounts")
