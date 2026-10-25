"""Calibration versions: creation, background execution, activation.

Design notes
------------
* Long-running work happens in a single background worker thread; the browser polls
  ``GET /api/calibrations/{id}`` for ``progress``/``stage``. A distributed queue is unnecessary.
* Only one calibration job may be pending/running at a time (checked in the database, so it also
  holds across restarts; run a single backend process - see README).
* A calibration version is created ``pending`` and either ends ``completed`` (with metrics and
  observations committed atomically) or ``failed``. A failure never modifies any other version, so
  the previously active calibration stays intact.
* The first successful calibration is auto-activated when none is active; afterwards a new
  version must be activated explicitly after review.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import Executor, ThreadPoolExecutor
from datetime import date, time
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.core.errors import AppError, Conflict, NoDataError, NotFound, ValidationFailed
from app.core.timeutils import now_utc, parse_hhmm, previous_day_cutoff_utc, today_uk
from app.models.calibration import (
    ACTIVE_JOB_STATUSES,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    Calibration,
    CalibrationObservation,
)
from app.services.calibration import build_calibration_dataset, compute_breakdowns, validate_calibration_range
from app.services.data_normalization import aggregate_actuals_hourly
from app.services.data_store import FetchStats, MarketDataStore
from app.services.forecast_selection import DEFAULT_MAX_VINTAGE_AGE, POLICY_LATEST_COMPLETE, VALID_POLICIES
from app.services.metrics import METRIC_DEFINITIONS, METRIC_VERSION, compute_error_metrics

logger = logging.getLogger(__name__)


class CalibrationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        store: MarketDataStore,
        settings: Settings,
        executor: Executor | None = None,
        run_inline: bool = False,
    ):
        self._sf = session_factory
        self._store = store
        self._settings = settings
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="calibration")
        self._run_inline = run_inline

    # ------------------------------------------------------------------ lifecycle

    def recover_interrupted(self) -> int:
        """Mark jobs left pending/running by a previous process as failed. Active versions are untouched."""
        with self._sf() as s:
            res = s.execute(
                update(Calibration)
                .where(Calibration.status.in_(ACTIVE_JOB_STATUSES))
                .values(
                    status=STATUS_FAILED,
                    error_code="INTERRUPTED",
                    error_message="Calibration was interrupted by an application restart. Run it again.",
                    stage="Interrupted",
                    completed_at=now_utc(),
                )
            )
            s.commit()
            n = getattr(res, "rowcount", 0) or 0
        if n:
            logger.warning("Marked %d interrupted calibration job(s) as failed", n)
        return n

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)

    # ------------------------------------------------------------------ submit

    def submit(
        self,
        start_date: date,
        end_date: date,
        cutoff_time: str | None = None,
        policy: str = POLICY_LATEST_COMPLETE,
    ) -> Calibration:
        cutoff_str = cutoff_time or self._settings.default_cutoff_time
        try:
            parse_hhmm(cutoff_str)  # validate only
        except ValueError as exc:
            raise ValidationFailed(str(exc), details={"field": "cutoff_time"}) from exc
        if policy not in VALID_POLICIES:
            raise ValidationFailed(f"Unknown forecast selection policy {policy!r}", details={"field": "policy"})
        validate_calibration_range(
            start_date, end_date, today=today_uk(), max_days=self._settings.max_calibration_days
        )

        with self._sf() as s:
            busy = s.execute(
                select(Calibration.id, Calibration.version).where(Calibration.status.in_(ACTIVE_JOB_STATUSES))
            ).first()
            if busy:
                raise Conflict(
                    f"Calibration version {busy.version} is still running; wait for it to finish.",
                    details={"running_calibration_id": busy.id},
                    code="CALIBRATION_IN_PROGRESS",
                )
            next_version = (s.execute(select(func.max(Calibration.version))).scalar() or 0) + 1
            cal = Calibration(
                id=str(uuid.uuid4()),
                version=next_version,
                status=STATUS_PENDING,
                is_active=False,
                start_date=start_date,
                end_date=end_date,
                cutoff_time=cutoff_str,
                metric_version=METRIC_VERSION,
                settings={
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "cutoff_time": cutoff_str,
                    "cutoff_rule": "previous UK day at cutoff_time",
                    "timezone": "Europe/London",
                    "forecast_selection_policy": policy,
                    "max_vintage_age_hours": DEFAULT_MAX_VINTAGE_AGE.total_seconds() / 3600,
                    "forecast_dataset": "WINDFOR",
                    "actual_dataset": "FUELHH (fuelType=WIND)",
                    "actual_aggregation": "hourly mean of two half-hourly MW observations",
                    "error_convention": "forecast_mw - actual_mw",
                    "percentile_method": "linear interpolation (numpy type 7)",
                    "metric_definitions": METRIC_DEFINITIONS,
                },
                progress=0,
                stage="Queued",
                created_at=now_utc(),
            )
            s.add(cal)
            try:
                s.commit()
            except Exception as exc:  # unique index race with a concurrent submit
                s.rollback()
                raise Conflict("Another calibration was created at the same time; retry.") from exc
            s.refresh(cal)

        if self._run_inline:
            self.run_job(cal.id)
        else:
            self._executor.submit(self._safe_run, cal.id)
        return cal

    def _safe_run(self, calibration_id: str) -> None:
        try:
            self.run_job(calibration_id)
        except Exception:  # pragma: no cover - run_job records failures itself
            logger.exception("Unhandled error in calibration worker")

    # ------------------------------------------------------------------ execute

    def _update(self, calibration_id: str, **values: Any) -> None:
        with self._sf() as s:
            s.execute(update(Calibration).where(Calibration.id == calibration_id).values(**values))
            s.commit()

    def run_job(self, calibration_id: str) -> None:
        with self._sf() as s:
            cal = s.get(Calibration, calibration_id)
            if cal is None:
                raise NotFound(f"Calibration {calibration_id} not found")
            start, end = cal.start_date, cal.end_date
            cutoff = parse_hhmm(cal.cutoff_time)
            policy = (cal.settings or {}).get("forecast_selection_policy", POLICY_LATEST_COMPLETE)
        self._update(calibration_id, status=STATUS_RUNNING, started_at=now_utc(), progress=2, stage="Starting")
        logger.info("Calibration %s started: %s..%s cutoff %s", calibration_id, start, end, cal.cutoff_time)
        try:
            self._execute(calibration_id, start, end, cutoff, policy)
        except AppError as exc:
            logger.warning("Calibration %s failed: [%s] %s", calibration_id, exc.code, exc.message)
            self._fail(calibration_id, exc.code, exc.message)
        except Exception:
            logger.exception("Calibration %s failed unexpectedly", calibration_id)
            self._fail(calibration_id, "INTERNAL_ERROR", "Unexpected error while calculating the calibration. See server logs.")

    def _fail(self, calibration_id: str, code: str, message: str) -> None:
        self._update(
            calibration_id,
            status=STATUS_FAILED,
            error_code=code,
            error_message=message[:2000],
            stage="Failed",
            completed_at=now_utc(),
            is_active=False,
        )

    def _execute(self, calibration_id: str, start: date, end: date, cutoff: time, policy: str) -> None:
        stats = FetchStats()

        def progress_scaled(lo: int, hi: int):
            def cb(done: int, total: int, label: str) -> None:
                pct = lo + int((hi - lo) * done / max(total, 1))
                self._update(calibration_id, progress=pct, stage=f"Fetching {label}")

            return cb

        # --- actual generation (settlement dates are UK dates, same as delivery dates)
        self._update(calibration_id, progress=5, stage="Fetching actual generation (FUELHH)")
        half_hourly, s1 = self._store.get_half_hourly_actuals(start, end, progress=progress_scaled(5, 35))
        stats.merge(s1)
        if half_hourly.empty:
            raise NoDataError(
                "Elexon returned no wind outturn (FUELHH) data for the selected range",
                details={"start_date": start.isoformat(), "end_date": end.isoformat()},
            )

        # --- forecast vintages that could have been available at any of the daily cutoffs
        pub_from = previous_day_cutoff_utc(start, cutoff) - DEFAULT_MAX_VINTAGE_AGE
        pub_to = previous_day_cutoff_utc(end, cutoff)
        self._update(calibration_id, progress=35, stage="Fetching forecast vintages (WINDFOR)")
        vintages, s2 = self._store.get_forecast_vintages(pub_from, pub_to, progress=progress_scaled(35, 75))
        stats.merge(s2)
        if vintages.empty:
            raise NoDataError(
                "Elexon returned no wind forecast (WINDFOR) vintages for the selected range",
                details={"publish_from": pub_from.isoformat(), "publish_to": pub_to.isoformat()},
            )

        # --- align + metrics
        self._update(calibration_id, progress=80, stage="Aligning forecasts with actuals")
        hourly = aggregate_actuals_hourly(half_hourly)
        dataset = build_calibration_dataset(
            vintages,
            hourly,
            start,
            end,
            cutoff,
            policy=policy,
            low_sample_pairs=self._settings.low_sample_pairs,
            fetch_stats=stats.__dict__.copy(),
        )
        obs = dataset.observations
        if len(obs) < self._settings.min_calibration_pairs:
            raise NoDataError(
                f"Only {len(obs)} matched hourly pairs were found; at least "
                f"{self._settings.min_calibration_pairs} are needed for a usable calibration",
                details={"matched_pairs": len(obs), "quality": dataset.quality},
            )

        self._update(calibration_id, progress=88, stage="Computing error metrics")
        metrics = compute_error_metrics(obs["forecast_mw"].to_numpy(), obs["actual_mw"].to_numpy()).to_dict()
        metrics["n_matched"] = dataset.quality["matched_pairs"]
        metrics["n_unmatched"] = dataset.quality["unmatched_hours"]
        breakdowns = compute_breakdowns(obs, low_sample_bucket=self._settings.low_sample_bucket)

        # --- persist atomically
        self._update(calibration_id, progress=94, stage="Saving results")
        records = [
            {
                "calibration_id": calibration_id,
                "delivery_start": r.delivery_start.to_pydatetime(),
                "delivery_date": r.delivery_date,
                "hour_local": int(r.hour_local),
                "forecast_mw": float(r.forecast_mw),
                "actual_mw": float(r.actual_mw),
                "error_mw": float(r.error_mw),
                "forecast_publish_time": r.forecast_publish_time.to_pydatetime(),
                "decision_cutoff": r.decision_cutoff.to_pydatetime(),
                "actual_available_at": r.actual_available_at.to_pydatetime(),
            }
            for r in obs.itertuples(index=False)
        ]
        with self._sf() as s:
            s.execute(insert(CalibrationObservation), records)
            s.execute(
                update(Calibration)
                .where(Calibration.id == calibration_id)
                .values(
                    status=STATUS_COMPLETED,
                    progress=100,
                    stage="Completed",
                    completed_at=now_utc(),
                    metrics=metrics,
                    breakdowns=breakdowns,
                    quality=dataset.quality,
                    warnings=dataset.warnings,
                )
            )
            no_active = s.execute(select(func.count()).select_from(Calibration).where(Calibration.is_active)).scalar() == 0
            if no_active:
                s.execute(
                    update(Calibration)
                    .where(Calibration.id == calibration_id)
                    .values(is_active=True, activated_at=now_utc())
                )
            s.commit()
        logger.info("Calibration %s completed with %d pairs", calibration_id, len(obs))

    # ------------------------------------------------------------------ activate / read

    def activate(self, calibration_id: str) -> Calibration:
        with self._sf() as s:
            cal = s.get(Calibration, calibration_id)
            if cal is None:
                raise NotFound(f"Calibration {calibration_id} not found")
            if cal.status != STATUS_COMPLETED:
                raise Conflict(
                    f"Only completed calibrations can be activated (this one is {cal.status})",
                    code="CALIBRATION_NOT_COMPLETED",
                )
            if cal.is_active:
                return cal
            # Deactivate first so the partial unique index (one active row) is never violated.
            s.execute(update(Calibration).where(Calibration.is_active).values(is_active=False))
            cal.is_active = True
            cal.activated_at = now_utc()
            s.commit()
            s.refresh(cal)
            logger.info("Calibration %s (v%d) activated", cal.id, cal.version)
            return cal
