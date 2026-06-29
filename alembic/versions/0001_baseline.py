"""baseline schema: users, jobs, clips, credit_ledger

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

job_status = sa.Enum("queued", "running", "completed", "failed", name="jobstatus")
ingest_kind = sa.Enum("upload", "youtube", "twitch", name="ingestkind")


def upgrade() -> None:
    bind = op.get_bind()
    job_status.create(bind, checkfirst=True)
    ingest_kind.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("credits", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", ingest_kind, nullable=False, server_default="upload"),
        sa.Column("source_ref", sa.Text, nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="queued"),
        sa.Column("stage", sa.Integer, nullable=False, server_default="0"),
        sa.Column("progress", sa.Float, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])

    op.create_table(
        "clips",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("job_id", sa.String(32), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False, server_default="Clip"),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("start_s", sa.Float, nullable=False, server_default="0"),
        sa.Column("end_s", sa.Float, nullable=False, server_default="0"),
        sa.Column("score", sa.Float, nullable=False, server_default="0"),
        sa.Column("hook", sa.Float, nullable=False, server_default="0"),
        sa.Column("pace", sa.Float, nullable=False, server_default="0"),
        sa.Column("sentiment", sa.Float, nullable=False, server_default="0"),
        sa.Column("face", sa.Float, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_clips_job_id", "clips", ["job_id"])

    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("delta", sa.Integer, nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_credit_ledger_user_id", "credit_ledger", ["user_id"])


def downgrade() -> None:
    op.drop_table("credit_ledger")
    op.drop_table("clips")
    op.drop_table("jobs")
    op.drop_table("users")
    bind = op.get_bind()
    ingest_kind.drop(bind, checkfirst=True)
    job_status.drop(bind, checkfirst=True)
