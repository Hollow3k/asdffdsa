"""Decision support and retrospective evaluation for a January delivery day.

Decision-time correctness
-------------------------
For a delivery date ``D`` and cutoff time ``T``:

* decision instant = ``T`` UK time on day ``D-1``;
* only forecast vintages published at or before that instant are even loaded from the store;
* only calibration observations whose *actual* outturn was published at or before that instant are
  used. A stored calibration that extends beyond the decision instant (e.g. a calibration ending
  31 Dec used for a 1 Jan decision, or a custom range running into January) is trimmed to what was
  knowable and the trimming is disclosed. If too little remains the request fails with an explicit
  explanation instead of silently using the future.

Realised actuals are only used by :meth:`DecisionService.evaluate`, which is explicitly
retrospective and never feeds the decision itself.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.core.errors import (
    CalibrationUnavailable,
    FutureDataLeakageError,
    NoEligibleForecast,
    NotFound,
    ValidationFailed,
)
from app.core.timeutils import (
    TIMEZONE_NAME,
    local_day_hours_utc,
    now_utc,
    parse_hhmm,
    previous_day_cutoff_utc,
    uk_date_of,
    uk_iso,
    uk_label,
)
from app.core.timeutils import to_uk as _to_uk
from app.models.calibration import STATUS_COMPLETED, Calibration, CalibrationObservation
from app.schemas.common import ErrorMetricsOut, QualityWarning
from app.schemas.decision import (
    CalibrationRef,
    CutoffInfo,
    DecisionResponse,
    EvaluationHour,
    EvaluationResponse,
    EvaluationSummary,
    Explanation,
    ForecastHour,
    ForecastInfo,
    RiskAssessment,
)
from app.schemas.procurement import ProcurementRequest, ProcurementResponse
from app.services.data_normalization import aggregate_actuals_hourly
from app.services.data_store import MarketDataStore
from app.services.forecast_selection import (
    DEFAULT_MAX_VINTAGE_AGE,
    POLICY_LATEST_COMPLETE,
    ForecastSelection,
    select_forecast,
)
from app.services.metrics import METRIC_DEFINITIONS, ErrorMetrics, compute_error_metrics
from app.services.procurement import build_plan

logger = logging.getLogger(__name__)

SOURCE_LABEL = "Elexon Insights Solution (BMRS) - WINDFOR national wind forecast"

LIMITATIONS = [
    "Elexon wind data alone cannot determine what to buy: demand, existing contract cover and your share of "
    "wind come from you, and other generation, prices, imbalance costs and your risk policy are not included.",
    "The shortfall buffer applies one historical error distribution to every hour. In reality errors "
    "depend on the wind level, season, hour and weather regime, and are correlated across hours.",
    "Calibration is a retrospective sample; a different period (or a rarer weather regime) can give "
    "larger errors than the percentile suggests. Treat P95 as an indicator, not a guarantee.",
    "National aggregates hide regional and transmission-constraint effects.",
    "This is decision support, not a definitive purchase order.",
]

PROCUREMENT_NOTE = (
    "These figures are GB-wide wind forecast uncertainty. A purchase volume is only calculated from demand "
    "(and optional contracted supply and wind share) that you enter yourself; electricity prices, imbalance "
    "costs and your risk policy are not in the Elexon data and are not modelled."
)


# ---------------------------------------------------------------------------
# Pure helpers (independently tested)
# ---------------------------------------------------------------------------


def filter_observations_available_at(obs: pd.DataFrame, cutoff_utc: datetime) -> tuple[pd.DataFrame, int]:
    """Keep only calibration observations that were fully knowable at ``cutoff_utc``.

    An observation is knowable when its actual outturn had been published (``actual_available_at``)
    and the forecast that was paired with it had been published (``forecast_publish_time``) by the
    cutoff. Returns (kept, number_excluded).
    """
    if obs.empty:
        return obs, 0
    cutoff_ts = pd.Timestamp(cutoff_utc)
    mask = (obs["actual_available_at"] <= cutoff_ts) & (obs["forecast_publish_time"] <= cutoff_ts)
    kept = obs[mask]
    assert_no_leakage(kept, cutoff_utc)
    return kept, int((~mask).sum())


def assert_no_leakage(obs: pd.DataFrame, cutoff_utc: datetime) -> None:
    """Raise if any observation used for a decision postdates the decision instant."""
    if obs.empty:
        return
    cutoff_ts = pd.Timestamp(cutoff_utc)
    if (obs["actual_available_at"] > cutoff_ts).any() or (obs["forecast_publish_time"] > cutoff_ts).any():
        raise FutureDataLeakageError(
            "Calibration data published after the decision cutoff was about to be used",
            details={"cutoff": cutoff_utc.isoformat()},
        )


def compute_risk_adjustments(
    forecast_mw: list[float | None], errors: np.ndarray, pct: float
) -> dict[str, Any]:
    """Shortfall quantile / buffer / bias adjustment and per-hour adjusted values.

    Everything derives from the signed error ``forecast - actual``:

    * ``bias``  = mean(error). Expected actual = forecast - bias  (bias adjustment = -bias).
    * ``Q``     = pct-th percentile of error over ALL hours. In pct% of historical hours the actual was
      no more than Q MW below the forecast. ``buffer = max(0, Q)``.
    * conservative estimate = forecast - buffer (floored at 0 MW).

    The buffer is measured from the *unadjusted* forecast, and the bias adjustment is a component of
    it (``buffer = bias + residual``), so applying both would count the bias twice. They are shown
    as separate steps, never summed on top of each other.
    """
    if errors.size == 0:
        raise ValueError("no calibration errors")
    q_hi = float(np.percentile(errors, pct))
    q_lo = float(np.percentile(errors, 100.0 - pct))
    bias = float(errors.mean())
    buffer = max(0.0, q_hi)

    adjusted: list[float | None] = []
    conservative: list[float | None] = []
    low: list[float | None] = []
    high: list[float | None] = []
    floored = 0
    for f in forecast_mw:
        if f is None:
            adjusted.append(None)
            conservative.append(None)
            low.append(None)
            high.append(None)
            continue
        adjusted.append(max(0.0, f - bias))
        raw_cons = f - buffer
        if raw_cons < 0:
            floored += 1
        conservative.append(max(0.0, raw_cons))
        low.append(max(0.0, f - q_hi))
        high.append(max(0.0, f - q_lo))
    return {
        "q_hi": q_hi,
        "q_lo": q_lo,
        "bias": bias,
        "buffer": buffer,
        "adjusted": adjusted,
        "conservative": conservative,
        "low": low,
        "high": high,
        "floored": floored,
    }


def _mean(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return float(np.mean(vals)) if vals else None


def _fmt_date(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def _metrics_out(m: ErrorMetrics, **extra: Any) -> ErrorMetricsOut:
    return ErrorMetricsOut(**m.to_dict(), **extra)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class DecisionService:
    def __init__(self, session_factory: sessionmaker[Session], store: MarketDataStore, settings: Settings):
        self._sf = session_factory
        self._store = store
        self._settings = settings

    # ----------------------------------------------------------- validation

    def validate_inputs(self, delivery_date: date, cutoff_time: str, pct: float | None = None) -> time:
        s = self._settings
        if not (s.decision_window_start <= delivery_date <= s.decision_window_end):
            raise ValidationFailed(
                f"Delivery date must be between {s.decision_window_start.isoformat()} and "
                f"{s.decision_window_end.isoformat()} for this simulation",
                details={"field": "delivery_date", "code": "DELIVERY_DATE_OUT_OF_RANGE"},
                code="DELIVERY_DATE_OUT_OF_RANGE",
            )
        try:
            cutoff = parse_hhmm(cutoff_time)
        except ValueError as exc:
            raise ValidationFailed(str(exc), details={"field": "cutoff"}, code="INVALID_CUTOFF") from exc
        if pct is not None and not (50.0 <= pct <= 99.0):
            raise ValidationFailed(
                "Percentile must be between 50 and 99", details={"field": "percentile"}, code="INVALID_PERCENTILE"
            )
        return cutoff

    # ----------------------------------------------------------- forecast

    def _select_forecast(self, delivery_date: date, cutoff: time) -> tuple[list[datetime], datetime, ForecastSelection]:
        hours = local_day_hours_utc(delivery_date)
        cutoff_utc = previous_day_cutoff_utc(delivery_date, cutoff)
        # Only vintages published at or before the cutoff are ever requested/loaded.
        vintages, _ = self._store.get_forecast_vintages(
            cutoff_utc - DEFAULT_MAX_VINTAGE_AGE, cutoff_utc, chunk="day"
        )
        sel = select_forecast(vintages, hours, cutoff_utc, policy=POLICY_LATEST_COMPLETE)
        if not sel.has_forecast:
            raise NoEligibleForecast(
                f"No wind forecast covering {_fmt_date(delivery_date)} had been published by "
                f"{uk_iso(cutoff_utc)}",
                details={"cutoff": cutoff_utc.isoformat(), "eligible_vintages": sel.eligible_vintage_count},
            )
        return hours, cutoff_utc, sel

    @staticmethod
    def _cutoff_info(cutoff_time: str, cutoff_utc: datetime) -> CutoffInfo:
        return CutoffInfo(
            cutoff_time=cutoff_time,
            local_iso=uk_iso(cutoff_utc),
            utc=cutoff_utc,
            rule="Latest forecast published at or before this instant (UK time, previous day)",
        )

    @staticmethod
    def _forecast_info(sel: ForecastSelection) -> ForecastInfo:
        return ForecastInfo(
            source=SOURCE_LABEL,
            dataset="WINDFOR",
            policy=sel.policy,
            vintage_publish_time_utc=sel.vintage_publish_time,
            vintage_publish_time_local=uk_iso(sel.vintage_publish_time) if sel.vintage_publish_time else None,
            latest_eligible_publish_time_utc=sel.latest_eligible_publish_time,
            eligible_vintages_considered=sel.eligible_vintage_count,
            expected_hours=len(sel.required_hours),
            available_hours=len(sel.hour_values),
            missing_hours=[uk_label(h) for h in sel.missing_hours],
            is_complete=sel.is_complete,
            fallback_used=sel.fallback_used,
            fallback_reason=sel.fallback_reason,
        )

    # ----------------------------------------------------------- calibration

    def _load_calibration(self, calibration_id: str | None) -> tuple[Calibration, pd.DataFrame]:
        with self._sf() as s:
            if calibration_id:
                cal = s.get(Calibration, calibration_id)
                if cal is None:
                    raise NotFound(f"Calibration {calibration_id} not found")
            else:
                cal = s.execute(select(Calibration).where(Calibration.is_active)).scalar_one_or_none()
                if cal is None:
                    raise NotFound(
                        "No active calibration. Run a calibration first.", code="NO_ACTIVE_CALIBRATION"
                    )
            if cal.status != STATUS_COMPLETED:
                raise CalibrationUnavailable(
                    f"Calibration v{cal.version} is {cal.status} and cannot be used", code="CALIBRATION_NOT_COMPLETED"
                )
            rows = s.execute(
                select(
                    CalibrationObservation.delivery_start,
                    CalibrationObservation.delivery_date,
                    CalibrationObservation.hour_local,
                    CalibrationObservation.forecast_mw,
                    CalibrationObservation.actual_mw,
                    CalibrationObservation.error_mw,
                    CalibrationObservation.forecast_publish_time,
                    CalibrationObservation.decision_cutoff,
                    CalibrationObservation.actual_available_at,
                )
                .where(CalibrationObservation.calibration_id == cal.id)
                .order_by(CalibrationObservation.delivery_start)
            ).all()
        obs = pd.DataFrame(
            rows,
            columns=[
                "delivery_start",
                "delivery_date",
                "hour_local",
                "forecast_mw",
                "actual_mw",
                "error_mw",
                "forecast_publish_time",
                "decision_cutoff",
                "actual_available_at",
            ],
        )
        for col in ("delivery_start", "forecast_publish_time", "decision_cutoff", "actual_available_at"):
            obs[col] = pd.to_datetime(obs[col], utc=True)
        return cal, obs

    def _effective_calibration(
        self, cal: Calibration, obs: pd.DataFrame, cutoff_utc: datetime, cutoff_str: str
    ) -> tuple[pd.DataFrame, CalibrationRef, list[QualityWarning]]:
        kept, excluded = filter_observations_available_at(obs, cutoff_utc)
        eff_start = kept["delivery_date"].min() if not kept.empty else None
        eff_end = kept["delivery_date"].max() if not kept.empty else None
        ref = CalibrationRef(
            id=cal.id,
            version=cal.version,
            start_date=cal.start_date,
            end_date=cal.end_date,
            cutoff_time=cal.cutoff_time,
            calculated_at=cal.completed_at,
            pairs_stored=len(obs),
            pairs_used=len(kept),
            pairs_excluded_not_yet_available=excluded,
            effective_start_date=eff_start,
            effective_end_date=eff_end,
            cutoff_matches_calibration=(cal.cutoff_time == cutoff_str),
            is_active=cal.is_active,
        )
        warnings: list[QualityWarning] = []
        if len(kept) < self._settings.min_calibration_pairs:
            raise CalibrationUnavailable(
                f"Calibration v{cal.version} ({cal.start_date.isoformat()} to {cal.end_date.isoformat()}) has only "
                f"{len(kept)} matched hours that were already observed by the decision cutoff "
                f"{uk_iso(cutoff_utc)}; at least {self._settings.min_calibration_pairs} are required. "
                "Use a calibration range that ends at least a day before the decision cutoff, or activate a "
                "different calibration version.",
                details={
                    "calibration_id": cal.id,
                    "pairs_stored": len(obs),
                    "pairs_available_at_cutoff": len(kept),
                    "pairs_excluded_not_yet_available": excluded,
                    "cutoff": cutoff_utc.isoformat(),
                },
            )
        if excluded:
            warnings.append(
                QualityWarning(
                    code="CALIBRATION_TRIMMED_TO_CUTOFF",
                    severity="warning",
                    message=(
                        f"{excluded} calibration hour(s) had not yet been observed at the cutoff {uk_iso(cutoff_utc)} "
                        "and were excluded so that no future information leaks into this decision."
                    ),
                )
            )
        if not ref.cutoff_matches_calibration:
            warnings.append(
                QualityWarning(
                    code="CUTOFF_MISMATCH",
                    severity="info",
                    message=(
                        f"Calibration forecasts were reconstructed at a {cal.cutoff_time} UK cutoff; this decision uses "
                        f"{cutoff_str}. Forecast skill changes with lead time, so the error statistics are approximate."
                    ),
                )
            )
        if len(kept) < self._settings.low_sample_pairs:
            warnings.append(
                QualityWarning(
                    code="LOW_SAMPLE",
                    severity="warning",
                    message=f"Only {len(kept)} calibration hours; tail percentiles are low-confidence.",
                )
            )
        for w in cal.warnings or []:
            if w.get("severity") in ("warning", "error"):
                warnings.append(QualityWarning(**{k: w.get(k) for k in ("code", "severity", "message", "days")}))
        return kept, ref, warnings

    # ----------------------------------------------------------- decision

    def analyze(
        self, delivery_date: date, cutoff_time: str, pct: float = 95.0, calibration_id: str | None = None
    ) -> DecisionResponse:
        cutoff = self.validate_inputs(delivery_date, cutoff_time, pct)
        hours, cutoff_utc, sel = self._select_forecast(delivery_date, cutoff)
        cal, obs = self._load_calibration(calibration_id)
        kept, ref, warnings = self._effective_calibration(cal, obs, cutoff_utc, cutoff_time)

        errors = kept["error_mw"].to_numpy(dtype=float)
        metrics = compute_error_metrics(kept["forecast_mw"].to_numpy(), kept["actual_mw"].to_numpy())
        forecasts = [sel.hour_values.get(h) for h in hours]
        adj = compute_risk_adjustments(forecasts, errors, pct)

        hour_rows = [
            ForecastHour(
                start_utc=h,
                local_label=uk_label(h),
                local_iso=uk_iso(h),
                hour_local=_to_uk(h).hour,
                forecast_mw=f,
                missing=f is None,
                bias_adjusted_mw=adj["adjusted"][i],
                conservative_mw=adj["conservative"][i],
                interval_low_mw=adj["low"][i],
                interval_high_mw=adj["high"][i],
            )
            for i, (h, f) in enumerate(zip(hours, forecasts, strict=True))
        ]
        cons_vals = [v for v in adj["conservative"] if v is not None]
        risk = RiskAssessment(
            percentile=pct,
            shortfall_quantile_mw=adj["q_hi"],
            shortfall_buffer_mw=adj["buffer"],
            bias_mw=adj["bias"],
            bias_adjustment_mw=-adj["bias"],
            residual_buffer_mw=adj["buffer"] - adj["bias"],
            overforecast_share=metrics.share_overforecast,
            interval_confidence_pct=round(2 * pct - 100.0, 6),
            mean_baseline_mw=_mean(forecasts),
            mean_bias_adjusted_mw=_mean(adj["adjusted"]),
            mean_conservative_mw=_mean(adj["conservative"]),
            min_conservative_mw=min(cons_vals) if cons_vals else None,
            hours_floored_at_zero=adj["floored"],
            p90_positive_error_mw=metrics.p90_positive_error_mw,
            p95_positive_error_mw=metrics.p95_positive_error_mw,
        )

        finfo = self._forecast_info(sel)
        warnings = self._forecast_warnings(sel) + warnings
        if adj["floored"]:
            warnings.append(
                QualityWarning(
                    code="BUFFER_FLOORED_AT_ZERO",
                    severity="info",
                    message=f"In {adj['floored']} hour(s) the buffer exceeds the forecast; the conservative estimate is floored at 0 MW.",
                )
            )

        return DecisionResponse(
            delivery_date=delivery_date,
            timezone=TIMEZONE_NAME,
            cutoff=self._cutoff_info(cutoff_time, cutoff_utc),
            forecast=finfo,
            hours=hour_rows,
            calibration=ref,
            metrics=_metrics_out(metrics),
            risk=risk,
            explanation=self._explain(delivery_date, cutoff_time, cutoff_utc, sel, ref, metrics, risk),
            limitations=LIMITATIONS,
            warnings=warnings,
            procurement_note=PROCUREMENT_NOTE,
            generated_at=now_utc(),
        )

    @staticmethod
    def _forecast_warnings(sel: ForecastSelection) -> list[QualityWarning]:
        out: list[QualityWarning] = []
        if sel.missing_hours:
            out.append(
                QualityWarning(
                    code="INCOMPLETE_FORECAST",
                    severity="warning",
                    message=(
                        f"The forecast is missing {len(sel.missing_hours)} of {len(sel.required_hours)} delivery hours "
                        f"({', '.join(uk_label(h) for h in sel.missing_hours)} UK). Missing hours are not filled."
                    ),
                )
            )
        if sel.fallback_used and sel.fallback_reason:
            out.append(QualityWarning(code="FALLBACK_VINTAGE", severity="warning", message=sel.fallback_reason))
        return out

    def _explain(
        self,
        delivery_date: date,
        cutoff_time: str,
        cutoff_utc: datetime,
        sel: ForecastSelection,
        ref: CalibrationRef,
        m: ErrorMetrics,
        r: RiskAssessment,
    ) -> Explanation:
        assert sel.vintage_publish_time is not None
        pct = f"{r.percentile:g}"
        direction = "too high (wind over-forecast)" if r.bias_mw > 0 else "too low (wind under-forecast)"
        headline = (
            f"At P{pct}, wind in any hour of {_fmt_date(delivery_date)} could be up to "
            f"{r.shortfall_buffer_mw:,.0f} MW below the baseline forecast."
        )
        steps = [
            f"Forecast: the WINDFOR vintage published {_fmt_date(uk_date_of(sel.vintage_publish_time))} at "
            f"{uk_label(sel.vintage_publish_time)} UK is the latest available at your cutoff of {cutoff_time} on "
            f"{_fmt_date(uk_date_of(cutoff_utc))}. No later forecast was used.",
            f"Calibration: version {ref.version}, "
            f"{_fmt_date(ref.effective_start_date) if ref.effective_start_date else '?'} to "
            f"{_fmt_date(ref.effective_end_date) if ref.effective_end_date else '?'} "
            f"({ref.pairs_used} matched hourly pairs). Each pair compares the forecast available at "
            f"{ref.cutoff_time} the previous day with the observed hourly mean wind generation (FUELHH).",
            f"Error convention: error = forecast - actual. Historical bias is {r.bias_mw:+,.0f} MW, so forecasts were on "
            f"average {abs(r.bias_mw):,.0f} MW {direction}.",
            f"Shortfall buffer: in {pct}% of historical hours forecast - actual was at most {r.shortfall_quantile_mw:,.0f} MW "
            f"(P{pct} of the signed error over all {ref.pairs_used} hours). Buffer = max(0, that value) = "
            f"{r.shortfall_buffer_mw:,.0f} MW.",
            "Conservative estimate per hour = baseline forecast - buffer (floored at 0 MW). "
            f"The bias adjustment ({r.bias_adjustment_mw:+,.0f} MW) is already contained in the buffer: "
            f"buffer = bias ({r.bias_mw:+,.0f}) + residual margin ({r.residual_buffer_mw:+,.0f}) MW, so it is not applied twice.",
        ]
        if m.p95_positive_error_mw is not None:
            steps.append(
                f"For context, wind was over-forecast in {100 * (m.share_overforecast or 0):.0f}% of hours; "
                f"among those hours the P90 over-forecast was {m.p90_positive_error_mw:,.0f} MW and the P95 was "
                f"{m.p95_positive_error_mw:,.0f} MW. These are conditional on an over-forecast occurring and are "
                "different from the all-hours percentile used for the buffer."
            )
        defs = {k: v for k, v in METRIC_DEFINITIONS.items()}
        return Explanation(headline=headline, steps=steps, definitions=defs)

    # ----------------------------------------------------------- purchase plan

    def plan(self, delivery_date: date, req: ProcurementRequest) -> ProcurementResponse:
        """Purchase volume needed on top of wind (and existing contracts) to meet the user's demand.

        Built on :meth:`analyze`, so the forecast vintage and the calibration are subject to exactly the
        same cutoff / leakage rules as the decision itself.
        """
        d = self.analyze(delivery_date, req.cutoff, req.percentile, req.calibration_id)
        n = len(d.hours)

        demand = self._expand_profile("demand", req.demand_by_hour_mw, req.demand_mw, n)
        contracted = self._expand_profile("contracted supply", req.contracted_by_hour_mw, req.contracted_mw, n)

        plan_hours, scenarios = build_plan(d.hours, demand, contracted, req.wind_share_pct, req.percentile)
        by_key = {s.key: s for s in scenarios}
        planned = sum(1 for h in plan_hours if h.planned)

        share = req.wind_share_pct / 100.0
        r = d.risk
        warnings = list(d.warnings)
        if planned < n:
            warnings.append(
                QualityWarning(
                    code="HOURS_NOT_PLANNED",
                    severity="warning",
                    message=(
                        f"{n - planned} of {n} hours have no forecast, so no purchase volume can be calculated for them. "
                        "They are excluded from the totals; cover them separately."
                    ),
                )
            )
        if planned and by_key["cautious"].buy_total_mwh == 0:
            warnings.append(
                QualityWarning(
                    code="NO_PURCHASE_NEEDED",
                    severity="info",
                    message=(
                        "Wind (even in the cautious case) plus your existing contracts covers your demand in every planned hour. "
                        "If your demand is only a small part of GB demand, lower the wind share to the portion of national "
                        "wind output you can actually count on."
                    ),
                )
            )
        elif planned and share > 0 and by_key["cautious"].wind_cover_pct is not None and by_key["cautious"].wind_cover_pct >= 99.0:
            warnings.append(
                QualityWarning(
                    code="WIND_COVERS_ALMOST_ALL",
                    severity="info",
                    message="Wind covers almost all of your demand. Check that the wind share reflects what you can really access.",
                )
            )

        assumptions = [
            f"Wind supply = {req.wind_share_pct:g}% of GB national wind output. Your wind is assumed to move in proportion to the "
            "national total, so the national forecast and its uncertainty are both scaled by this share.",
            f"Cautious case = published forecast minus the P{r.percentile:g} shortfall buffer "
            f"({r.shortfall_buffer_mw:,.0f} MW nationally, {r.shortfall_buffer_mw * share:,.0f} MW at your share), floored at 0 MW. "
            f"It was exceeded in about {100 - r.percentile:g}% of comparable historical hours.",
            "Expected case = published forecast minus the average historical error "
            f"({r.bias_mw:+,.0f} MW nationally). The bias is part of the cautious buffer and is not subtracted twice.",
            "Purchase per hour = max(0, demand - existing contracted supply - wind). Each hour stands alone: surplus wind in one hour "
            "does not reduce the purchase in another. One hour = 1 h, so MW and MWh per hour are equal.",
            "Demand and contracted supply are exactly as you entered them; their own uncertainty is not modelled.",
            "Not included: prices, imbalance costs, network losses, storage, other generation, or the risk that wind errors are "
            "correlated across hours. This is a volume estimate, not a trading recommendation.",
        ]

        return ProcurementResponse(
            delivery_date=delivery_date,
            cutoff=d.cutoff,
            percentile=req.percentile,
            recommended_basis="cautious",
            wind_share_pct=req.wind_share_pct,
            demand_total_mwh=float(sum(h.demand_mw for h in plan_hours if h.planned)),
            contracted_total_mwh=float(sum(min(h.contracted_mw, h.demand_mw) for h in plan_hours if h.planned)),
            hours_total=n,
            hours_planned=planned,
            hours_unplanned=n - planned,
            scenarios=scenarios,
            risk_cover_mwh=by_key["cautious"].buy_total_mwh - by_key["expected"].buy_total_mwh,
            hours=plan_hours,
            forecast=d.forecast,
            calibration=d.calibration,
            assumptions=assumptions,
            warnings=warnings,
            generated_at=now_utc(),
        )

    @staticmethod
    def _expand_profile(name: str, hourly: list[float] | None, flat: float | None, n: int) -> list[float]:
        if hourly is not None:
            if len(hourly) != n:
                raise ValidationFailed(
                    f"Expected {n} hourly {name} values (one per UK-local delivery hour), got {len(hourly)}",
                    details={"field": f"{name}_by_hour", "expected": n, "received": len(hourly)},
                    code="INVALID_PROFILE_LENGTH",
                )
            return [float(v) for v in hourly]
        return [float(flat or 0.0)] * n

    # ----------------------------------------------------------- evaluation

    def evaluate(
        self, delivery_date: date, cutoff_time: str, pct: float = 95.0, calibration_id: str | None = None
    ) -> EvaluationResponse:
        cutoff = self.validate_inputs(delivery_date, cutoff_time, pct)
        hours, cutoff_utc, sel = self._select_forecast(delivery_date, cutoff)

        # Realised actuals: used for retrospective scoring only.
        half_hourly, _ = self._store.get_half_hourly_actuals(delivery_date, delivery_date, chunk="day")
        hourly = aggregate_actuals_hourly(half_hourly)
        actual_by_hour = {
            ts.to_pydatetime(): float(v) for ts, v in zip(hourly.complete["hour_start"], hourly.complete["actual_mw"], strict=True)
        }

        cal_ref: CalibrationRef | None = None
        warnings = self._forecast_warnings(sel)
        buffer: float | None = None
        try:
            cal, obs = self._load_calibration(calibration_id)
            kept, cal_ref, cal_warnings = self._effective_calibration(cal, obs, cutoff_utc, cutoff_time)
            errors = kept["error_mw"].to_numpy(dtype=float)
            buffer = max(0.0, float(np.percentile(errors, pct)))
            warnings += cal_warnings
        except (NotFound, CalibrationUnavailable) as exc:
            warnings.append(QualityWarning(code=exc.code, severity="info", message=f"Risk bands unavailable: {exc.message}"))

        rows: list[EvaluationHour] = []
        f_list: list[float] = []
        a_list: list[float] = []
        below = 0
        missing_f = missing_a = 0
        for h in hours:
            f = sel.hour_values.get(h)
            a = actual_by_hour.get(h)
            if f is None:
                missing_f += 1
            if a is None:
                missing_a += 1
            cons = max(0.0, f - buffer) if (f is not None and buffer is not None) else None
            is_below = (a < cons) if (a is not None and cons is not None) else None
            if f is not None and a is not None:
                f_list.append(f)
                a_list.append(a)
                if is_below:
                    below += 1
            rows.append(
                EvaluationHour(
                    start_utc=h,
                    local_label=uk_label(h),
                    local_iso=uk_iso(h),
                    forecast_mw=f,
                    actual_mw=a,
                    error_mw=(f - a) if (f is not None and a is not None) else None,
                    conservative_mw=cons,
                    actual_below_conservative=is_below,
                )
            )
        metrics = compute_error_metrics(f_list, a_list)
        if missing_a:
            warnings.append(
                QualityWarning(
                    code="MISSING_ACTUAL_HOURS",
                    severity="warning",
                    message=f"{missing_a} of {len(hours)} hours have no complete actual generation yet; they are excluded from scoring.",
                )
            )
        matched = metrics.n
        summary = EvaluationSummary(
            expected_hours=len(hours),
            matched_pairs=matched,
            hours_missing_forecast=missing_f,
            hours_missing_actual=missing_a,
            actuals_available=matched > 0,
            metrics=_metrics_out(metrics),
            percentile=pct if buffer is not None else None,
            hours_actual_below_conservative=below if buffer is not None else None,
            share_actual_below_conservative=(below / matched) if (buffer is not None and matched) else None,
            expected_share_below_conservative=((100.0 - pct) / 100.0) if buffer is not None else None,
        )
        return EvaluationResponse(
            delivery_date=delivery_date,
            timezone=TIMEZONE_NAME,
            cutoff=self._cutoff_info(cutoff_time, cutoff_utc),
            forecast=self._forecast_info(sel),
            hours=rows,
            summary=summary,
            calibration=cal_ref,
            warnings=warnings,
            notice=(
                "Retrospective evaluation: realised generation is shown only to score the forecast that was "
                "available at the cutoff. It was not, and could not have been, used to make the decision."
            ),
            generated_at=now_utc(),
        )


__all__ = ["DecisionService", "filter_observations_available_at", "assert_no_leakage", "compute_risk_adjustments"]
