"""Purchase-volume maths. Pure functions: no I/O, fully deterministic.

Per delivery hour (each hour is 1 h, so MW == MWh)::

    wind      = wind_share * national_wind_estimate        (estimate: forecast | bias-adjusted | conservative)
    residual  = max(0, demand - contracted)                 demand left after existing contracted supply
    wind_used = min(wind, residual)
    buy       = residual - wind_used  = max(0, demand - contracted - wind)
    surplus   = wind - wind_used      = max(0, wind - residual)

Hours are independent: surplus wind in one hour never offsets a purchase in another hour. Hours with no
forecast are *unplanned* - they are reported and excluded from totals, never filled with a guess.

The three wind estimates come from the decision analysis:
    forecast  - the WINDFOR vintage available at the cutoff, as published
    expected  - forecast minus the historical mean error (bias)
    cautious  - forecast minus the P(q) shortfall buffer (floored at 0 MW)
"""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.decision import ForecastHour
from app.schemas.procurement import PlanHour, PlanScenario

SCENARIOS: tuple[tuple[str, str, str], ...] = (
    ("forecast", "As published", "Wind arrives exactly as the forecast says."),
    ("expected", "Expected", "Forecast corrected for the average historical error (bias)."),
    ("cautious", "Cautious", "Wind falls short by the historical P{q} shortfall buffer."),
)


def hour_position(demand: float, contracted: float, wind: float) -> tuple[float, float, float]:
    """(buy, wind_used, surplus) for one hour; all MW, all >= 0."""
    residual = max(0.0, demand - contracted)
    wind_used = min(max(0.0, wind), residual)
    return residual - wind_used, wind_used, max(0.0, wind) - wind_used


def build_plan(
    hours: Sequence[ForecastHour],
    demand_mw: Sequence[float],
    contracted_mw: Sequence[float],
    wind_share_pct: float,
    percentile: float,
) -> tuple[list[PlanHour], list[PlanScenario]]:
    if not (len(hours) == len(demand_mw) == len(contracted_mw)):
        raise ValueError("hours, demand and contracted must have the same length")
    share = wind_share_pct / 100.0

    plan_hours: list[PlanHour] = []
    for h, d, c in zip(hours, demand_mw, contracted_mw, strict=True):
        base = PlanHour(
            start_utc=h.start_utc,
            local_label=h.local_label,
            hour_local=h.hour_local,
            demand_mw=d,
            contracted_mw=c,
            planned=False,
        )
        if h.forecast_mw is not None and h.bias_adjusted_mw is not None and h.conservative_mw is not None:
            winds = {
                "forecast": share * h.forecast_mw,
                "expected": share * h.bias_adjusted_mw,
                "cautious": share * h.conservative_mw,
            }
            base.planned = True
            for key, wind in winds.items():
                buy, _used, surplus = hour_position(d, c, wind)
                setattr(base, f"wind_{key}_mw", wind)
                setattr(base, f"buy_{key}_mw", buy)
                setattr(base, f"surplus_{key}_mw", surplus)
        plan_hours.append(base)

    return plan_hours, [_scenario(plan_hours, key, label, desc.format(q=f"{percentile:g}")) for key, label, desc in SCENARIOS]


def _scenario(hours: Sequence[PlanHour], key: str, label: str, description: str) -> PlanScenario:
    planned = [h for h in hours if h.planned]
    buys = [(h, getattr(h, f"buy_{key}_mw")) for h in planned]
    winds = [getattr(h, f"wind_{key}_mw") for h in planned]
    surpluses = [getattr(h, f"surplus_{key}_mw") for h in planned]

    buy_total = sum(b for _, b in buys)
    wind_total = sum(winds)
    surplus_total = sum(surpluses)
    wind_used = wind_total - surplus_total
    residual_total = sum(max(0.0, h.demand_mw - h.contracted_mw) for h in planned)
    peak_hour, peak = (None, 0.0)
    for h, b in buys:
        if b > peak:
            peak_hour, peak = h.local_label, b
    return PlanScenario(
        key=key,
        label=label,
        description=description,
        buy_total_mwh=buy_total,
        avg_buy_mw=buy_total / len(planned) if planned else 0.0,
        peak_buy_mw=peak,
        peak_buy_hour=peak_hour,
        hours_with_buy=sum(1 for _, b in buys if b > 0),
        wind_total_mwh=wind_total,
        wind_used_mwh=wind_used,
        wind_cover_pct=(100.0 * wind_used / residual_total) if residual_total > 0 else None,
        surplus_wind_mwh=surplus_total,
        hours_with_surplus=sum(1 for s in surpluses if s > 0),
    )
