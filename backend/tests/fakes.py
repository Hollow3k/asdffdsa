"""Deterministic fake of the Elexon API for automated tests (never the live API).

Synthetic world
---------------
* ``base(t)``  - "true" hourly mean wind MW at UTC hour ``t``.
* FUELHH half-hours are ``base - 50`` (first half) and ``base + 50`` (second half) so the hourly
  mean is exactly ``base(t)``.
* WINDFOR vintages are published at 02:30, 05:30, ... UTC (every 3 h), each covering 73 hours from
  ``floor(publish) - 8h``. The forecast for hour ``t`` in vintage ``p`` is
  ``base(t) + BIAS + lead_hours`` so every error is known in closed form.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

import httpx

from app.core.timeutils import UK_TZ, local_to_utc

BIAS = 1000.0
PUBLISH_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)  # at :30 UTC


def base(t: datetime) -> float:
    h = t.timestamp() / 3600.0
    return 10000.0 + 3000.0 * math.sin(h / 12.0)


def forecast_value(start: datetime, publish: datetime) -> float:
    lead = (start - publish).total_seconds() / 3600.0
    return base(start) + BIAS + lead


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def all_publish_times(first: datetime, last: datetime) -> list[datetime]:
    out = []
    day = first.date()
    while day <= last.date():
        for h in PUBLISH_HOURS:
            p = datetime(day.year, day.month, day.day, h, 30, tzinfo=UTC)
            if first <= p <= last:
                out.append(p)
        day += timedelta(days=1)
    return out


def vintage_rows(publish: datetime, drop: Callable[[datetime, datetime], bool] | None = None) -> list[dict]:
    first = publish.replace(minute=0, second=0, microsecond=0) - timedelta(hours=8)
    rows = []
    for i in range(73):
        start = first + timedelta(hours=i)
        if drop and drop(publish, start):
            continue
        rows.append(
            {
                "dataset": "WINDFOR",
                "publishTime": iso(publish),
                "startTime": iso(start),
                "generation": round(forecast_value(start, publish), 3),
            }
        )
    return rows


def settlement_period(start: datetime, settlement_date: date) -> int:
    day_start = local_to_utc(settlement_date, time(0, 0))
    return int((start - day_start).total_seconds() // 1800) + 1


class FakeElexon:
    """Callable httpx transport handler with request recording and fault injection."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.world_start = datetime(2025, 9, 1, tzinfo=UTC)
        self.world_end = datetime(2026, 2, 28, tzinfo=UTC)
        # Fault injection
        self.fail_with: int | None = None  # HTTP status for every request
        self.fail_after_calls: int | None = None  # start failing after N calls
        self.drop_forecast: Callable[[datetime, datetime], bool] | None = None
        self.drop_actual: Callable[[datetime], bool] | None = None
        self.drop_vintage: Callable[[datetime], bool] | None = None
        self.extra_other_fuel = False

    # ------------------------------------------------------------------ handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_with and (self.fail_after_calls is None or len(self.requests) > self.fail_after_calls):
            return httpx.Response(self.fail_with, json={"title": "injected failure"})
        path = request.url.path
        params = dict(request.url.params)
        if path.endswith("/datasets/WINDFOR/stream"):
            return self._windfor(params)
        if path.endswith("/datasets/FUELHH/stream"):
            return self._fuelhh(params)
        return httpx.Response(404, json={"title": "not found"})

    def _windfor(self, p: dict) -> httpx.Response:
        if "settlementDateFrom" in p:
            return httpx.Response(400, json={"errors": {"": ["unsupported"]}})
        lo = datetime.fromisoformat(p["publishDateTimeFrom"].replace("Z", "+00:00"))
        hi = datetime.fromisoformat(p["publishDateTimeTo"].replace("Z", "+00:00"))
        lo, hi = max(lo, self.world_start), min(hi, self.world_end)
        rows: list[dict] = []
        for pub in all_publish_times(lo, hi):
            if self.drop_vintage and self.drop_vintage(pub):
                continue
            rows.extend(vintage_rows(pub, self.drop_forecast))
        return httpx.Response(200, json=rows)

    def _fuelhh(self, p: dict) -> httpx.Response:
        if "publishDateTimeFrom" in p:
            return httpx.Response(
                400, json={"errors": {"": ["The Settlement Date fields cannot be set when a Publish Date field is set."]}}
            )
        d0 = date.fromisoformat(p["settlementDateFrom"])
        d1 = date.fromisoformat(p["settlementDateTo"])
        rows: list[dict] = []
        d = d0
        while d <= d1:
            start = local_to_utc(d, time(0, 0))
            end = local_to_utc(d + timedelta(days=1), time(0, 0))
            t = start
            while t < end:
                hour = t.replace(minute=0)
                second_half = t.minute == 30
                if self.world_start <= t <= self.world_end and not (self.drop_actual and self.drop_actual(t)):
                    rows.append(
                        {
                            "dataset": "FUELHH",
                            "publishTime": iso(t + timedelta(minutes=30)),
                            "startTime": iso(t),
                            "settlementDate": d.isoformat(),
                            "settlementPeriod": settlement_period(t, d),
                            "fuelType": "WIND",
                            "generation": base(hour) + (50.0 if second_half else -50.0),
                        }
                    )
                    if self.extra_other_fuel:
                        rows.append({**rows[-1], "fuelType": "CCGT", "generation": 99999.0})
                t += timedelta(minutes=30)
            d += timedelta(days=1)
        return httpx.Response(200, json=rows)

    # ------------------------------------------------------------------ helpers

    def count(self, dataset: str) -> int:
        return sum(1 for r in self.requests if dataset in r.url.path)


def uk_midnight(d: date) -> datetime:
    return datetime.combine(d, time(0), tzinfo=UK_TZ).astimezone(UTC)
