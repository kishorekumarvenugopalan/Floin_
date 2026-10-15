import numpy as np
from scipy import ndimage

EIGHT_CONNECTED = np.ones((3, 3), dtype=bool)


def identify_depressions(ground: np.ndarray, filled: np.ndarray, domain: np.ndarray,
                         cell_area_m2: float, tolerance_m: float = 1e-3):
    depth = np.where(domain, filled - ground, 0.0)
    inside = domain & (depth > tolerance_m)
    components, _ = ndimage.label(inside, structure=EIGHT_CONNECTED)
    level_key = np.round(filled[inside] * 1000.0).astype(np.int64)
    pairs = np.stack([components[inside].astype(np.int64), level_key], axis=1)
    _, ids = np.unique(pairs, axis=0, return_inverse=True)
    labels = np.full(ground.shape, -1, dtype=np.int64)
    labels[inside] = ids.ravel()
    n = int(ids.max()) + 1 if ids.size else 0
    capacity = np.bincount(labels[inside], weights=depth[inside], minlength=n) * cell_area_m2
    spill = np.zeros(n)
    spill[labels[inside]] = filled[inside]
    return labels, capacity, spill


def fill_and_spill(order: np.ndarray, receiver: np.ndarray, inflow_m3: np.ndarray,
                   labels: np.ndarray, capacity: np.ndarray):
    flat_labels = labels.ravel()
    n_dep = capacity.size
    # The outlet of a depression is its first cell in flood order (reached from outside).
    in_order = flat_labels[order]
    member = in_order >= 0
    first_dep, first_pos = np.unique(in_order[member], return_index=True)
    exit_cell = np.full(n_dep, -1, dtype=np.int64)
    exit_cell[first_dep] = order[member][first_pos]

    flow = np.asarray(inflow_m3, dtype="float64").ravel().tolist()
    recv = receiver.tolist()
    dep = flat_labels.tolist()
    exits = exit_cell.tolist()
    cap = capacity.tolist()
    stored = [0.0] * n_dep
    outflow = 0.0

    for c in reversed(order.tolist()):
        v = flow[c]
        d = dep[c]
        r = recv[c]
        if d >= 0:
            if c == exits[d]:
                s = v if v < cap[d] else cap[d]
                stored[d] = s
                v -= s
                if r >= 0 and dep[r] == d:
                    raise AssertionError("depression outlet drains back into its own depression")
            elif r < 0 or dep[r] != d:
                r = exits[d]          
        if r < 0:
            outflow += v
        else:
            flow[r] += v
    through = np.asarray(flow).reshape(labels.shape)
    return np.asarray(stored), outflow, through


def water_surface(labels: np.ndarray, ground: np.ndarray, stored_m3: np.ndarray,
                  spill: np.ndarray, cell_area_m2: float) -> np.ndarray:
    level = np.full(ground.shape, np.nan)
    wet_dep = stored_m3 > 0
    cells = np.flatnonzero((labels >= 0).ravel() & wet_dep[np.maximum(labels.ravel(), 0)])
    if cells.size == 0:
        return level
    d = labels.ravel()[cells]
    z = ground.ravel()[cells]
    idx = np.lexsort((z, d))
    d_s, z_s = d[idx], z[idx]
    starts = np.flatnonzero(np.r_[True, d_s[1:] != d_s[:-1]])
    group_start = np.repeat(starts, np.diff(np.r_[starts, d_s.size]))
    k = np.arange(d_s.size) - group_start + 1                    
    csum = np.cumsum(z_s)
    s_k = csum - np.r_[0.0, csum][group_start]                  
    volume_at_k = cell_area_m2 * (k * z_s - s_k)                 
    target = stored_m3[d_s]
    fits = volume_at_k <= target * (1 + 1e-12) + 1e-9
    k_max = np.bincount(d_s[fits], minlength=stored_m3.size)    
    deps = np.unique(d_s)
    starts_by_dep = np.zeros(stored_m3.size, dtype=np.int64)
    starts_by_dep[d_s[starts]] = starts
    last = starts_by_dep[deps] + k_max[deps] - 1
    s_last = s_k[last]
    h = (stored_m3[deps] / cell_area_m2 + s_last) / k_max[deps]
    h = np.minimum(h, spill[deps])
    surface = np.full(stored_m3.size, np.nan)
    surface[deps] = h
    flat_level = level.ravel()
    flat_level[cells] = surface[d]
    return flat_level.reshape(ground.shape)

def flood_depth(labels, ground, stored_m3, spill, cell_area_m2) -> tuple[np.ndarray, np.ndarray]:
    surface = water_surface(labels, ground, stored_m3, spill, cell_area_m2)
    depth = np.where(np.isfinite(surface), np.maximum(surface - ground, 0.0), 0.0)
    return surface, depth
