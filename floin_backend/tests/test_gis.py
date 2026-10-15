import numpy as np
import pytest
import rasterio
from rasterio.warp import Resampling
from shapely.geometry import GeometryCollection, LineString, Point, Polygon

from app.core.config import MODEL_AREA_WGS84
from app.core.errors import DataValidationError
from app.gis.grid import ModelGrid
from app.gis.raster import read_float, reproject_to_grid, write_raster
from app.gis.vector import LINEAR, POLYGONAL, coerce_geometry
from app.simulation.dem import repair_artifacts, sea_mask


def small_grid(res=30.0):
    return ModelGrid.from_bounds((80.20, 13.00, 80.23, 13.03), "EPSG:32644", res)


def test_model_grid_is_snapped_and_inside_bounds():
    grid = ModelGrid.from_bounds(MODEL_AREA_WGS84, "EPSG:32644", 30)
    left, bottom, right, top = grid.bounds
    assert left % 30 == 0 and top % 30 == 0
    assert grid.crs.to_epsg() == 32644 and grid.cell_area_m2 == 900


def test_alignment_check_rejects_shifted_grid(tmp_path):
    grid = small_grid()
    path = write_raster(tmp_path / "a.tif", np.zeros(grid.shape), grid, "float32", -9999.0)
    with rasterio.open(path) as src:
        grid.require_aligned(src.profile, "a")
        profile = src.profile.copy()
    profile["transform"] = profile["transform"] @ rasterio.Affine.translation(0.5, 0)
    with pytest.raises(DataValidationError):
        grid.require_aligned(profile, "shifted")


def test_nodata_round_trip(tmp_path):
    grid = small_grid()
    data = np.ones(grid.shape)
    data[0, 0] = np.nan
    path = write_raster(tmp_path / "n.tif", data, grid, "float32", -9999.0)
    back = read_float(path, grid)
    assert np.isnan(back[0, 0]) and back[1, 1] == 1


def test_categorical_reprojection_keeps_class_values(tmp_path):
    fine, coarse = small_grid(10), small_grid(30)
    classes = np.where(np.arange(fine.width) % 2 == 0, 10, 50)[None, :].repeat(fine.height, 0)
    path = write_raster(tmp_path / "lc.tif", classes, fine, "uint8", 0)
    out = reproject_to_grid(path, coarse, Resampling.mode, dst_dtype="uint8", dst_nodata=0)
    assert set(np.unique(out)) <= {0, 10, 50}


def test_geometry_coercion():
    collection = GeometryCollection([Polygon([(0, 0), (1, 0), (1, 1)]), LineString([(0, 0), (2, 2)]), Point(5, 5)])
    assert coerce_geometry(collection, POLYGONAL).geom_type == "MultiPolygon"
    assert coerce_geometry(collection, LINEAR).geom_type == "MultiLineString"
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])            # self-intersecting
    assert coerce_geometry(bowtie, POLYGONAL).is_valid
    assert coerce_geometry(Point(0, 0), POLYGONAL) is None


def test_sea_mask_keeps_inland_lakes():
    landcover = np.full((5, 6), 50, dtype=np.uint8)
    landcover[:, -2:] = 80          # sea on the east edge
    landcover[2, 1] = 80            # inland lake
    sea = sea_mask(landcover)
    assert sea[:, -2:].all() and not sea[2, 1]


def test_dem_artifact_repair():
    dem = np.full((9, 9), 5.0)
    dem[4, 4] = -60.0
    repaired, n = repair_artifacts(dem, np.ones_like(dem, dtype=bool))
    assert n == 1 and repaired[4, 4] == pytest.approx(5.0)
