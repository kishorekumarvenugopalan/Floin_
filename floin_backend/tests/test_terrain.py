"""D8, depression filling and accumulation on small synthetic grids (test fixtures only)."""
import numpy as np

from app.simulation.accumulation import accumulate
from app.simulation.d8 import d8_receivers, priority_flood


def route(dem, domain=None, cell=30.0):
    domain = np.isfinite(dem) if domain is None else domain
    filled, order, flood_recv = priority_flood(dem, domain)
    receiver, codes = d8_receivers(filled, domain, flood_recv, cell)
    return filled, order, receiver, codes


def test_plane_sloping_east_drains_east():
    dem = np.tile(np.arange(10, 0, -1, dtype=float), (5, 1))     # elevation falls eastward
    _, _, receiver, codes = route(dem)
    assert (codes[1:-1, 1:-2] == 1).all()                        # ESRI code 1 = east


def test_diagonal_distance_is_used():
    # Centre cell 10; east neighbour 9 (drop 1 / 30) beats south-east neighbour 8.7 (drop 1.3 / 42.4).
    dem = np.full((3, 3), 20.0)
    dem[1, 1], dem[1, 2], dem[2, 2] = 10.0, 9.0, 8.7
    _, _, receiver, _ = route(dem)
    assert receiver[4] == 5


def test_pit_is_filled_to_its_spill_level():
    dem = np.full((5, 5), 10.0)
    dem[2, 2] = 2.0
    dem[0, 2] = 9.0                                             # lowest rim point
    filled, *_ = route(dem)
    assert filled[2, 2] == 10.0
    assert np.all(filled >= dem)


def test_network_is_acyclic_and_reaches_outlets():
    rng = np.random.default_rng(0)                              # random terrain fixture
    dem = rng.random((40, 40)) * 5
    filled, order, receiver, _ = route(dem)
    rank = np.empty(dem.size, dtype=int)
    rank[order] = np.arange(order.size)
    has = receiver >= 0
    assert np.all(rank[receiver[has]] < rank[np.flatnonzero(has)])
    acc, outflow = accumulate(order, receiver, np.ones(dem.shape))
    assert outflow == dem.size                                  # every cell's unit leaves the domain once


def test_accumulation_counts_upstream_cells():
    dem = np.tile(np.arange(6, 0, -1, dtype=float), (3, 1))
    domain = np.zeros_like(dem, dtype=bool)
    domain[1, :] = True                                         # single row of cells
    _, order, receiver, _ = route(np.where(domain, dem, np.nan), domain)
    acc, _ = accumulate(order, receiver, domain.astype(float))
    assert acc[1].tolist() == [1, 2, 3, 4, 5, 6]


def test_runoff_weighted_accumulation_conserves_volume():
    rng = np.random.default_rng(1)
    dem = rng.random((30, 30)) * 3
    _, order, receiver, _ = route(dem)
    volume = rng.random(dem.shape) * 10
    _, outflow = accumulate(order, receiver, volume)
    assert outflow == np.float64(volume.sum()) or abs(outflow - volume.sum()) < 1e-9
