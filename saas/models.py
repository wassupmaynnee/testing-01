"""ORM models: users, jobs, clips, and a credit ledger."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime, Enum, Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class IngestKind(str, enum.Enum):
    upload = "upload"      # live in the walking skeleton
    youtube = "youtube"    # deferred seam
    twitch = "twitch"      # deferred seam


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    credits: Mapped[int] = mapped_column(Integer, default=0)
    # Current plan key from the frozen tier catalog (free|starter|pro|scale).
    tier: Mapped[str] = mapped_column(String(32), default="free")
    # Stripe customer handle — set on first checkout so the billing portal and
    # repeat purchases reuse one customer. Nullable until they buy.
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    jobs: Mapped[list["Job"]] = relationship(back_populates="user", cascade="all,delete-orphan")
    ledger: Mapped[list["CreditLedger"]] = relationship(back_populates="user", cascade="all,delete-orphan")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[IngestKind] = mapped_column(Enum(IngestKind), default=IngestKind.upload)
    source_ref: Mapped[str] = mapped_column(Text)  # uploaded file path or URL
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued, index=True)
    stage: Mapped[int] = mapped_column(Integer, default=0)        # STEP_LABELS index 0..6
    progress: Mapped[float] = mapped_column(Float, default=0.0)   # 0..1
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped[User] = relationship(back_populates="jobs")
    clips: Mapped[list["Clip"]] = relationship(back_populates="job", cascade="all,delete-orphan")


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="Clip")
    file_path: Mapped[str] = mapped_column(Text)
    start_s: Mapped[float] = mapped_column(Float, default=0.0)
    end_s: Mapped[float] = mapped_column(Float, default=0.0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    # Frozen-formula sub-signals, persisted for transparency.
    hook: Mapped[float] = mapped_column(Float, default=0.0)
    pace: Mapped[float] = mapped_column(Float, default=0.0)
    sentiment: Mapped[float] = mapped_column(Float, default=0.0)
    face: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    job: Mapped[Job] = relationship(back_populates="clips")


class CreditLedger(Base):
    __tablename__ = "credit_ledger"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="ledger")


class StripeEvent(Base):
    """
    Idempotency ledger for Stripe webhooks. The Stripe event id is the primary
    key, so a duplicate `checkout.session.completed` (Stripe does not guarantee
    single delivery) is a no-op insert conflict and credits never double-grant.
    """
    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)  # Stripe event id (evt_...)
    type: Mapped[str] = mapped_column(String(128))
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    credits_granted: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
