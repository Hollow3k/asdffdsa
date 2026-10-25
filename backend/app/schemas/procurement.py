from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from pydantic import Field, model_validator

from app.schemas.common import ApiModel, QualityWarning
from app.schemas.decision import CalibrationRef, CutoffInfo, ForecastInfo

MAX_MW = 1_000_000
Mw = Annotated[float, Field(ge=0, le=MAX_MW, allow_inf_nan=False)]


class ProcurementRequest(ApiModel):
    """User-supplied position. Nothing is calculated unless demand is provided."""

    cutoff: str = Field(default="17:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    percentile: float = Field(default=95.0, ge=50, le=99)
    calibration_id: str | None = None

    demand_mw: Mw | None = Field(default=None, description="Flat expected demand applied to every hour (MW)")
    demand_by_hour_mw: list[Mw] | None = Field(
        default=None, description="Expected demand per UK-local delivery hour, in order (MW)"
    )
    contracted_mw: Mw = Field(default=0.0, description="Existing contracted supply, flat across hours (MW)")
    contracted_by_hour_mw: list[Mw] | None = None
    wind_share_pct: float = Field(
        default=100.0,
        ge=0,
        le=100,
        allow_inf_nan=False,
        description="Share of GB national wind output you can count on (%)",
    )

    @model_validator(mode="after")
    def _one_demand(self) -> ProcurementRequest:
        if (self.demand_mw is None) == (self.demand_by_hour_mw is None):
            raise ValueError("provide exactly one of demand_mw or demand_by_hour_mw")
        return self


class PlanHour(ApiModel):
    start_utc: datetime
    local_label: str
    hour_local: int
    demand_mw: float
    contracted_mw: float
    planned: bool  # False when the forecast has no value for this hour
    wind_forecast_mw: float | None = None  # all wind figures already scaled by the wind share
    wind_expected_mw: float | None = None
    wind_cautious_mw: float | None = None
    buy_forecast_mw: float | None = None
    buy_expected_mw: float | None = None
    buy_cautious_mw: float | None = None
    surplus_forecast_mw: float | None = None
    surplus_expected_mw: float | None = None
    surplus_cautious_mw: float | None = None


class PlanScenario(ApiModel):
    key: str  # forecast | expected | cautious
    label: str
    description: str
    buy_total_mwh: float
    avg_buy_mw: float
    peak_buy_mw: float
    peak_buy_hour: str | None
    hours_with_buy: int
    wind_total_mwh: float
    wind_used_mwh: float
    wind_cover_pct: float | None  # share of net-of-contracts demand covered by wind
    surplus_wind_mwh: float
    hours_with_surplus: int


class ProcurementResponse(ApiModel):
    delivery_date: date
    cutoff: CutoffInfo
    percentile: float
    recommended_basis: str
    wind_share_pct: float
    demand_total_mwh: float
    contracted_total_mwh: float
    hours_total: int
    hours_planned: int
    hours_unplanned: int
    scenarios: list[PlanScenario]
    risk_cover_mwh: float  # cautious purchase minus expected purchase
    hours: list[PlanHour]
    forecast: ForecastInfo
    calibration: CalibrationRef
    assumptions: list[str]
    warnings: list[QualityWarning]
    generated_at: datetime
