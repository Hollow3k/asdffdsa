from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
ACTIVE_JOB_STATUSES = (STATUS_PENDING, STATUS_RUNNING)


class Calibration(Base):
    """A versioned calibration run. Versions are immutable once completed."""

    __tablename__ = "calibrations"
    __table_args__ = (
        UniqueConstraint("version", name="uq_calibration_version"),
        # At most one active calibration (partial unique index; supported by SQLite and PostgreSQL).
        Index(
            "uq_calibration_single_active",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_PENDING, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    cutoff_time: Mapped[str] = mapped_column(String(5), nullable=False)
    metric_version: Mapped[str] = mapped_column(String(16), nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage: Mapped[str] = mapped_column(String(120), nullable=False, default="Queued")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    breakdowns: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    quality: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)

    observations: Mapped[list[CalibrationObservation]] = relationship(
        back_populates="calibration", cascade="all, delete-orphan", passive_deletes=True
    )


class CalibrationObservation(Base):
    """One matched hourly forecast/actual pair, with full provenance for reproducibility."""

    __tablename__ = "calibration_observations"
    __table_args__ = (
        UniqueConstraint("calibration_id", "delivery_start", name="uq_obs_calibration_hour"),
        Index("ix_obs_calibration_date", "calibration_id", "delivery_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    calibration_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calibrations.id", ondelete="CASCADE"), nullable=False
    )
    delivery_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    delivery_date: Mapped[date] = mapped_column(Date, nullable=False)  # UK local date
    hour_local: Mapped[int] = mapped_column(Integer, nullable=False)  # UK local hour 0-23
    forecast_mw: Mapped[float] = mapped_column(Float, nullable=False)
    actual_mw: Mapped[float] = mapped_column(Float, nullable=False)
    error_mw: Mapped[float] = mapped_column(Float, nullable=False)  # forecast - actual
    forecast_publish_time: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    decision_cutoff: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    actual_available_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    calibration: Mapped[Calibration] = relationship(back_populates="observations")
