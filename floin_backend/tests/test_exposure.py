"""Exposure SQL on a tiny synthetic layout (test fixture), inside a rolled-back transaction."""
import json

import pytest
from shapely.geometry import box
from sqlalchemy import text

from app.db.database import get_engine
from app.services.exposure_service import compute_exposure, store_flood_polygons
from tests.conftest import requires_db

pytestmark = requires_db

X0, Y0 = 300000.0, 1300000.0     # outside the model area, so no real features interfere (EPSG:32644)


@pytest.fixture
def tx():
    with get_engine().connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()       # nothing written by the test persists


def line(x0, x1, y):
    return f"SRID=32644;MULTILINESTRING(({x0} {y}, {x1} {y}))"


def test_bridges_and_tunnels_are_not_counted_as_flooded(tx):
    ds = tx.execute(text("""
        INSERT INTO floin.datasets (name, title, dataset_type, category, stage, storage_kind, table_name, status)
        VALUES ('test_fixture_layout', 'test fixture', 'vector', 'test', 'processed', 'postgis', 'floin.roads', 'available')
        RETURNING id""")).scalar_one()
    sid = "SIM-TEST-EXPOSURE"
    tx.execute(text("""
        INSERT INTO floin.simulation_runs (id, status, scenario, rainfall_source, rainfall_mm, duration_hours, parameters, model_version)
        VALUES (:sid, 'running', 'test', 'uniform', 1, 1, '{}', 'test')"""), {"sid": sid})
    # 100 m flood square; three roads cross it fully: at grade, bridge, tunnel.
    store_flood_polygons(tx, sid, [(box(X0, Y0, X0 + 100, Y0 + 100), 2)])
    for tags, y in (({}, 20), ({"bridge": "yes"}, 50), ({"tunnel": "yes"}, 80)):
        tx.execute(text("""
            INSERT INTO floin.roads (dataset_id, highway, attributes, geom)
            VALUES (:ds, 'primary', CAST(:a AS jsonb), ST_GeomFromEWKT(:g))"""),
            {"ds": ds, "a": json.dumps(tags), "g": line(X0 - 50, X0 + 150, Y0 + y)})
    tx.execute(text("""
        INSERT INTO floin.railways (dataset_id, railway, is_metro, attributes, geom)
        VALUES (:ds, 'subway', true, '{"bridge": "viaduct"}', ST_GeomFromEWKT(:g)),
               (:ds, 'rail', false, '{}', ST_GeomFromEWKT(:h))"""),
        {"ds": ds, "g": line(X0 - 50, X0 + 150, Y0 + 40), "h": line(X0 - 50, X0 + 150, Y0 + 60)})

    exposure = compute_exposure(tx, sid, ["low", "moderate", "high", "severe"])

    assert exposure["roads"]["affected_km"] == pytest.approx(0.1, abs=1e-6)                  # only the at-grade road
    assert exposure["roads"]["excluded_bridge_or_tunnel_km"] == pytest.approx(0.2, abs=1e-6)
    assert exposure["railways"]["affected_metro_km"] == pytest.approx(0.0)
    assert exposure["railways"]["excluded_bridge_or_tunnel_metro_km"] == pytest.approx(0.1, abs=1e-6)
    assert exposure["railways"]["affected_rail_km"] == pytest.approx(0.1, abs=1e-6)
