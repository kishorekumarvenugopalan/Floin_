"""Fill-and-spill depth and extent on synthetic grids with analytic answers (test fixtures only)."""
import numpy as np
import pytest

from app.simulation.d8 import d8_receivers, priority_flood
from app.simulation.flood_depth import fill_and_spill, flood_depth, identify_depressions
from app.simulation.flood_extent import classify, summarize

CELL = 30.0
AREA = CELL * CELL


def bowl():
    """7x7 plateau at 10 m with a 3x3 basin at 4 m; rim spill point at 8 m on the north edge."""
    dem = np.full((7, 7), 10.0)
    dem[2:5, 2:5] = 4.0
    dem[1, 3] = 8.0
    dem[0, 3] = 8.0
    return dem


def run(dem, inflow):
    domain = np.isfinite(dem)
    filled, order, flood_recv = priority_flood(dem, domain)
    receiver, _ = d8_receivers(filled, domain, flood_recv, CELL)
    labels, capacity, spill = identify_depressions(dem, filled, domain, AREA)
    stored, outflow, _ = fill_and_spill(order, receiver, inflow, labels, capacity)
    surface, depth = flood_depth(labels, dem, stored, spill, AREA)
    return labels, capacity, stored, outflow, depth


def test_capacity_matches_geometry():
    labels, capacity, *_ = run(bowl(), np.zeros((7, 7)))
    # 9 basin cells, 4 m deep below the 8 m spill level; the rim cell (1,3) is at spill level.
    assert capacity.sum() == pytest.approx(9 * 4.0 * AREA)


def test_partial_fill_gives_flat_surface_and_conserves_volume():
    inflow = np.zeros((7, 7))
    inflow[3, 3] = 9 * AREA * 1.5             # enough for 1.5 m over the 9 basin cells
    _, _, stored, outflow, depth = run(bowl(), inflow)
    assert stored.sum() == pytest.approx(inflow.sum())
    assert outflow == pytest.approx(0.0)
    assert depth[2:5, 2:5] == pytest.approx(np.full((3, 3), 1.5))
    assert (depth * AREA).sum() == pytest.approx(inflow.sum())


def test_overflow_spills_and_leaves_domain():
    inflow = np.zeros((7, 7))
    inflow[3, 3] = 9 * AREA * 4.0 + 5000.0    # capacity + 5000 m3 excess
    _, capacity, stored, outflow, depth = run(bowl(), inflow)
    assert stored.sum() == pytest.approx(capacity.sum())
    assert outflow == pytest.approx(5000.0)
    assert depth[3, 3] == pytest.approx(4.0)


def test_rain_on_plateau_runs_into_basin():
    inflow = np.full((7, 7), 10.0)            # 10 m3 on every cell
    _, _, stored, outflow, _ = run(bowl(), inflow)
    assert stored.sum() + outflow == pytest.approx(inflow.sum())
    assert stored.sum() > 0


def test_mass_balance_on_random_terrain():
    rng = np.random.default_rng(3)
    dem = rng.random((50, 50)) * 4            # synthetic rough terrain fixture
    inflow = rng.random(dem.shape) * 50
    _, _, stored, outflow, depth = run(dem, inflow)
    assert stored.sum() + outflow == pytest.approx(inflow.sum(), rel=1e-9)
    assert (depth * AREA).sum() == pytest.approx(stored.sum(), rel=1e-6)


def test_classes_and_threshold():
    depth = np.array([0.05, 0.2, 0.5, 1.5, 2.5, 3.0])
    mask = np.array([True, True, True, True, True, False])
    classes = classify(depth, mask, 0.1, (0.3, 1.0, 2.0))
    assert classes.tolist() == [0, 1, 2, 3, 4, 0]
    summary = summarize(depth, classes, AREA, ("low", "moderate", "high", "severe"))
    assert summary["flooded_cells"] == 4 and summary["max_depth_m"] == 2.5
    with pytest.raises(ValueError):
        classify(depth, mask, 0.5, (0.3, 1.0))


def test_validation_metrics_are_json_serialisable():
    """Regression: NumPy integers in point metrics broke json.dumps when storing validation results."""
    import json

    import shapely
    from affine import Affine

    from app.gis.grid import ModelGrid
    from app.services.validation_service import _point_metrics, binary_metrics
    from rasterio.crs import CRS

    grid = ModelGrid(CRS.from_epsg(32644), Affine(30, 0, 0, 0, -30, 300), 10, 10)
    depth = np.zeros((10, 10))
    depth[5, 5] = 0.8
    mask = np.ones((10, 10), dtype=bool)
    items = [(shapely.Point(165, 135), 0.6096, 0.9144, "2-3 ft"), (shapely.Point(15, 285), 0.0, 0.6096, "<2 ft")]
    row = _point_metrics(({"name": "fixture"}, items), depth, mask, grid, 0.1, with_classes=True)
    json.dumps(row["details"])
    assert row["details"]["detected_within_1_cell"] == 1 and row["details"]["depth_class_agreement"] == 0.5
    json.dumps(binary_metrics(depth > 0.5, depth > 0.1, 900.0))


def test_chance_extent_metrics():
    from app.services.validation_service import chance_extent_metrics

    mask = np.ones((10, 10), dtype=bool)
    predicted = np.zeros((10, 10), dtype=bool)
    predicted[:5] = True                      # 50 % predicted
    observed = np.zeros((10, 10), dtype=bool)
    observed[:, :2] = True                    # 20 % observed
    ch = chance_extent_metrics(predicted, observed, mask, 900.0)
    assert ch["chance_precision"] == pytest.approx(0.2)
    assert ch["chance_iou"] == pytest.approx(0.1 / (0.5 + 0.2 - 0.1))
