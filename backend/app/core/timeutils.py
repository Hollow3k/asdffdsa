"""Time handling. Everything is stored in UTC; UK business logic uses Europe/London.

UK local days are *not* UTC calendar days: in BST a delivery day starts at 23:00 UTC of the
previous calendar day, and on DST transition days a local day has 23 or 25 hours.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

UK_TZ = ZoneInfo("Europe/London")
TIMEZONE_NAME = "Europe/London"

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def parse_hhmm(value: str) -> time:
    m = _HHMM.match(value.strip())
    if not m:
        raise ValueError(f"Time must be HH:MM in 24h format, got {value!r}")
    return time(int(m.group(1)), int(m.group(2)))


def ensure_utc(dt: datetime) -> datetime:
    """Return an aware UTC datetime. Naive datetimes are rejected (ambiguous)."""
    if dt.tzinfo is None:
        raise ValueError("Naive datetime is not allowed; timestamps must be timezone-aware")
    return dt.astimezone(UTC)


def local_to_utc(d: date, t: time) -> datetime:
    """UK wall-clock date+time -> aware UTC datetime.

    A non-existent local time (spring-forward gap) resolves using the pre-transition offset; an
    ambiguous time (autumn overlap) resolves to its first occurrence (fold=0).
    """
    return datetime.combine(d, t, tzinfo=UK_TZ).astimezone(UTC)


def local_day_bounds_utc(d: date) -> tuple[datetime, datetime]:
    """[start, end) of the UK-local calendar day ``d`` as UTC instants."""
    start = local_to_utc(d, time(0, 0))
    end = local_to_utc(d + timedelta(days=1), time(0, 0))
    return start, end


def local_day_hours_utc(d: date) -> list[datetime]:
    """UTC start instants of every UK-local hour of day ``d`` (24, or 23/25 on DST days)."""
    start, end = local_day_bounds_utc(d)
    hours: list[datetime] = []
    cur = start
    while cur < end:
        hours.append(cur)
        cur += timedelta(hours=1)
    return hours


def previous_day_cutoff_utc(delivery_date: date, cutoff: time) -> datetime:
    """Decision cutoff: ``cutoff`` UK time on the day *before* ``delivery_date``."""
    return local_to_utc(delivery_date - timedelta(days=1), cutoff)


def to_uk(dt: datetime) -> datetime:
    return ensure_utc(dt).astimezone(UK_TZ)


def uk_date_of(dt: datetime) -> date:
    return to_uk(dt).date()


def uk_label(dt: datetime) -> str:
    """HH:MM label in UK local time."""
    return to_uk(dt).strftime("%H:%M")


def uk_iso(dt: datetime) -> str:
    """ISO-8601 with the UK offset, e.g. 2026-01-14T17:00:00+00:00."""
    return to_uk(dt).isoformat()


def utc_iso(dt: datetime) -> str:
    return ensure_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    """Parse an API timestamp ('...Z' or with offset). Naive strings are treated as UTC, as
    the Elexon API always returns UTC instants."""
    v = value.strip()
    if v.endswith("Z") or v.endswith("z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def now_utc() -> datetime:
    return datetime.now(UTC)


def today_uk() -> date:
    return now_utc().astimezone(UK_TZ).date()
