"""users.referral_code + referrals table, with backfill for existing users

Revision ID: 0006_referrals
Revises: 0005_clip_library
Create Date: 2026-07-03

Additive and introspective; backfills a unique referral code for every existing
user so older accounts can share links immediately.
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = "0006_referrals"
down_revision = "0005_clip_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    cols = {c["name"] for c in insp.get_columns("users")}
    if "referral_code" not in cols:
        op.add_column("users", sa.Column("referral_code", sa.String(16), nullable=True))
        op.create_index("ix_users_referral_code", "users", ["referral_code"], unique=True)
        # Backfill: deterministic-length random codes for existing accounts.
        users = bind.execute(sa.text("SELECT id FROM users WHERE referral_code IS NULL")).fetchall()
        for (uid,) in users:
            bind.execute(sa.text("UPDATE users SET referral_code = :c WHERE id = :i"),
                         {"c": uuid.uuid4().hex[:8], "i": uid})

    if "referrals" not in insp.get_table_names():
        op.create_table(
            "referrals",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("referrer_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("referred_user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("credits_referrer", sa.Integer, nullable=False, server_default="0"),
            sa.Column("credits_referred", sa.Integer, nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("credited_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("referred_user_id", name="uq_referral_referred_once"),
        )
        op.create_index("ix_referrals_referrer_id", "referrals", ["referrer_id"])
        op.create_index("ix_referrals_referred_user_id", "referrals", ["referred_user_id"])


def downgrade() -> None:
    op.drop_index("ix_referrals_referred_user_id", table_name="referrals")
    op.drop_index("ix_referrals_referrer_id", table_name="referrals")
    op.drop_table("referrals")
    op.drop_index("ix_users_referral_code", table_name="users")
    op.drop_column("users", "referral_code")
