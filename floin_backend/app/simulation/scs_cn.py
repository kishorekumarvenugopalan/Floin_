import numpy as np

def retention_mm(cn):
    cn = np.asarray(cn, dtype="float64")
    s = np.full(cn.shape, np.nan)
    valid = np.isfinite(cn) & (cn > 0) & (cn <= 100)
    s[valid] = 25400.0 / cn[valid] - 254.0
    return s

def runoff_depth_mm(rainfall_mm, cn, ia_ratio: float = 0.2):
    if not 0 < ia_ratio <= 1:
        raise ValueError("ia_ratio must be in (0, 1]")
    cn = np.asarray(cn, dtype="float64")
    p = np.broadcast_to(np.asarray(rainfall_mm, dtype="float64"), cn.shape)
    if np.any(p[np.isfinite(p)] < 0):
        raise ValueError("rainfall cannot be negative")
    s = retention_mm(cn)
    ia = ia_ratio * s
    q = np.full(cn.shape, np.nan)
    valid = np.isfinite(s) & np.isfinite(p)
    wet = valid & (p > ia)
    q[valid] = 0.0
    excess = p[wet] - ia[wet]
    q[wet] = excess ** 2 / (excess + s[wet])
    return q


def runoff_volume_m3(runoff_mm, cell_area_m2: float):
    if cell_area_m2 <= 0:
        raise ValueError("cell area must be positive")
    return np.asarray(runoff_mm, dtype="float64") / 1000.0 * cell_area_m2
