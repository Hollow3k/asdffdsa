"""Elexon Insights Solution (BMRS) API client.

Endpoints used (verified against the live API, not guessed):

* ``GET /datasets/WINDFOR/stream`` - national wind forecast *vintages*, hourly. Query:
  ``publishDateTimeFrom`` / ``publishDateTimeTo`` (both inclusive). Rows:
  ``{dataset, publishTime, startTime, generation}``. Each publication is a snapshot of ~73
  hourly target intervals, published roughly every 2-4 hours.
* ``GET /datasets/FUELHH/stream`` - half-hourly outturn by fuel type. Query:
  ``settlementDateFrom`` / ``settlementDateTo`` and ``fuelType``. Rows:
  ``{dataset, publishTime, startTime, settlementDate, settlementPeriod, fuelType, generation}``.
  Settlement-date filters **cannot** be combined with publish-date filters (the API answers 400),
  so this client only ever sends settlement dates for FUELHH and publish times for WINDFOR.

Both ``/stream`` endpoints return a JSON array in a single response (no pagination).

This module only fetches and validates; business logic lives elsewhere.
"""

from __future__ import annotations

import logging
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import httpx

from app.core.errors import (
    ElexonBadRequestError,
    ElexonDataError,
    ElexonRateLimitError,
    ElexonUnavailableError,
)
from app.core.timeutils import parse_utc, utc_iso

logger = logging.getLogger(__name__)

WIND_FUEL_TYPE = "WIND"
RETRYABLE_STATUS = {500, 502, 503, 504}
# If more than this share of rows in a response is malformed we refuse the whole response.
MAX_MALFORMED_SHARE = 0.05


@dataclass(frozen=True)
class ForecastRow:
    publish_time: datetime  # when the forecast was published (UTC)
    start_time: datetime  # start of the target delivery hour (UTC)
    generation_mw: float


@dataclass(frozen=True)
class ActualRow:
    start_time: datetime  # start of the half-hour (UTC)
    settlement_date: date  # UK settlement date
    settlement_period: int
    publish_time: datetime | None
    generation_mw: float


@dataclass
class FetchResult:
    rows: list = field(default_factory=list)
    raw_count: int = 0
    dropped_malformed: int = 0
    dropped_other_fuel: int = 0
    requests_made: int = 0

    @property
    def empty(self) -> bool:
        return not self.rows


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


class ElexonClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 45.0,
        max_retries: int = 4,
        backoff_base: float = 1.0,
        backoff_max: float = 20.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float], float] | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max(0, max_retries)
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._sleep = sleep
        self._jitter = jitter if jitter is not None else (lambda d: random.uniform(0, d * 0.1))
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": "wind-procurement-dashboard/1.0"},
        )
        self.request_count = 0

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ HTTP

    def _delay(self, attempt: int, retry_after: float | None = None) -> float:
        delay = min(self._backoff_max, self._backoff_base * (2**attempt))
        if retry_after is not None:
            delay = min(self._backoff_max, max(delay, retry_after))
        return delay + self._jitter(delay)

    @staticmethod
    def _retry_after_seconds(resp: httpx.Response) -> float | None:
        raw = resp.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            return None  # HTTP-date form is not worth supporting for a bounded backoff

    def _get_json(self, path: str, params: dict[str, str]) -> Any:
        last_error: Exception | None = None
        total_attempts = self._max_retries + 1
        for attempt in range(total_attempts):
            retry_after: float | None = None
            self.request_count += 1
            try:
                resp = self._client.get(path, params=params)
            except httpx.TimeoutException as exc:
                last_error = ElexonUnavailableError(
                    f"Elexon API timed out after {self._timeout:.0f}s",
                    details={"path": path, "attempts": attempt + 1},
                )
                logger.warning("Elexon timeout on %s (attempt %d/%d)", path, attempt + 1, total_attempts)
                last_error.__cause__ = exc
            except httpx.TransportError as exc:
                last_error = ElexonUnavailableError(
                    "Could not connect to the Elexon API",
                    details={"path": path, "attempts": attempt + 1, "reason": type(exc).__name__},
                )
                logger.warning("Elexon transport error on %s: %s", path, type(exc).__name__)
                last_error.__cause__ = exc
            else:
                status = resp.status_code
                if status == 200:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        last_error = ElexonDataError(
                            "Elexon API returned a response that is not valid JSON",
                            details={"path": path, "attempts": attempt + 1},
                        )
                        last_error.__cause__ = exc
                elif status == 429:
                    retry_after = self._retry_after_seconds(resp)
                    last_error = ElexonRateLimitError(
                        "Elexon API rate limit reached; try again shortly",
                        details={"path": path, "attempts": attempt + 1, "retry_after": retry_after},
                    )
                    logger.warning("Elexon rate limited on %s (attempt %d/%d)", path, attempt + 1, total_attempts)
                elif status in RETRYABLE_STATUS:
                    last_error = ElexonUnavailableError(
                        f"Elexon API responded with HTTP {status}",
                        details={"path": path, "status": status, "attempts": attempt + 1},
                    )
                    logger.warning("Elexon HTTP %s on %s (attempt %d/%d)", status, path, attempt + 1, total_attempts)
                else:
                    # 4xx other than 429 are not transient: do not retry.
                    detail = _short_error_body(resp)
                    raise ElexonBadRequestError(
                        f"Elexon API rejected the request (HTTP {status}): {detail}",
                        details={"path": path, "status": status, "params": params},
                    )
            if attempt < total_attempts - 1:
                self._sleep(self._delay(attempt, retry_after))
        assert last_error is not None
        raise last_error

    # ------------------------------------------------------------------ WINDFOR

    def fetch_wind_forecasts(self, publish_from: datetime, publish_to: datetime) -> FetchResult:
        """Forecast vintages published within [publish_from, publish_to] (inclusive)."""
        if publish_to < publish_from:
            raise ValueError("publish_to must not be before publish_from")
        payload = self._get_json(
            "/datasets/WINDFOR/stream",
            {
                "publishDateTimeFrom": utc_iso(publish_from),
                "publishDateTimeTo": utc_iso(publish_to),
                "format": "json",
            },
        )
        return _parse_forecasts(payload)

    # ------------------------------------------------------------------ FUELHH

    def fetch_wind_actuals(self, settlement_from: date, settlement_to: date) -> FetchResult:
        """WIND outturn for settlement dates in [settlement_from, settlement_to] (inclusive)."""
        if settlement_to < settlement_from:
            raise ValueError("settlement_to must not be before settlement_from")
        payload = self._get_json(
            "/datasets/FUELHH/stream",
            {
                "settlementDateFrom": settlement_from.isoformat(),
                "settlementDateTo": settlement_to.isoformat(),
                "fuelType": WIND_FUEL_TYPE,
                "format": "json",
            },
        )
        return _parse_actuals(payload)

    # ------------------------------------------------------------------ health

    def ping(self) -> bool:
        """Cheap reachability probe (single request, no retries)."""
        try:
            resp = self._client.get(
                "/datasets/WINDFOR/stream",
                params={
                    "publishDateTimeFrom": "2026-01-01T00:00:00Z",
                    "publishDateTimeTo": "2026-01-01T00:00:00Z",
                },
                timeout=5.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError:
            return False


def _short_error_body(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, dict):
            flat = [m for v in errors.values() if isinstance(v, list) for m in v]
            if flat:
                return "; ".join(str(m) for m in flat)[:300]
        title = body.get("title") or body.get("message")
        if title:
            return str(title)[:300]
    return str(body)[:200]


def _ensure_list_payload(payload: Any) -> list:
    if not isinstance(payload, list):
        raise ElexonDataError(
            "Elexon API returned an unexpected response shape (expected a JSON array)",
            details={"received_type": type(payload).__name__},
        )
    return payload


def _check_malformed_share(dropped: int, total: int, dataset: str) -> None:
    if total and dropped / total > MAX_MALFORMED_SHARE:
        raise ElexonDataError(
            f"{dataset} response is malformed: {dropped} of {total} rows were unusable",
            details={"dropped": dropped, "total": total, "dataset": dataset},
        )


def _parse_forecasts(payload: Any) -> FetchResult:
    items = _ensure_list_payload(payload)
    result = FetchResult(raw_count=len(items), requests_made=1)
    for item in items:
        try:
            if not isinstance(item, dict):
                raise ValueError("row is not an object")
            ds = item.get("dataset")
            if ds is not None and ds != "WINDFOR":
                raise ValueError(f"unexpected dataset {ds!r}")
            gen = _finite_number(item["generation"])
            if gen is None:
                raise ValueError("generation is not a finite number")
            publish = parse_utc(item["publishTime"])
            start = parse_utc(item["startTime"])
        except (KeyError, ValueError, TypeError, AttributeError):
            result.dropped_malformed += 1
            continue
        result.rows.append(ForecastRow(publish_time=publish, start_time=start, generation_mw=gen))
    _check_malformed_share(result.dropped_malformed, result.raw_count, "WINDFOR")
    if result.dropped_malformed:
        logger.warning("WINDFOR: dropped %d malformed rows of %d", result.dropped_malformed, result.raw_count)
    return result


def _parse_actuals(payload: Any) -> FetchResult:
    items = _ensure_list_payload(payload)
    result = FetchResult(raw_count=len(items), requests_made=1)
    for item in items:
        try:
            if not isinstance(item, dict):
                raise ValueError("row is not an object")
            fuel = item.get("fuelType")
            if fuel != WIND_FUEL_TYPE:
                # Never let other fuels leak into wind actuals.
                result.dropped_other_fuel += 1
                continue
            gen = _finite_number(item["generation"])
            if gen is None:
                raise ValueError("generation is not a finite number")
            start = parse_utc(item["startTime"])
            sdate = date.fromisoformat(str(item["settlementDate"])[:10])
            period = int(item["settlementPeriod"])
            publish_raw = item.get("publishTime")
            publish = parse_utc(publish_raw) if publish_raw else None
        except (KeyError, ValueError, TypeError, AttributeError):
            result.dropped_malformed += 1
            continue
        result.rows.append(
            ActualRow(
                start_time=start,
                settlement_date=sdate,
                settlement_period=period,
                publish_time=publish,
                generation_mw=gen,
            )
        )
    _check_malformed_share(result.dropped_malformed + result.dropped_other_fuel, result.raw_count, "FUELHH")
    if result.dropped_malformed or result.dropped_other_fuel:
        logger.warning(
            "FUELHH: dropped %d malformed and %d non-wind rows of %d",
            result.dropped_malformed,
            result.dropped_other_fuel,
            result.raw_count,
        )
    return result
