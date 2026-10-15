import hashlib
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject, transform_bounds

from app.core.errors import DataValidationError
from app.gis.grid import ModelGrid


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_band(path: Path, grid: ModelGrid | None = None, name: str | None = None):
    """Read band 1 and its profile. If a grid is given, the raster must already match it."""
    with rasterio.open(path) as src:
        data = src.read(1)
        profile = src.profile.copy()
    if grid is not None:
        grid.require_aligned(profile, name or Path(path).name)
    return data, profile


def read_float(path: Path, grid: ModelGrid | None = None, name: str | None = None) -> np.ndarray:
    """Read band 1 as float64 with NoData converted to NaN."""
    data, profile = read_band(path, grid, name)
    data = data.astype("float64")
    nodata = profile.get("nodata")
    if nodata is not None:
        data[data == nodata] = np.nan
    return data


def write_raster(path: Path, array: np.ndarray, grid: ModelGrid, dtype: str, nodata) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(array)
    if np.issubdtype(data.dtype, np.floating) and nodata is not None:
        data = np.where(np.isnan(data), nodata, data)
    with rasterio.open(path, "w", **grid.profile(dtype, nodata)) as dst:
        dst.write(data.astype(dtype), 1)
    return path


def reproject_to_grid(src_path: Path, grid: ModelGrid, resampling: Resampling, dst_dtype="float32",
                      dst_nodata=-9999.0, src_nodata=None) -> np.ndarray:
    """Warp a raster onto the model grid. The caller chooses the resampling method
    (continuous data: bilinear/average; categorical data: nearest/mode)."""
    destination = np.full(grid.shape, dst_nodata, dtype=dst_dtype)
    with rasterio.open(src_path) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=destination,
            src_transform=src.transform, src_crs=src.crs,
            src_nodata=src.nodata if src_nodata is None else src_nodata,
            dst_transform=grid.transform, dst_crs=grid.crs, dst_nodata=dst_nodata,
            resampling=resampling, init_dest_nodata=True,
        )
    return destination


def raster_metadata(path: Path) -> dict:
    """Facts for the dataset catalog, computed from the file itself."""
    path = Path(path)
    with rasterio.open(path) as src:
        data = src.read(1, masked=True)
        bounds = src.bounds
        footprint = transform_bounds(src.crs, "EPSG:4326", *bounds, densify_pts=21)
        valid = data.compressed()
        meta = {
            "crs": src.crs.to_string(),
            "srid": src.crs.to_epsg(),
            "resolution_x": abs(src.res[0]),
            "resolution_y": abs(src.res[1]),
            "width": src.width,
            "height": src.height,
            "min_x": bounds.left, "min_y": bounds.bottom, "max_x": bounds.right, "max_y": bounds.top,
            "footprint_wgs84": footprint,
            "dtype": src.dtypes[0],
            "nodata_value": src.nodata,
            "min_value": float(valid.min()) if valid.size else None,
            "max_value": float(valid.max()) if valid.size else None,
            "valid_fraction": float(valid.size / data.size) if data.size else 0.0,
        }
    meta["size_bytes"] = path.stat().st_size
    meta["checksum_sha256"] = sha256_file(path)
    return meta


def require_crs(profile, expected: str, name: str) -> None:
    if profile.get("crs") is None:
        raise DataValidationError(f"{name} has no CRS")
    if rasterio.crs.CRS.from_user_input(profile["crs"]) != rasterio.crs.CRS.from_user_input(expected):
        raise DataValidationError(f"{name} CRS is {profile['crs']}, expected {expected}")
