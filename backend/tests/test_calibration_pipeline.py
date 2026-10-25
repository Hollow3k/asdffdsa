from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
import pytest
from sqlalchemy import select

from app.core.errors import Conflict, ValidationFailed
from app.core.timeutils import local_day_hours_utc, previous_day_cutoff_utc, to_uk
from app.models.calibration import Calibration, CalibrationObservation
from app.services.calibration import build_calibration_dataset, validate_calibration_range
from app.services.data_normalization import aggregate_actuals_hourly
from tests.conftest import make_client
from tests.fakes import BIAS, base


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def dataset_for(container, start: date, end: date, cutoff=time(17, 0), shuffle=False, **kw):
    pub_from = previous_day_cutoff_utc(start, cutoff) - timedelta(hours=72)
    pub_to = previous_day_cutoff_utc(end, cutoff)
    vint, _ = container.store.get_forecast_vintages(pub_from, pub_to)
    half, _ = container.store.get_half_hourly_actuals(start, end)
    if shuffle:
        vint = vint.sample(frac=1.0, random_state=1).reset_index(drop=True)
        half = half.sample(frac=1.0, random_state=2).reset_index(drop=True)
    return build_calibration_dataset(vint, aggregate_actuals_hourly(half), start, end, cutoff, **kw)


# ------------------------------------------------------------------ alignment & errors


def test_pairs_match_by_delivery_time_even_when_input_rows_are_shuffled(container):
    ds = dataset_for(container, date(2025, 11, 3), date(2025, 11, 5), shuffle=True)
    obs = ds.observations
    assert len(obs) == 72
    for r in obs.itertuples():
        ts = r.delivery_start.to_pydatetime()
        assert r.actual_mw == pytest.approx(base(ts))  # actual of THAT hour: mean of the two half-hours
        lead = (ts - r.forecast_publish_time.to_pydatetime()).total_seconds() / 3600
        assert r.forecast_mw == pytest.approx(base(ts) + BIAS + lead, abs=1e-3)  # forecast of THAT hour
        assert r.error_mw == pytest.approx(r.forecast_mw - r.actual_mw)  # error = forecast - actual
    assert (obs["error_mw"] > 0).all()  # fake forecasts are always too high -> positive = over-forecast


def test_no_forecast_published_after_its_historical_cutoff_is_used(container):
    ds = dataset_for(container, date(2025, 11, 1), date(2025, 11, 30))
    obs = ds.observations
    assert (obs["forecast_publish_time"] <= obs["decision_cutoff"]).all()
    # Cutoff is 17:00 UK on the previous day (GMT in November)
    for r in obs.itertuples():
        expected = previous_day_cutoff_utc(r.delivery_date, time(17, 0))
        assert r.decision_cutoff.to_pydatetime() == expected
    # Actuals are only counted once observed
    assert (obs["actual_available_at"] >= obs["delivery_start"] + pd.Timedelta(hours=1)).all()


def test_dst_fall_back_day_has_25_hours_and_both_duplicate_local_hours_matched(container):
    ds = dataset_for(container, date(2025, 10, 25), date(2025, 10, 27))
    day = ds.observations[ds.observations["delivery_date"] == date(2025, 10, 26)]
    assert len(day) == 25
    assert sorted(day["hour_local"].tolist()).count(1) == 2  # 01:00 BST and 01:00 GMT
    assert ds.quality["expected_hours"] == 24 + 25 + 24
    assert ds.quality["unmatched_hours"] == 0


def test_bst_delivery_day_spans_two_utc_dates(container):
    ds = dataset_for(container, date(2025, 10, 2), date(2025, 10, 2))
    starts = [h.to_pydatetime() for h in ds.observations["delivery_start"]]
    assert starts[0] == utc(2025, 10, 1, 23)  # 00:00 BST of 2 Oct is 23:00 UTC of 1 Oct
    assert {to_uk(s).date() for s in starts} == {date(2025, 10, 2)}
    assert {s.date() for s in starts} == {date(2025, 10, 1), date(2025, 10, 2)}


# ------------------------------------------------------------------ missing data


def test_missing_actual_half_hour_excludes_that_hour_and_is_reported(container, fake):
    gone = utc(2025, 11, 4, 10, 30)
    fake.drop_actual = lambda t: t == gone
    ds = dataset_for(container, date(2025, 11, 4), date(2025, 11, 4))
    assert len(ds.observations) == 23
    assert utc(2025, 11, 4, 10) not in [h.to_pydatetime() for h in ds.observations["delivery_start"]]
    q = ds.quality
    assert q["hours_missing_actual"] == 1 and q["hours_incomplete_actual"] == 1
    assert q["unmatched_hours"] == 1 and q["matched_pairs"] == 23
    assert any(w["code"] == "MISSING_ACTUAL_HOURS" for w in ds.warnings)


