"""Domain exceptions and their mapping onto a consistent HTTP error envelope.

Every error returned by the API has the shape::

    {"error": {"code": "SOME_CODE", "message": "Human readable", "details": {...}}}

Internal stack traces are logged server side and never sent to the browser.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code:
            self.code = code


class ValidationFailed(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"


class CalibrationUnavailable(AppError):
    """The active calibration cannot legitimately support the requested decision."""

    status_code = 422
    code = "CALIBRATION_UNAVAILABLE_AT_CUTOFF"


class NoEligibleForecast(AppError):
    status_code = 404
    code = "NO_ELIGIBLE_FORECAST"


class UpstreamError(AppError):
    status_code = 502
    code = "UPSTREAM_ERROR"


class FutureDataLeakageError(AppError):
    """Raised when a decision would be informed by data not available at its cutoff."""

    status_code = 500
    code = "FUTURE_DATA_LEAKAGE"


# --- Elexon client errors ---------------------------------------------------


class ElexonError(UpstreamError):
    code = "ELEXON_ERROR"


class ElexonUnavailableError(ElexonError):
    """Timeouts, connection failures, 5xx after bounded retries."""

    status_code = 502
    code = "ELEXON_UNAVAILABLE"


class ElexonRateLimitError(ElexonError):
    status_code = 503
    code = "ELEXON_RATE_LIMITED"


class ElexonBadRequestError(ElexonError):
    status_code = 502
    code = "ELEXON_REJECTED_REQUEST"


class ElexonDataError(ElexonError):
    """Response arrived but was empty/malformed in a way we cannot safely use."""

    status_code = 502
    code = "ELEXON_MALFORMED_DATA"


class NoDataError(ElexonError):
    """Response was valid but contained no usable records."""

    status_code = 404
    code = "NO_DATA"
