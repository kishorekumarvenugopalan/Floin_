from dataclasses import dataclass

import numpy as np
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import transform_bounds

from app.core.errors import DataValidationError


@dataclass(frozen=True)
class ModelGrid:
    """The single raster grid every model layer is aligned to (CRS, cell size, origin, shape)."""

    crs: CRS
    transform: Affine
    width: int
    height: int

    @classmethod
    def from_bounds(cls, bounds_wgs84, crs: str, resolution: float) -> "ModelGrid":
        """Grid snapped to whole multiples of `resolution`, kept *inside* the given lon/lat box
        so no edge cell extends beyond the source data."""
        target = CRS.from_user_input(crs)
        left, bottom, right, top = transform_bounds("EPSG:4326", target, *bounds_wgs84, densify_pts=101)
        left = np.ceil(left / resolution) * resolution
        bottom = np.ceil(bottom / resolution) * resolution
        right = np.floor(right / resolution) * resolution
        top = np.floor(top / resolution) * resolution
        width = int(round((right - left) / resolution))
        height = int(round((top - bottom) / resolution))
        return cls(target, Affine(resolution, 0, left, 0, -resolution, top), width, height)

    @classmethod
    def from_profile(cls, profile) -> "ModelGrid":
        return cls(CRS.from_user_input(profile["crs"]), profile["transform"], profile["width"], profile["height"])

    @property
    def shape(self) -> tuple[int, int]:
        return self.height, self.width

    @property
    def resolution(self) -> float:
        return abs(self.transform.a)

    @property
    def cell_area_m2(self) -> float:
        return abs(self.transform.a * self.transform.e)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        left, top = self.transform.c, self.transform.f
        return left, top + self.transform.e * self.height, left + self.transform.a * self.width, top

    def profile(self, dtype: str, nodata) -> dict:
        return {
            "driver": "GTiff", "crs": self.crs, "transform": self.transform,
            "width": self.width, "height": self.height, "count": 1,
            "dtype": dtype, "nodata": nodata, "compress": "deflate",
            "tiled": True, "blockxsize": 256, "blockysize": 256,
        }

    def require_aligned(self, profile, name: str) -> None:
        """Raise unless a raster profile matches this grid exactly (no silent resampling)."""
        other = ModelGrid.from_profile(profile)
        problems = []
        if other.crs != self.crs:
            problems.append(f"CRS {other.crs} != {self.crs}")
        if (other.width, other.height) != (self.width, self.height):
            problems.append(f"shape {other.height}x{other.width} != {self.height}x{self.width}")
        if not other.transform.almost_equals(self.transform, precision=1e-6):
            problems.append(f"transform {tuple(other.transform)[:6]} != {tuple(self.transform)[:6]}")
        if problems:
            raise DataValidationError(f"{name} is not aligned to the model grid: " + "; ".join(problems))

    def as_dict(self) -> dict:
        return {
            "crs": self.crs.to_string(), "resolution_m": self.resolution,
            "width": self.width, "height": self.height, "bounds": list(self.bounds),
            "transform": list(self.transform)[:6],
        }
