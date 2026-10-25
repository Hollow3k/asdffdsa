from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_container
from app.container import Container
from app.schemas.common import ErrorEnvelope
from app.schemas.decision import DecisionResponse, EvaluationResponse
from app.schemas.procurement import ProcurementRequest, ProcurementResponse

router = APIRouter(prefix="/api/decisions", tags=["decisions"])

_ERR: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
    502: {"model": ErrorEnvelope},
}

CutoffQuery = Query(
    "17:00",
    pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
    description="UK wall-clock time on the day BEFORE the delivery date: the latest forecast publication allowed (HH:MM)",
)
PercentileQuery = Query(95.0, ge=50, le=99, description="Conservatism of the shortfall buffer (e.g. 90 or 95)")
CalibrationQuery = Query(None, description="Use a specific completed calibration instead of the active one")


@router.get(
    "/{delivery_date}",
    response_model=DecisionResponse,
    responses=_ERR,
    summary="Decision support for a delivery day using the forecast available at the cutoff",
)
def get_decision(
    delivery_date: date,
    cutoff: str = CutoffQuery,
    percentile: float = PercentileQuery,
    calibration_id: str | None = CalibrationQuery,
    container: Container = Depends(get_container),
) -> DecisionResponse:
    return container.decisions.analyze(delivery_date, cutoff, percentile, calibration_id)


@router.post(
    "/{delivery_date}/procurement",
    response_model=ProcurementResponse,
    responses=_ERR,
    summary="Purchase volume needed on top of wind and existing contracts to meet the supplied demand",
)
def post_procurement(
    delivery_date: date,
    body: ProcurementRequest,
    container: Container = Depends(get_container),
) -> ProcurementResponse:
    return container.decisions.plan(delivery_date, body)


@router.get(
    "/{delivery_date}/evaluation",
    response_model=EvaluationResponse,
    responses=_ERR,
    summary="Retrospective: the eligible forecast versus realised generation",
)
def get_evaluation(
    delivery_date: date,
    cutoff: str = CutoffQuery,
    percentile: float = PercentileQuery,
    calibration_id: str | None = CalibrationQuery,
    container: Container = Depends(get_container),
) -> EvaluationResponse:
    return container.decisions.evaluate(delivery_date, cutoff, percentile, calibration_id)
