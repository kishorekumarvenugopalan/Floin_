"""Read-only views of stored rasters for the frontend.

Nothing here computes new model results: it reprojects, downsamples and colours rasters
that the pipeline or a simulation already produced.

Map previews are warped to Web Mercator (EPSG:3857) before encoding, so a browser map can
stretch the PNG between its lon/lat corners without misplacing cells (a UTM raster shown
as a plain image would be rotated by the UTM grid convergence).
"""
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds

from app.core.config import MODEL_AREA_WGS84
from app.core.errors import DataValidationError

WEB_MERCATOR = "EPSG:3857"

WORLDCOVER_COLOURS = {
    10: ("#006400", "Tree cover"), 20: ("#ffbb22", "Shrubland"), 30: ("#ffff4c", "Grassland"),
    40: ("#f096ff", "Cropland"), 50: ("#fa0000", "Built-up"), 60: ("#b4b4b4", "Bare / sparse vegetation"),
    80: ("#0064c8", "Permanent water"), 90: ("#0096a0", "Herbaceous wetland"), 95: ("#00cf75", "Mangroves"),
}
HSG_COLOURS = {1: ("#4ade80", "A (low runoff)"), 2: ("#a3e635", "B"), 3: ("#f59e0b", "C"), 4: ("#dc2626", "D (high runoff)")}
DEPTH_CLASS_COLOURS = ["#7dd3fc", "#38bdf8", "#2563eb", "#1e3a8a", "#172554", "#0f172a", "#020617"]

# style name -> (kind, unit, colour stops or palette)
STYLES = {
    "elevation": ("continuous", "m", ["#0b3d2e", "#2f6f3e", "#9fbf5f", "#e8d38a", "#b5835a", "#f5f0e6"]),
    "rainfall": ("continuous", "mm", ["#e0f2fe", "#7dd3fc", "#0284c7", "#4c1d95"]),
    "runoff": ("continuous", "mm", ["#e0f2fe", "#38bdf8", "#1d4ed8", "#1e1b4b"]),
    "cn": ("continuous", "CN", ["#14532d", "#a3e635", "#f59e0b", "#b91c1c"]),
    "accumulation": ("log", "upstream cells", ["#0c4a6e", "#0ea5e9", "#a5f3fc", "#ffffff"]),
    "accumulation_m3": ("log", "m3", ["#0c4a6e", "#0ea5e9", "#a5f3fc", "#ffffff"]),
    "landcover": ("categorical", None, WORLDCOVER_COLOURS),
    "hsg": ("categorical", None, HSG_COLOURS),
    "channels": ("categorical", None, {1: ("#22d3ee", "Mapped river / canal")}),
    "depth": ("depth_classes", "m", None),
}
DATASET_STYLES = {
    "dem_30m": "elevation", "landcover_30m": "landcover", "hsg_30m": "hsg",
    "rainfall_chirps_2015_event_30m": "rainfall", "terrain_flow_accumulation_30m": "accumulation",
    "channels_30m": "channels",
}
OUTPUT_STYLES = {"flood_depth": "depth", "runoff": "runoff", "cn": "cn", "runoff_accumulation": "accumulation_m3"}
CATEGORICAL_RESAMPLING = {"landcover", "hsg", "channels", "depth"}


def _hex(colour: str) -> tuple[int, int, int]:
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))


def _ramp(t: np.ndarray, stops: list[str]) -> np.ndarray:
    """Linear interpolation between colour stops for t in [0, 1]."""
    rgb = np.array([_hex(s) for s in stops], dtype="float64")
    pos = np.clip(t, 0, 1) * (len(stops) - 1)
    lo = np.floor(pos).astype(int).clip(0, len(stops) - 2)
    frac = (pos - lo)[..., None]
    return (rgb[lo] * (1 - frac) + rgb[lo + 1] * frac).astype("uint8")


def _warp_to_mercator(path: Path, max_size: int, resampling: Resampling):
    with rasterio.open(path) as src:
        transform, width, height = calculate_default_transform(src.crs, WEB_MERCATOR, src.width, src.height, *src.bounds)
        scale = max(width, height) / max_size if max(width, height) > max_size else 1.0
        width, height = int(round(width / scale)), int(round(height / scale))
        transform = transform * transform.scale(scale, scale)
        data = np.full((height, width), np.nan, dtype="float64")
        source = src.read(1).astype("float64")
        if src.nodata is not None:
            source[source == src.nodata] = np.nan
        reproject(source, data, src_transform=src.transform, src_crs=src.crs, src_nodata=np.nan,
                  dst_transform=transform, dst_crs=WEB_MERCATOR, dst_nodata=np.nan, resampling=resampling)
    left, top = transform.c, transform.f
    right, bottom = left + transform.a * width, top + transform.e * height
    west, south, east, north = transform_bounds(WEB_MERCATOR, "EPSG:4326", left, bottom, right, top)
    return data, [[south, west], [north, east]]


