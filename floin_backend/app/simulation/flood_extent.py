import numpy as np
from rasterio import features
from shapely.geometry import shape

DEFAULT_CLASS_BREAKS = (0.3, 1.0, 2.0)
DEFAULT_CLASS_NAMES = ("low", "moderate", "high", "severe")
DEFAULT_MIN_DEPTH_M = 0.10


def classify(depth: np.ndarray, flood_mask: np.ndarray, min_depth_m: float, breaks) -> np.ndarray:
    if min_depth_m <= 0:
        raise ValueError("min_depth_m must be positive")
    if list(breaks) != sorted(breaks) or min(breaks) <= min_depth_m:
        raise ValueError("class breaks must be increasing and above min_depth_m")
    flooded = flood_mask & (depth >= min_depth_m)
    classes = np.zeros(depth.shape, dtype=np.uint8)
    classes[flooded] = (np.digitize(depth[flooded], breaks) + 1).astype(np.uint8)
    return classes


def polygonize(classes: np.ndarray, transform) -> list[tuple[object, int]]:
    return [
        (shape(geom), int(value))
        for geom, value in features.shapes(classes, mask=classes > 0, transform=transform, connectivity=4)
    ]


def summarize(depth: np.ndarray, classes: np.ndarray, cell_area_m2: float, names) -> dict:
    flooded = classes > 0
    values = depth[flooded]
    by_class = {}
    for i, name in enumerate(names, start=1):
        cells = int((classes == i).sum())
        by_class[name] = {"cells": cells, "area_km2": cells * cell_area_m2 / 1e6}
    return {
        "flooded_cells": int(flooded.sum()),
        "flooded_area_km2": float(flooded.sum() * cell_area_m2 / 1e6),
        "max_depth_m": float(values.max()) if values.size else 0.0,
        "mean_depth_m": float(values.mean()) if values.size else 0.0,
        "p95_depth_m": float(np.percentile(values, 95)) if values.size else 0.0,
        "flood_volume_m3": float(values.sum() * cell_area_m2),
        "by_class": by_class,
    }
