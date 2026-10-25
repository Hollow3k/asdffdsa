"""Read-through persistence for Elexon data.

Historical ranges are immutable once they have closed, so a fetched range is recorded in
``fetch_coverage`` and reused instead of calling the API again. A range is only reusable if it
was fetched *after* it closed (plus a small settling margin) - partially elapsed ranges are always
re-fetched. Empty responses are never recorded as coverage, so a transient empty answer cannot
poison the cache.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pandas as pd
from sqlalchemy import and_, delete, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.timeutils import local_to_utc, now_utc
from app.models.market_data import FetchCoverage, WindActualRecord, WindForecastRecord
from app.services.data_normalization import actuals_to_frame, forecasts_to_frame
from app.services.elexon_client import ActualRow, ElexonClient, ForecastRow

logger = logging.getLogger(__name__)

DS_FORECAST = "WINDFOR"
DS_ACTUAL = "FUELHH"
FORECAST_SETTLE_MARGIN = timedelta(hours=1)
ACTUAL_SETTLE_MARGIN = timedelta(hours=24)  # outturn can be refreshed shortly after the period

ProgressCb = Callable[[int, int, str], None]


@dataclass
class FetchStats:
    requests_made: int = 0
    cache_hits: int = 0
    rows_fetched: int = 0
    rows_dropped_malformed: int = 0
    rows_dropped_other_fuel: int = 0

    def merge(self, other: FetchStats) -> None:
        self.requests_made += other.requests_made
        self.cache_hits += other.cache_hits
        self.rows_fetched += other.rows_fetched
        self.rows_dropped_malformed += other.rows_dropped_malformed
        self.rows_dropped_other_fuel += other.rows_dropped_other_fuel


def _utc_chunks(start: datetime, end: datetime, kind: str) -> Iterator[tuple[datetime, datetime]]:
    """Inclusive UTC chunks covering exactly [start, end], split at UTC day or month boundaries."""
    if kind not in ("day", "month"):
        raise ValueError(kind)
    cur = start
    while cur <= end:
        if kind == "day":
            boundary = datetime.combine(cur.date() + timedelta(days=1), time(0), tzinfo=cur.tzinfo)
        else:
            y, m = (cur.year + 1, 1) if cur.month == 12 else (cur.year, cur.month + 1)
            boundary = datetime(y, m, 1, tzinfo=cur.tzinfo)
        yield cur, min(end, boundary - timedelta(seconds=1))
        cur = boundary


def _date_chunks(start: date, end: date, kind: str) -> Iterator[tuple[date, date]]:
    """Inclusive date chunks covering exactly [start, end], split at day or month boundaries."""
    cur = start
    while cur <= end:
        if kind == "day":
            nxt = cur + timedelta(days=1)
        else:
            nxt = date(cur.year + (cur.month == 12), 1 if cur.month == 12 else cur.month + 1, 1)
        yield cur, min(end, nxt - timedelta(days=1))
        cur = nxt


class MarketDataStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        client: ElexonClient,
        clock: Callable[[], datetime] = now_utc,
    ):
        self._sf = session_factory
        self._client = client
        self._clock = clock

    # ----------------------------------------------------------------- coverage helpers

    def _is_covered(self, session: Session, dataset: str, start: datetime, end: datetime) -> bool:
        stmt = (
            select(FetchCoverage.id)
            .where(
                and_(
                    FetchCoverage.dataset == dataset,
                    FetchCoverage.range_start <= start,
                    FetchCoverage.range_end >= end,
                )
            )
            .limit(1)
        )
        return session.execute(stmt).first() is not None

    def _record_coverage(
        self, session: Session, dataset: str, start: datetime, end: datetime, count: int, margin: timedelta
    ) -> None:
        now = self._clock()
        if count > 0 and now >= end + margin:
            session.add(
                FetchCoverage(dataset=dataset, range_start=start, range_end=end, fetched_at=now, row_count=count)
            )

    # ----------------------------------------------------------------- forecasts

    def get_forecast_vintages(
        self,
        publish_from: datetime,
        publish_to: datetime,
        *,
        chunk: str = "month",
        progress: ProgressCb | None = None,
    ) -> tuple[pd.DataFrame, FetchStats]:
        """All forecast rows published within [publish_from, publish_to] (inclusive)."""
        stats = FetchStats()
        chunks = list(_utc_chunks(publish_from, publish_to, chunk))
        for i, (c_start, c_end) in enumerate(chunks):
            with self._sf() as session:
                if self._is_covered(session, DS_FORECAST, c_start, c_end):
                    stats.cache_hits += 1
                else:
                    result = self._client.fetch_wind_forecasts(c_start, c_end)
                    stats.requests_made += result.requests_made
                    stats.rows_fetched += len(result.rows)
                    stats.rows_dropped_malformed += result.dropped_malformed
                    self._store_forecasts(session, c_start, c_end, result.rows)
            if progress:
                progress(i + 1, len(chunks), f"Forecast vintages {c_start.date()}")

        with self._sf() as session:
            stmt = (
                select(WindForecastRecord.publish_time, WindForecastRecord.start_time, WindForecastRecord.generation_mw)
                .where(WindForecastRecord.publish_time >= publish_from, WindForecastRecord.publish_time <= publish_to)
                .order_by(WindForecastRecord.publish_time, WindForecastRecord.start_time)
            )
            rows = [ForecastRow(p, s, g) for p, s, g in session.execute(stmt).all()]
        return forecasts_to_frame(rows), stats

    def _store_forecasts(self, session: Session, c_start: datetime, c_end: datetime, rows: list[ForecastRow]) -> None:
        try:
            session.execute(
                delete(WindForecastRecord).where(
                    WindForecastRecord.publish_time >= c_start, WindForecastRecord.publish_time <= c_end
                )
            )
            unique = {(r.publish_time, r.start_time): r for r in rows}
            if unique:
                session.execute(
                    insert(WindForecastRecord),
                    [
                        {"publish_time": r.publish_time, "start_time": r.start_time, "generation_mw": r.generation_mw}
                        for r in unique.values()
                    ],
                )
            self._record_coverage(session, DS_FORECAST, c_start, c_end, len(unique), FORECAST_SETTLE_MARGIN)
            session.commit()
        except IntegrityError:
            # A concurrent writer stored the same immutable chunk first; the data is identical.
            session.rollback()
            logger.info("Concurrent forecast chunk write detected for %s; continuing", c_start.date())

    # ----------------------------------------------------------------- actuals

    @staticmethod
    def _actual_utc_bounds(d_from: date, d_to: date) -> tuple[datetime, datetime]:
        start = local_to_utc(d_from, time(0))
        end_exclusive = local_to_utc(d_to + timedelta(days=1), time(0))
        return start, end_exclusive

    def get_half_hourly_actuals(
        self,
        settlement_from: date,
        settlement_to: date,
        *,
        chunk: str = "month",
        progress: ProgressCb | None = None,
    ) -> tuple[pd.DataFrame, FetchStats]:
        """Half-hourly WIND outturn for UK settlement dates [settlement_from, settlement_to]."""
        stats = FetchStats()
        chunks = list(_date_chunks(settlement_from, settlement_to, chunk))
        for i, (d_lo, d_hi) in enumerate(chunks):
            lo_utc, hi_excl = self._actual_utc_bounds(d_lo, d_hi)
            hi_incl = hi_excl - timedelta(seconds=1)
            with self._sf() as session:
                if self._is_covered(session, DS_ACTUAL, lo_utc, hi_incl):
                    stats.cache_hits += 1
                else:
                    result = self._client.fetch_wind_actuals(d_lo, d_hi)
                    stats.requests_made += result.requests_made
                    stats.rows_fetched += len(result.rows)
                    stats.rows_dropped_malformed += result.dropped_malformed
                    stats.rows_dropped_other_fuel += result.dropped_other_fuel
                    self._store_actuals(session, lo_utc, hi_excl, hi_incl, result.rows)
            if progress:
                progress(i + 1, len(chunks), f"Actual generation {d_lo}")

        lo, hi_excl = self._actual_utc_bounds(settlement_from, settlement_to)
        with self._sf() as session:
            stmt = (
                select(
                    WindActualRecord.start_time,
                    WindActualRecord.settlement_date,
                    WindActualRecord.settlement_period,
                    WindActualRecord.publish_time,
                    WindActualRecord.generation_mw,
                )
                .where(WindActualRecord.start_time >= lo, WindActualRecord.start_time < hi_excl)
                .order_by(WindActualRecord.start_time)
            )
            rows = [ActualRow(s, sd, sp, p, g) for s, sd, sp, p, g in session.execute(stmt).all()]
        return actuals_to_frame(rows), stats

    def _store_actuals(
        self, session: Session, lo: datetime, hi_excl: datetime, hi_incl: datetime, rows: list[ActualRow]
    ) -> None:
        try:
            session.execute(
                delete(WindActualRecord).where(WindActualRecord.start_time >= lo, WindActualRecord.start_time < hi_excl)
            )
            # Keep the most recently published row per start_time (the API should not repeat them).
            unique: dict[datetime, ActualRow] = {}
            for r in sorted(rows, key=lambda r: r.publish_time or r.start_time):
                if lo <= r.start_time < hi_excl:
                    unique[r.start_time] = r
            if unique:
                session.execute(
                    insert(WindActualRecord),
                    [
                        {
                            "start_time": r.start_time,
                            "settlement_date": r.settlement_date,
                            "settlement_period": r.settlement_period,
                            "publish_time": r.publish_time,
                            "generation_mw": r.generation_mw,
                        }
                        for r in unique.values()
                    ],
                )
            self._record_coverage(session, DS_ACTUAL, lo, hi_incl, len(unique), ACTUAL_SETTLE_MARGIN)
            session.commit()
        except IntegrityError:
            session.rollback()
            logger.info("Concurrent actuals chunk write detected for %s; continuing", lo.date())