def test_missing_forecast_hours_are_excluded_not_filled(container, fake):
    # Remove hour 12:00 on Nov 5 from every vintage: it can never be matched.
    target = utc(2025, 11, 5, 12)
    fake.drop_forecast = lambda pub, start: start == target
    ds = dataset_for(container, date(2025, 11, 5), date(2025, 11, 5))
    assert len(ds.observations) == 23
    assert ds.quality["hours_missing_forecast"] == 1 and ds.quality["days_with_incomplete_forecast"] == 1
    assert any(w["code"] == "MISSING_FORECAST_HOURS" for w in ds.warnings)


def test_incomplete_latest_vintage_falls_back_to_complete_one_and_flags_it(container, fake):
    # Cutoff 17:00 on Nov 9 -> latest vintage 14:30. Make it miss the evening of Nov 10.
    fake.drop_forecast = lambda pub, start: pub == utc(2025, 11, 9, 14, 30) and start.hour >= 18 and start.day == 10
    ds = dataset_for(container, date(2025, 11, 10), date(2025, 11, 10))
    assert len(ds.observations) == 24
    assert ds.quality["days_using_fallback_vintage"] == 1
    assert set(ds.observations["forecast_publish_time"]) == {pd.Timestamp(utc(2025, 11, 9, 11, 30))}
    assert any(w["code"] == "FALLBACK_VINTAGE_USED" for w in ds.warnings)


def test_day_without_any_eligible_forecast_yields_no_pairs_and_warning(container, fake):
    fake.drop_vintage = lambda pub: pub.date() == date(2025, 11, 9)
    ds = dataset_for(container, date(2025, 11, 10), date(2025, 11, 10))
    # Earlier vintage from 8 Nov 23:30 still covers 10 Nov 00:00-... only partially; nothing is invented.
    assert ds.quality["matched_pairs"] == len(ds.observations)
    assert ds.quality["hours_missing_forecast"] == 24 - len(ds.observations)


def test_low_sample_warning(container):
    ds = dataset_for(container, date(2025, 11, 3), date(2025, 11, 4), low_sample_pairs=500)
    assert any(w["code"] == "LOW_SAMPLE" for w in ds.warnings)


# ------------------------------------------------------------------ validation


def test_range_validation():
    today = date(2026, 6, 1)
    validate_calibration_range(date(2025, 10, 1), date(2025, 12, 31), today=today, max_days=400)
    with pytest.raises(ValidationFailed):
        validate_calibration_range(date(2025, 12, 31), date(2025, 10, 1), today=today, max_days=400)
    with pytest.raises(ValidationFailed):
        validate_calibration_range(date(2024, 1, 1), date(2025, 12, 31), today=today, max_days=400)
    with pytest.raises(ValidationFailed):
        validate_calibration_range(date(2026, 5, 1), today, today=today, max_days=400)  # today not yet complete


# ------------------------------------------------------------------ jobs, persistence, versions


def new_cal(container, start=date(2025, 11, 1), end=date(2025, 11, 30), **kw):
    return container.calibrations.submit(start, end, "17:00", **kw)


def reload(container, cid) -> Calibration:
    with container.session_factory() as s:
        return s.get(Calibration, cid)


def test_calibration_completes_and_persists_everything_needed_to_reproduce(container):
    cal = new_cal(container)
    c = reload(container, cal.id)
    assert c.status == "completed" and c.progress == 100
    assert c.version == 1 and c.is_active  # first calibration auto-activates
    assert c.settings["cutoff_time"] == "17:00" and c.settings["error_convention"] == "forecast_mw - actual_mw"
    assert c.metric_version == "v1" and c.completed_at is not None
    assert c.metrics["n"] == 30 * 24 and c.metrics["bias_mw"] > BIAS
    assert c.quality["matched_pairs"] == 720 and c.warnings is not None
    with container.session_factory() as s:
        n = s.execute(select(CalibrationObservation).where(CalibrationObservation.calibration_id == cal.id)).scalars().all()
    assert len(n) == 720


