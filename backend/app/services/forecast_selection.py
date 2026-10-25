"""Decision-time forecast selection.

Given a pool of forecast vintages and a decision cutoff, choose the forecast that was genuinely
available at that moment for a set of required delivery hours.

Policy ``latest_complete_vintage`` (default, documented and auditable):

1. Consider only vintages with ``publish_time <= cutoff`` (and not older than ``max_vintage_age``).
   Vintages published after the cutoff are *never* eligible - they are only counted for audit.
2. If the latest eligible vintage covers every required hour, use it.
3. Otherwise use the most recent *earlier* eligible vintage that is complete. The fallback is
   flagged (``fallback_used``) with a reason - vintages are never silently mixed per hour.
4. If no eligible vintage is complete, use the eligible vintage with the greatest coverage (latest
   on ties) and report the missing hours. Missing hours are never filled with actuals, later
   forecasts or defaults.

Policy ``latest_vintage_only`` skips step 3 and uses the latest eligible vintage as-is.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

from app.core.errors import FutureDataLeakageError

POLICY_LATEST_COMPLETE = "latest_complete_vintage"
POLICY_LATEST_ONLY = "latest_vintage_only"
VALID_POLICIES = (POLICY_LATEST_COMPLETE, POLICY_LATEST_ONLY)
DEFAULT_MAX_VINTAGE_AGE = timedelta(hours=72)


@dataclass
class ForecastSelection:
    cutoff_utc: datetime
    required_hours: list[datetime]
    policy: str
    vintage_publish_time: datetime | None = None
    latest_eligible_publish_time: datetime | None = None
    hour_values: dict[datetime, float] = field(default_factory=dict)
    missing_hours: list[datetime] = field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: str | None = None
    eligible_vintage_count: int = 0
    excluded_future_vintage_count: int = 0

    @property
    def has_forecast(self) -> bool:
        return self.vintage_publish_time is not None and bool(self.hour_values)

    @property
    def is_complete(self) -> bool:
        return self.has_forecast and not self.missing_hours


def select_forecast(
    vintages: pd.DataFrame,
    required_hours: Sequence[datetime],
    cutoff_utc: datetime,
    *,
    policy: str = POLICY_LATEST_COMPLETE,
    max_vintage_age: timedelta = DEFAULT_MAX_VINTAGE_AGE,
) -> ForecastSelection:
    """Pick the forecast vintage for ``required_hours`` that was available at ``cutoff_utc``.

    ``vintages`` needs columns ``publish_time``, ``start_time``, ``generation_mw`` (UTC).
    """
    if policy not in VALID_POLICIES:
        raise ValueError(f"Unknown forecast selection policy {policy!r}")
    if cutoff_utc.tzinfo is None:
        raise ValueError("cutoff_utc must be timezone-aware")

    required = list(required_hours)
    sel = ForecastSelection(cutoff_utc=cutoff_utc, required_hours=required, policy=policy)
    sel.missing_hours = list(required)
    if vintages.empty or not required:
        return sel

    cutoff_ts = pd.Timestamp(cutoff_utc)
    publish = vintages["publish_time"]
    sel.excluded_future_vintage_count = int(publish[publish > cutoff_ts].nunique())

    eligible = vintages[(publish <= cutoff_ts) & (publish >= cutoff_ts - max_vintage_age)]
    if eligible.empty:
        return sel

    publish_desc = sorted(eligible["publish_time"].unique(), reverse=True)
    sel.eligible_vintage_count = len(publish_desc)
    sel.latest_eligible_publish_time = pd.Timestamp(publish_desc[0]).to_pydatetime()

    required_index = pd.DatetimeIndex(required, tz="UTC") if _all_aware_utc(required) else pd.DatetimeIndex(required)
    relevant = eligible[eligible["start_time"].isin(required_index)]
    coverage = relevant.groupby("publish_time")["start_time"].nunique()
    n_required = len(set(required))

    def covered(p) -> int:  # noqa: ANN001
        return int(coverage.get(p, 0))

    latest = publish_desc[0]
    chosen = latest
    if covered(latest) < n_required and policy == POLICY_LATEST_COMPLETE:
        complete = [p for p in publish_desc if covered(p) == n_required]
        if complete:
            chosen = complete[0]
            sel.fallback_used = True
            missing_latest = n_required - covered(latest)
            sel.fallback_reason = (
                f"Latest eligible vintage ({pd.Timestamp(latest).isoformat()}) was missing "
                f"{missing_latest} of {n_required} required hours; used the most recent complete "
                f"earlier vintage instead."
            )
        else:
            best = max(publish_desc, key=lambda p: (covered(p), p))
            chosen = best
            if best != latest:
                sel.fallback_used = True
                sel.fallback_reason = (
                    "No eligible vintage fully covered the delivery day; used the eligible vintage "
                    "with the greatest coverage."
                )

    chosen_rows = relevant[relevant["publish_time"] == chosen]
    values = {
        pd.Timestamp(t).to_pydatetime(): float(g)
        for t, g in zip(chosen_rows["start_time"], chosen_rows["generation_mw"], strict=True)
    }
    sel.vintage_publish_time = pd.Timestamp(chosen).to_pydatetime()
    sel.hour_values = values
    sel.missing_hours = [h for h in required if h not in values]

    _assert_no_future_vintage(sel)
    return sel


def _all_aware_utc(hours: Sequence[datetime]) -> bool:
    return all(h.tzinfo is not None for h in hours)


def _assert_no_future_vintage(sel: ForecastSelection) -> None:
    """Last line of defence: a forecast published after the cutoff must never be returned."""
    if sel.vintage_publish_time is not None and sel.vintage_publish_time > sel.cutoff_utc:
        raise FutureDataLeakageError(
            "Selected forecast vintage was published after the decision cutoff",
            details={
                "vintage_publish_time": sel.vintage_publish_time.isoformat(),
                "cutoff": sel.cutoff_utc.isoformat(),
            },
        )
