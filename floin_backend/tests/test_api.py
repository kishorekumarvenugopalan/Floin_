from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import requires_db

client = TestClient(app)


def test_root():
    assert client.get("/").json()["docs"] == "/docs"


def test_simulation_request_validation():
    assert client.post("/api/v1/simulations", json={"duration_hours": 24}).status_code == 422          # no rainfall
    assert client.post("/api/v1/simulations", json={"rainfall_mm": -5, "duration_hours": 24}).status_code == 422
    both = {"rainfall_mm": 100, "rainfall_dataset": "x", "duration_hours": 24}
    assert client.post("/api/v1/simulations", json=both).status_code == 422
    bad_breaks = {"rainfall_mm": 100, "duration_hours": 24, "depth_class_breaks_m": [1.0, 0.5]}
    assert client.post("/api/v1/simulations", json=bad_breaks).status_code == 422


@requires_db
def test_health_reports_database_and_storage():
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok" and body["postgis"] and body["storage"]["objects"] > 0


@requires_db
def test_datasets_listing_and_lookup():
    rows = client.get("/api/v1/datasets", params={"category": "dem"}).json()
    assert {r["name"] for r in rows} >= {"dem_30m", "dem_cop30_source"}
    assert client.get("/api/v1/datasets/dem_30m").json()["srid"] == 32644
    missing = client.get("/api/v1/datasets/nope")
    assert missing.status_code == 404 and missing.json()["error"] == "not_found"


@requires_db
def test_unknown_simulation_returns_404():
    for path in ("", "/results", "/flood", "/risk"):
        r = client.get(f"/api/v1/simulations/SIM-unknown{path}")
        assert r.status_code == 404, path
