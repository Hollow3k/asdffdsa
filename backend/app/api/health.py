from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import get_container
from app.container import Container
from app.core.timeutils import TIMEZONE_NAME, now_utc, today_uk
from app.schemas.calibration import AppConfig

router = APIRouter(prefix="/api", tags=["health"])

_UPSTREAM_CACHE: dict[str, Any] = {"at": 0.0, "ok": None}
_UPSTREAM_TTL_SECONDS = 60.0


@router.get("/health", summary="Application and upstream service health")
def health(container: Container = Depends(get_container)) -> dict[str, Any]:
    db_ok = True
    try:
        with container.session_factory() as s:
            s.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - report, never raise from a health probe
        db_ok = False

    now = time.monotonic()
    if _UPSTREAM_CACHE["ok"] is None or now - _UPSTREAM_CACHE["at"] > _UPSTREAM_TTL_SECONDS:
        _UPSTREAM_CACHE["ok"] = container.client.ping()
        _UPSTREAM_CACHE["at"] = now
    elexon_ok = bool(_UPSTREAM_CACHE["ok"])

    return {
        "status": "ok" if db_ok else "degraded",
        "time_utc": now_utc(),
        "database": {"ok": db_ok},
        # An unreachable Elexon API does not make the app unhealthy: saved calibrations still work.
        "elexon": {"reachable": elexon_ok, "cached_for_seconds": int(_UPSTREAM_TTL_SECONDS)},
    }


@router.get("/config", response_model=AppConfig, summary="Defaults and limits used by the UI")
def config(container: Container = Depends(get_container)) -> AppConfig:
    s = container.settings
    return AppConfig(
        timezone=TIMEZONE_NAME,
        default_calibration_start=s.default_calibration_start,
        default_calibration_end=s.default_calibration_end,
        decision_window_start=s.decision_window_start,
        decision_window_end=s.decision_window_end,
        default_cutoff_time=s.default_cutoff_time,
        min_calibration_pairs=s.min_calibration_pairs,
        low_sample_pairs=s.low_sample_pairs,
        max_calibration_days=s.max_calibration_days,
        latest_calibration_end_date=today_uk() - timedelta(days=1),
    )
