from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_session
from app.container import Container
from app.core.errors import NotFound
from app.models.calibration import Calibration, CalibrationObservation
from app.schemas.calibration import (
    Breakdowns,
    CalibrationCreate,
    CalibrationDetail,
    CalibrationSummary,
    ObservationOut,
    ObservationPage,
)
from app.schemas.common import ErrorEnvelope, ErrorMetricsOut

router = APIRouter(prefix="/api/calibrations", tags=["calibrations"])

_ERR: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}


def _summary(c: Calibration) -> CalibrationSummary:
    metrics = c.metrics or {}
    return CalibrationSummary(
        id=c.id,
        version=c.version,
        status=c.status,
        is_active=c.is_active,
        start_date=c.start_date,
        end_date=c.end_date,
        cutoff_time=c.cutoff_time,
        metric_version=c.metric_version,
        progress=c.progress,
        stage=c.stage,
        error_code=c.error_code,
        error_message=c.error_message,
        created_at=c.created_at,
        started_at=c.started_at,
        completed_at=c.completed_at,
        activated_at=c.activated_at,
        n_matched=metrics.get("n_matched"),
        n_unmatched=metrics.get("n_unmatched"),
        warning_count=len(c.warnings or []),
    )


def _detail(c: Calibration, low_sample_pairs: int) -> CalibrationDetail:
    base = _summary(c).model_dump()
    n = (c.metrics or {}).get("n") or 0
    note = None
    if c.status == "completed" and n < low_sample_pairs:
        note = f"Only {n} matched hours (< {low_sample_pairs}): treat tail percentiles as low-confidence."
    return CalibrationDetail(
        **base,
        settings=c.settings or {},
        metrics=ErrorMetricsOut.model_validate(c.metrics) if c.metrics else None,
        breakdowns=Breakdowns.model_validate(c.breakdowns) if c.breakdowns else None,
        quality=c.quality,
        warnings=c.warnings or [],
        sample_size_note=note,
    )


@router.get("", response_model=list[CalibrationSummary], summary="List calibration versions (newest first)")
def list_calibrations(session: Session = Depends(get_session)) -> list[CalibrationSummary]:
    rows = session.execute(select(Calibration).order_by(Calibration.version.desc())).scalars().all()
    return [_summary(c) for c in rows]


@router.get(
    "/active",
    response_model=CalibrationDetail,
    responses=_ERR,
    summary="The active calibration (404 NO_ACTIVE_CALIBRATION on first run)",
)
def active_calibration(
    session: Session = Depends(get_session), container: Container = Depends(get_container)
) -> CalibrationDetail:
    cal = session.execute(select(Calibration).where(Calibration.is_active)).scalar_one_or_none()
    if cal is None:
        raise NotFound("No active calibration exists yet", code="NO_ACTIVE_CALIBRATION")
    return _detail(cal, container.settings.low_sample_pairs)


@router.post(
    "",
    response_model=CalibrationSummary,
    status_code=202,
    responses=_ERR,
    summary="Start a calibration run for a historical range (asynchronous)",
)
def create_calibration(body: CalibrationCreate, container: Container = Depends(get_container)) -> CalibrationSummary:
    cal = container.calibrations.submit(
        body.start_date, body.end_date, body.cutoff_time, body.forecast_selection_policy
    )
    # In inline mode (tests) the job has finished already; re-read for the latest state.
    with container.session_factory() as s:
        fresh = s.get(Calibration, cal.id)
        assert fresh is not None
        return _summary(fresh)


@router.get("/{calibration_id}", response_model=CalibrationDetail, responses=_ERR, summary="Inspect a calibration version")
def get_calibration(
    calibration_id: str, session: Session = Depends(get_session), container: Container = Depends(get_container)
) -> CalibrationDetail:
    cal = session.get(Calibration, calibration_id)
    if cal is None:
        raise NotFound(f"Calibration {calibration_id} not found")
    return _detail(cal, container.settings.low_sample_pairs)


@router.get(
    "/{calibration_id}/observations",
    response_model=ObservationPage,
    responses=_ERR,
    summary="Matched hourly forecast/actual pairs stored with a calibration",
)
def get_observations(
    calibration_id: str,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> ObservationPage:
    if session.get(Calibration, calibration_id) is None:
        raise NotFound(f"Calibration {calibration_id} not found")
    total = session.execute(
        select(func.count()).select_from(CalibrationObservation).where(CalibrationObservation.calibration_id == calibration_id)
    ).scalar_one()
    rows = (
        session.execute(
            select(CalibrationObservation)
            .where(CalibrationObservation.calibration_id == calibration_id)
            .order_by(CalibrationObservation.delivery_start)
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return ObservationPage(
        total=total, limit=limit, offset=offset, items=[ObservationOut.model_validate(r) for r in rows]
    )


@router.post(
    "/{calibration_id}/activate",
    response_model=CalibrationDetail,
    responses=_ERR,
    summary="Make a completed calibration version the active one",
)
def activate_calibration(calibration_id: str, container: Container = Depends(get_container)) -> CalibrationDetail:
    cal = container.calibrations.activate(calibration_id)
    return _detail(cal, container.settings.low_sample_pairs)