def test_calibration_survives_restart(settings, fake, container):
    cal = new_cal(container)
    container.close()
    # "Restart": a brand new container on the same database file.
    from app.container import build_container

    c2 = build_container(settings, client=make_client(settings, fake), run_inline=True)
    try:
        c = reload(c2, cal.id)
        assert c.status == "completed" and c.is_active and c.metrics["n"] == 720
        with c2.session_factory() as s:
            assert len(s.execute(select(CalibrationObservation)).scalars().all()) == 720
    finally:
        c2.close()


def test_new_version_does_not_replace_active_until_activated(container):
    v1 = new_cal(container)
    v2 = new_cal(container, date(2025, 10, 1), date(2025, 10, 20))
    assert (reload(container, v1.id).is_active, reload(container, v2.id).is_active) == (True, False)
    assert reload(container, v2.id).version == 2
    container.calibrations.activate(v2.id)
    assert (reload(container, v1.id).is_active, reload(container, v2.id).is_active) == (False, True)
    # reactivating an earlier version is possible and v1 data is intact
    container.calibrations.activate(v1.id)
    assert (reload(container, v1.id).is_active, reload(container, v2.id).is_active) == (True, False)
    assert reload(container, v1.id).metrics["n"] == 720


def test_failed_recalculation_keeps_previous_active_calibration_intact(container, fake):
    v1 = new_cal(container)
    before = reload(container, v1.id).metrics
    fake.fail_with = 503  # Elexon down for the recalculation
    v2 = new_cal(container, date(2025, 10, 1), date(2025, 10, 20))
    failed = reload(container, v2.id)
    assert failed.status == "failed" and failed.error_code == "ELEXON_UNAVAILABLE" and not failed.is_active
    assert failed.metrics is None
    with container.session_factory() as s:
        assert s.execute(select(CalibrationObservation).where(CalibrationObservation.calibration_id == v2.id)).first() is None
    kept = reload(container, v1.id)
    assert kept.is_active and kept.status == "completed" and kept.metrics == before
    with pytest.raises(Conflict):
        container.calibrations.activate(v2.id)  # failed versions cannot be activated


def test_failure_midway_does_not_leave_partial_observations(container, fake):
    # The first (actuals) request succeeds, then the API starts failing.
    fake.fail_with = 500
    fake.fail_after_calls = 1
    cal = new_cal(container)
    c = reload(container, cal.id)
    assert c.status == "failed"
    with container.session_factory() as s:
        assert s.execute(select(CalibrationObservation)).first() is None


def test_empty_api_response_fails_clearly_without_fabricating_data(container, fake):
    fake.world_end = datetime(2025, 8, 1, tzinfo=UTC)  # world has no data for the range
    cal = new_cal(container)
    c = reload(container, cal.id)
    assert c.status == "failed" and c.error_code == "NO_DATA" and c.metrics is None


def test_too_few_pairs_fails(container):
    cal = new_cal(container, date(2025, 11, 3), date(2025, 11, 4))  # 48 < 72
    c = reload(container, cal.id)
    assert c.status == "failed" and "at least 72" in (c.error_message or "")


def test_concurrent_job_is_rejected(container):
    from app.models.calibration import STATUS_RUNNING

    cal = new_cal(container)
    with container.session_factory() as s:
        c = s.get(Calibration, cal.id)
        c.status = STATUS_RUNNING
        s.commit()
    with pytest.raises(Conflict) as ei:
        new_cal(container, date(2025, 12, 1), date(2025, 12, 10))
    assert ei.value.code == "CALIBRATION_IN_PROGRESS"


def test_interrupted_jobs_are_marked_failed_on_startup_and_active_untouched(container):
    from app.models.calibration import STATUS_RUNNING

    v1 = new_cal(container)
    v2 = new_cal(container, date(2025, 10, 1), date(2025, 10, 20))
    with container.session_factory() as s:
        s.get(Calibration, v2.id).status = STATUS_RUNNING
        s.commit()
    assert container.calibrations.recover_interrupted() == 1
    assert reload(container, v2.id).status == "failed" and reload(container, v2.id).error_code == "INTERRUPTED"
    assert reload(container, v1.id).is_active


def test_cached_history_is_not_refetched(container, fake):
    new_cal(container)
    first = len(fake.requests)
    new_cal(container)  # identical range -> served from the local store
    assert len(fake.requests) == first


def test_calendar_dst_range_calibration_runs(container):
    cal = new_cal(container, date(2025, 10, 20), date(2025, 11, 10))
    c = reload(container, cal.id)
    assert c.status == "completed"
    assert c.metrics["n"] == 22 * 24 + 1  # one extra hour on 26 Oct
    assert len(local_day_hours_utc(date(2025, 10, 26))) == 25
