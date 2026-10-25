import math

import numpy as np
import pytest

from app.services.metrics import compute_error_metrics, forecast_error, percentile


def test_error_sign_positive_means_overforecast():
    # forecast 120 vs actual 100 -> wind was over-forecast, actual lower than predicted
    assert forecast_error(120.0, 100.0) == pytest.approx(20.0)
    # forecast 80 vs actual 100 -> under-forecast, negative
    assert forecast_error(80.0, 100.0) == pytest.approx(-20.0)


def test_metrics_on_known_sample():
    forecast = [110, 90, 100, 130]
    actual = [100, 100, 100, 100]
    # errors: +10, -10, 0, +30
    m = compute_error_metrics(forecast, actual)
    assert m.n == 4
    assert m.mae_mw == pytest.approx(12.5)
    assert m.rmse_mw == pytest.approx(math.sqrt((100 + 100 + 0 + 900) / 4))
    assert m.bias_mw == pytest.approx(7.5)
    # |error| sorted [0, 10, 10, 30]; linear interpolation: p90 at index 2.7, p95 at 2.85
    assert m.p90_abs_error_mw == pytest.approx(24.0)
    assert m.p95_abs_error_mw == pytest.approx(27.0)
    # positive errors only: [10, 30]; p90 at 0.9 -> 28, p95 at 0.95 -> 29
    assert m.n_overforecast == 2
    assert m.share_overforecast == pytest.approx(0.5)
    assert m.p90_positive_error_mw == pytest.approx(28.0)
    assert m.p95_positive_error_mw == pytest.approx(29.0)
    assert m.mean_forecast_mw == pytest.approx(107.5)
    assert m.mean_actual_mw == pytest.approx(100.0)


def test_abs_error_percentile_differs_from_positive_error_percentile():
    # Large under-forecast must widen the absolute-error tail but not the positive-error tail.
    m = compute_error_metrics([100, 100, 100, 100, 100], [100, 100, 100, 100, 1100])
    # |errors| = [0, 0, 0, 0, 1000]; p95 sits at index 3.8 -> 0.8 * 1000
    assert m.p95_abs_error_mw == pytest.approx(800.0)
    assert m.p95_positive_error_mw is None  # no over-forecast hours at all
    assert m.bias_mw < 0


def test_signed_error_quantiles():
    forecast = [100 + e for e in range(-5, 6)]  # errors -5..5
    m = compute_error_metrics(forecast, [100] * 11)
    assert m.p50_error_mw == pytest.approx(0.0)
    assert m.p95_error_mw == pytest.approx(4.5)
    assert m.p05_error_mw == pytest.approx(-4.5)


def test_empty_and_invalid_inputs_are_unavailable_not_zero():
    m = compute_error_metrics([], [])
    assert m.n == 0 and m.mae_mw is None and m.rmse_mw is None and not m.available
    m = compute_error_metrics([np.nan, 100.0], [100.0, np.inf])
    assert m.n == 0 and m.bias_mw is None


def test_nan_pairs_are_excluded_but_valid_pairs_kept():
    m = compute_error_metrics([110, np.nan, 90], [100, 100, 100])
    assert m.n == 2
    assert m.bias_mw == pytest.approx(0.0)


def test_mismatched_lengths_rejected():
    with pytest.raises(ValueError):
        compute_error_metrics([1, 2, 3], [1, 2])


def test_percentile_helper():
    assert percentile([], 95) is None
    assert percentile([1, 2, 3, 4, 5], 50) == pytest.approx(3)
