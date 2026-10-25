from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.core.errors import ValidationFailed
from app.core.timeutils import local_day_bounds_utc
from app.models.market_data import FetchCoverage, WindActualRecord, WindForecastRecord
from app.schemas.common import ErrorEnvelope
from app.schemas.decision import CoverageDataset, CoverageGap, DataCoverageResponse

router = APIRouter(prefix="/api", tags=["coverage"])

MAX_GAPS = 50
VINTAGE_GAP_HOURS = 6


@router.get(
    "/data-coverage",
    response_model=DataCoverageResponse,
    responses={422: {"model": ErrorEnvelope}},
    summary="Elexon data stored locally and any gaps in it",
)
def data_coverage(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    session: Session = Depends(get_session),
) -> DataCoverageResponse:
    """Reports what is *stored locally* (data fetched so far), not what exists upstream."""
    if (start_date is None) != (end_date is None):
        raise ValidationFailed("Provide both start_date and end_date, or neither")
    if start_date and end_date and end_date < start_date:
        raise ValidationFailed("end_date must not be before start_date")

    f_q = select(WindForecastRecord.publish_time).distinct().order_by(WindForecastRecord.publish_time)
    f_rows = select(func.count()).select_from(WindForecastRecord)
    a_q = select(WindActualRecord.start_time).order_by(WindActualRecord.start_time)
    if start_date and end_date:
        lo, _ = local_day_bounds_utc(start_date)
        _, hi = local_day_bounds_utc(end_date)
        f_q = f_q.where(WindForecastRecord.publish_time >= lo, WindForecastRecord.publish_time < hi)
        f_rows = f_rows.where(WindForecastRecord.publish_time >= lo, WindForecastRecord.publish_time < hi)
        a_q = a_q.where(WindActualRecord.start_time >= lo, WindActualRecord.start_time < hi)

    publish_times = list(session.execute(f_q).scalars())
    actual_starts = list(session.execute(a_q).scalars())
    forecast_rows = session.execute(f_rows).scalar_one()

    gaps: list[CoverageGap] = []
    for a, b in zip(publish_times, publish_times[1:], strict=False):
        if b - a > timedelta(hours=VINTAGE_GAP_HOURS):
            gaps.append(
                CoverageGap(
                    kind="forecast_vintage_gap",
                    start_utc=a,
                    end_utc=b,
                    description=f"No forecast published for {(b - a).total_seconds() / 3600:.1f} h",
                )
            )
    for a, b in zip(actual_starts, actual_starts[1:], strict=False):
        if b - a > timedelta(minutes=30):
            missing = int((b - a) / timedelta(minutes=30)) - 1
            gaps.append(
                CoverageGap(
                    kind="actual_missing_half_hours",
                    start_utc=a + timedelta(minutes=30),
                    end_utc=b,
                    description=f"{missing} half-hour period(s) of wind outturn missing",
                )
            )
    gaps.sort(key=lambda g: g.start_utc)
    truncated = len(gaps) > MAX_GAPS

    fetched_ranges = session.execute(select(func.count()).select_from(FetchCoverage)).scalar_one()
    return DataCoverageResponse(
        note="Coverage of locally stored data (fetched on demand). Gaps are reported only between stored observations.",
        start_date=start_date,
        end_date=end_date,
        forecast=CoverageDataset(
            dataset="WINDFOR",
            rows=forecast_rows,
            first=publish_times[0] if publish_times else None,
            last=publish_times[-1] if publish_times else None,
            detail={"vintages": len(publish_times), "first_last_refer_to": "publish_time"},
        ),
        actual=CoverageDataset(
            dataset="FUELHH (WIND)",
            rows=len(actual_starts),
            first=actual_starts[0] if actual_starts else None,
            last=actual_starts[-1] if actual_starts else None,
            detail={"granularity_minutes": 30, "first_last_refer_to": "start_time"},
        ),
        gaps=gaps[:MAX_GAPS],
        gaps_truncated=truncated,
        fetched_ranges=fetched_ranges,
    )
