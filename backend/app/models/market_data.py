"""Cached, normalised Elexon data. Raw API timestamps are preserved (publish vs. target time)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime


class WindForecastRecord(Base):
    """One WINDFOR value: forecast for the hour starting ``start_time`` as published at ``publish_time``."""

    __tablename__ = "wind_forecast_records"
    __table_args__ = (
        UniqueConstraint("publish_time", "start_time", name="uq_forecast_publish_start"),
        Index("ix_forecast_publish", "publish_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    publish_time: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    start_time: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    generation_mw: Mapped[float] = mapped_column(Float, nullable=False)


class WindActualRecord(Base):
    """One FUELHH WIND half-hour observation."""

    __tablename__ = "wind_actual_records"
    __table_args__ = (UniqueConstraint("start_time", name="uq_actual_start"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    start_time: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    settlement_date: Mapped[date] = mapped_column(Date, nullable=False)
    settlement_period: Mapped[int] = mapped_column(Integer, nullable=False)
    publish_time: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    generation_mw: Mapped[float] = mapped_column(Float, nullable=False)


class FetchCoverage(Base):
    """Records which closed, inclusive UTC ranges of a dataset have already been fetched.

    Used to avoid re-requesting immutable history. A range is only considered reusable if it was
    fetched after it closed (plus a settling margin), so partially elapsed ranges are re-fetched.
    """

    __tablename__ = "fetch_coverage"
    __table_args__ = (Index("ix_coverage_dataset_range", "dataset", "range_start", "range_end"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset: Mapped[str] = mapped_column(String(16), nullable=False)
    range_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    range_end: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
