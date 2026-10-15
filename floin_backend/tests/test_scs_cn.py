import numpy as np
import pytest

from app.simulation.scs_cn import retention_mm, runoff_depth_mm, runoff_volume_m3


def test_textbook_case():
    # P = 100 mm, CN = 75: S = 84.667, Ia = 16.933, Q = 83.067^2 / 167.733 = 41.137 mm
    q = runoff_depth_mm(100.0, np.array([75.0]))
    assert retention_mm(np.array([75.0]))[0] == pytest.approx(84.6667, rel=1e-4)
    assert q[0] == pytest.approx(41.137, rel=1e-3)


def test_no_runoff_below_initial_abstraction():
    assert runoff_depth_mm(10.0, np.array([75.0]))[0] == 0.0


def test_cn_100_turns_all_rainfall_into_runoff():
    assert runoff_depth_mm(55.0, np.array([100.0]))[0] == pytest.approx(55.0)


def test_runoff_never_exceeds_rainfall_and_grows_with_cn():
    cn = np.array([40.0, 60.0, 80.0, 98.0])
    q = runoff_depth_mm(300.0, cn)
    assert np.all(q <= 300.0) and np.all(np.diff(q) > 0)


def test_invalid_and_missing_cn_give_nan():
    q = runoff_depth_mm(100.0, np.array([np.nan, 0.0, 120.0, 80.0]))
    assert np.isnan(q[:3]).all() and np.isfinite(q[3])


def test_spatial_rainfall():
    q = runoff_depth_mm(np.array([0.0, 50.0, 200.0]), np.array([90.0, 90.0, 90.0]))
    assert q[0] == 0 and 0 < q[1] < q[2]


def test_negative_rainfall_rejected():
    with pytest.raises(ValueError):
        runoff_depth_mm(-1.0, np.array([80.0]))


def test_volume_is_depth_times_area():
    assert runoff_volume_m3(np.array([50.0]), 900.0)[0] == pytest.approx(45.0)  # 0.05 m x 900 m2
    with pytest.raises(ValueError):
        runoff_volume_m3(np.array([1.0]), 0.0)
