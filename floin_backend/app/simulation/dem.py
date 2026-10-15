import numpy as np
from scipy import ndimage

WORLDCOVER_WATER = 80
EIGHT_CONNECTED = np.ones((3, 3), dtype=bool)


def sea_mask(landcover: np.ndarray, open_sea_edge: str = "east") -> np.ndarray:
    water = (landcover == WORLDCOVER_WATER) | (landcover == 0)
    labels, _ = ndimage.label(water, structure=EIGHT_CONNECTED)
    edge = {"east": labels[:, -1], "west": labels[:, 0], "north": labels[0, :], "south": labels[-1, :]}[open_sea_edge]
    sea_labels = np.unique(edge[edge > 0])
    return np.isin(labels, sea_labels)


def model_domain(dem: np.ndarray, landcover: np.ndarray) -> np.ndarray:
    return np.isfinite(dem) & ~sea_mask(landcover)


def repair_artifacts(dem: np.ndarray, domain: np.ndarray, floor_m: float = -2.0) -> tuple[np.ndarray, int]:
    from rasterio.fill import fillnodata

    bad = domain & (dem < floor_m)
    if not bad.any():
        return dem.copy(), 0
    valid = np.isfinite(dem) & ~bad
    filled = fillnodata(np.where(valid, dem, 0).astype("float32"), mask=valid.astype("uint8"),
                        max_search_distance=100, smoothing_iterations=0)
    out = dem.astype("float64", copy=True)
    out[bad] = filled[bad]
    return out, int(bad.sum())


def burn_channels(dem: np.ndarray, channels: np.ndarray, depth_m: float) -> np.ndarray:
    if depth_m < 0:
        raise ValueError("burn depth must be >= 0")
    out = dem.astype("float64", copy=True)
    out[channels & np.isfinite(out)] -= depth_m
    return out
