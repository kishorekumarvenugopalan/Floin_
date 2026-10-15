"""Read-only map/display endpoints used by the frontend."""
import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.services.display_service import block_reduce, grid_factor
from tests.conftest import requires_db

client = TestClient(app)
API = "/api/v1"


def test_block_reduce_is_nan_aware():
    a = np.array([[1.0, 3.0, np.nan], [5.0, 7.0, np.nan]])
    assert block_reduce(a, 2).tolist() == [[4.0, np.nan]] or np.isnan(block_reduce(a, 2)[0, 1])
    assert block_reduce(a, 2)[0, 0] == 4.0 and block_reduce(a, 2, "max")[0, 0] == 7.0
    assert grid_factor((1662, 1269), 256) == 7


@requires_db
def test_layer_catalog_lists_only_usable_vector_layers():
    layers = client.get(f"{API}/layers").json()
    names = {l["name"] for l in layers}
    assert {"wards_gcc", "osm_roads", "flood_2015_inundation"} <= names
    assert all(l["status"] in ("available", "limited") for l in layers)


@requires_db
def test_layer_bbox_and_limit_are_independent():
    """Regression: the bbox north edge was bound to the same SQL parameter as the row limit."""
    url = f"{API}/layers/osm_roads/geojson"
    small = client.get(url, params={"bbox": "80.20,13.00,80.30,13.10", "limit": 20}).json()
    assert small["properties"]["returned"] == 20 and small["properties"]["truncated"] is True
    for f in small["features"]:
        xs = [c[0] for c in f["geometry"]["coordinates"]] if f["geometry"]["type"] == "LineString" \
            else [c[0] for part in f["geometry"]["coordinates"] for c in part]
        assert min(xs) < 80.31 and max(xs) > 80.19      # lon/lat order, inside/overlapping the bbox


@requires_db
def test_layer_errors_are_json():
    assert client.get(f"{API}/layers/osm_roads/geojson", params={"bbox": "x"}).status_code == 422
    assert client.get(f"{API}/layers/dem_30m/geojson").status_code == 422
    assert client.get(f"{API}/layers/rejected:highway/geojson").status_code == 409


@requires_db
def test_raster_preview_is_georeferenced_png():
    meta = client.get(f"{API}/rasters/dem_30m/preview", params={"max_size": 256}).json()
    (south, west), (north, east) = meta["bounds"]
    assert 12.8 < south < north < 13.35 and 80.0 < west < east < 80.45
    assert meta["crs_of_image"] == "EPSG:3857" and meta["legend"]["unit"] == "m"
    png = client.get(f"{API}/rasters/dem_30m/preview.png", params={"max_size": 256})
    assert png.headers["content-type"] == "image/png" and png.content[:8] == b"\x89PNG\r\n\x1a\n"


@requires_db
def test_terrain_grid_shape_and_units():
    g = client.get(f"{API}/terrain/grid", params={"max_size": 64}).json()
    assert len(g["values"]) == g["height"] and len(g["values"][0]) == g["width"]
    assert g["cell_size_m"] == 30 * g["downsample_factor"] and g["unit"] == "m"
    assert any(v is None for row in g["values"] for v in row)        # sea is null, not 0


@requires_db
def test_chirps_rainfall_series():
    r = client.get(f"{API}/rainfall/chirps").json()
    days = {d["date"]: d for d in r["days"]}
    assert "2015-12-01" in days and days["2015-12-01"]["mean_mm"] > 100


@requires_db
def test_simulation_views():
    runs = client.get(f"{API}/simulations", params={"limit": 50}).json()
    done = [r["id"] for r in runs if r["status"] == "completed"]
    if not done:
        return
    sid = done[0]
    wards = client.get(f"{API}/simulations/{sid}/wards").json()
    assert len(wards["features"]) == 201
    meta = client.get(f"{API}/simulations/{sid}/outputs/flood_depth/preview", params={"max_size": 256}).json()
    assert meta["legend"]["kind"] == "depth_classes"
    assert client.get(f"{API}/simulations/{sid}/outputs/nope/preview").status_code == 422
    overlay = client.get(f"{API}/simulations/{sid}/terrain-overlay", params={"max_size": 64}).json()
    grid = client.get(f"{API}/terrain/grid", params={"max_size": 64}).json()
    assert len(overlay["depth_mean"]) == grid["height"] and len(overlay["depth_mean"][0]) == grid["width"]


@requires_db
def test_validation_list():
    assert isinstance(client.get(f"{API}/validation").json(), list)