def _encode_png(rgba: np.ndarray) -> bytes:
    height, width, _ = rgba.shape
    # A plain PNG has no georeferencing; the overlay corners are returned separately.
    with warnings.catch_warnings(), MemoryFile() as mem:
        warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
        with mem.open(driver="PNG", width=width, height=height, count=4, dtype="uint8") as dst:
            dst.write(np.moveaxis(rgba, -1, 0))
        return mem.read()


@lru_cache(maxsize=48)
def render_preview(path_str: str, mtime: float, style: str, max_size: int, breaks: tuple = (), min_depth: float = 0.0):
    """Coloured RGBA PNG in Web Mercator, its lat/lon bounds, and a legend. Cached per file version."""
    kind, unit, palette = STYLES[style]
    resampling = Resampling.nearest if style in CATEGORICAL_RESAMPLING else Resampling.bilinear
    data, bounds = _warp_to_mercator(Path(path_str), max_size, resampling)
    valid = np.isfinite(data)
    rgba = np.zeros(data.shape + (4,), dtype="uint8")
    legend = {"style": style, "kind": kind, "unit": unit}

    if kind in ("continuous", "log"):
        values = np.log10(np.maximum(data, 1.0)) if kind == "log" else data
        if not valid.any():
            raise DataValidationError("raster has no valid cells to display")
        vmin, vmax = np.nanpercentile(values[valid], [1, 99])
        vmax = vmax if vmax > vmin else vmin + 1
        rgba[valid, :3] = _ramp((values[valid] - vmin) / (vmax - vmin), palette)
        rgba[valid, 3] = 210
        to_unit = (lambda v: float(10 ** v)) if kind == "log" else float
        legend.update(min=to_unit(vmin), max=to_unit(vmax), stops=palette, scale="log10" if kind == "log" else "linear",
                      note="colour range clipped to the 1st-99th percentile of valid cells")
    elif kind == "categorical":
        items = []
        for value, (colour, label) in palette.items():
            sel = valid & (data == value)
            if sel.any():
                rgba[sel, :3] = _hex(colour)
                rgba[sel, 3] = 220
                items.append({"value": value, "colour": colour, "label": label})
        legend["items"] = items
    elif kind == "depth_classes":
        edges = [min_depth, *breaks]
        items = []
        for i, lo in enumerate(edges):
            hi = edges[i + 1] if i + 1 < len(edges) else None
            sel = valid & (data >= lo) & (data < hi if hi is not None else True)
            colour = DEPTH_CLASS_COLOURS[min(i, len(DEPTH_CLASS_COLOURS) - 1)]
            rgba[sel, :3] = _hex(colour)
            rgba[sel, 3] = 230
            items.append({"colour": colour, "label": f"{lo:g}-{hi:g} m" if hi is not None else f">= {lo:g} m"})
        legend["items"] = items
        legend["note"] = f"cells shallower than {min_depth:g} m are transparent"
    return _encode_png(rgba), bounds, legend


def block_reduce(array: np.ndarray, factor: int, how: str = "mean") -> np.ndarray:
    """Downsample by whole blocks (NaN-aware); edge blocks are padded with NaN."""
    h, w = array.shape
    ph, pw = -h % factor, -w % factor
    padded = np.pad(array.astype("float64"), ((0, ph), (0, pw)), constant_values=np.nan)
    blocks = padded.reshape(padded.shape[0] // factor, factor, padded.shape[1] // factor, factor)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)   # all-NaN blocks (sea) are expected
        return np.nanmax(blocks, axis=(1, 3)) if how == "max" else np.nanmean(blocks, axis=(1, 3))


def grid_factor(shape: tuple[int, int], max_size: int) -> int:
    return max(1, int(np.ceil(max(shape) / max_size)))


def to_json_grid(array: np.ndarray, decimals: int = 2) -> list[list[float | None]]:
    rounded = np.round(array, decimals)
    return [[None if not np.isfinite(v) else float(v) for v in row] for row in rounded]


def chirps_window_stats(path: Path) -> dict:
    """Min / mean / max of CHIRPS cells whose centres fall inside the model area (sea cells are NoData)."""
    with rasterio.open(path) as src:
        data = src.read(1).astype("float64")
        if src.nodata is not None:
            data[data == src.nodata] = np.nan
        rows, cols = np.indices(data.shape)
        xs, ys = rasterio.transform.xy(src.transform, rows.ravel(), cols.ravel())
    xs, ys = np.asarray(xs).reshape(data.shape), np.asarray(ys).reshape(data.shape)
    w, s, e, n = MODEL_AREA_WGS84
    inside = (xs >= w) & (xs <= e) & (ys >= s) & (ys <= n) & np.isfinite(data)
    values = data[inside]
    return {"cells": int(values.size), "min_mm": float(values.min()) if values.size else None,
            "mean_mm": float(values.mean()) if values.size else None, "max_mm": float(values.max()) if values.size else None}
