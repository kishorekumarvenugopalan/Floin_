import heapq
from collections import deque

import numpy as np
from scipy import ndimage

NEIGHBOURS = [(0, 1, 1), (1, 1, 2), (1, 0, 4), (1, -1, 8), (0, -1, 16), (-1, -1, 32), (-1, 0, 64), (-1, 1, 128)]
OUTLET_CODE = 0
NODATA_CODE = 255


def priority_flood(dem: np.ndarray, domain: np.ndarray):
    rows, cols = dem.shape
    width = cols + 2
    z = np.pad(np.where(domain, dem, np.nan), 1, constant_values=np.nan).ravel()
    inside = np.pad(domain, 1, constant_values=False)
    seeds_mask = inside & ~ndimage.binary_erosion(inside, structure=np.ones((3, 3), bool), border_value=0)
    offsets = [dr * width + dc for dr, dc, _ in NEIGHBOURS]

    closed = bytearray((~inside).ravel().astype(np.uint8).tobytes())
    filled = z.tolist()
    receiver = [-1] * z.size
    order = []
    heap = [(filled[i], i) for i in np.flatnonzero(seeds_mask.ravel()).tolist()]
    for _, i in heap:
        closed[i] = 1
    heapq.heapify(heap)
    pit = deque()
    push, pop = heapq.heappush, heapq.heappop

    while heap or pit:
        c = pit.popleft() if pit else pop(heap)[1]
        order.append(c)
        level = filled[c]
        for off in offsets:
            n = c + off
            if closed[n]:
                continue
            closed[n] = 1
            receiver[n] = c
            if filled[n] <= level:
                filled[n] = level        
                pit.append(n)
            else:
                push(heap, (filled[n], n))

    order_padded = np.asarray(order, dtype=np.int64)
    filled_arr = np.asarray(filled, dtype="float64").reshape(rows + 2, cols + 2)[1:-1, 1:-1]
    receiver_padded = np.asarray(receiver, dtype=np.int64)
    to_unpadded = _padded_to_flat(rows, cols)
    order_flat = to_unpadded[order_padded]
    flood_receiver = np.full(rows * cols, -1, dtype=np.int64)
    has = receiver_padded[order_padded] >= 0
    flood_receiver[order_flat[has]] = to_unpadded[receiver_padded[order_padded[has]]]
    return filled_arr, order_flat, flood_receiver


def _padded_to_flat(rows, cols):
    width = cols + 2
    idx = np.arange((rows + 2) * width)
    r, c = idx // width - 1, idx % width - 1
    out = r * cols + c
    out[(r < 0) | (r >= rows) | (c < 0) | (c >= cols)] = -1
    return out


def d8_receivers(filled: np.ndarray, domain: np.ndarray, flood_receiver: np.ndarray, cell_size: float):
    rows, cols = filled.shape
    f = np.pad(np.where(domain, filled, np.nan), 1, constant_values=np.nan)
    best_slope = np.zeros((rows, cols))
    best_k = np.full((rows, cols), -1, dtype=np.int8)
    for k, (dr, dc, _) in enumerate(NEIGHBOURS):
        neighbour = f[1 + dr:1 + dr + rows, 1 + dc:1 + dc + cols]
        distance = cell_size * (np.sqrt(2.0) if dr and dc else 1.0)
        with np.errstate(invalid="ignore"):
            slope = (filled - neighbour) / distance
            better = domain & np.isfinite(slope) & (slope > best_slope)
        best_slope[better] = slope[better]
        best_k[better] = k

    flat_index = np.arange(rows * cols).reshape(rows, cols)
    receiver = np.full(rows * cols, -1, dtype=np.int64)
    codes = np.full((rows, cols), NODATA_CODE, dtype=np.uint8)
    for k, (dr, dc, code) in enumerate(NEIGHBOURS):
        sel = best_k == k
        receiver[flat_index[sel]] = flat_index[sel] + dr * cols + dc
        codes[sel] = code

    no_descent = domain & (best_k < 0)
    receiver[flat_index[no_descent]] = flood_receiver[flat_index[no_descent]]
    fallback = receiver.reshape(rows, cols)
    for dr, dc, code in NEIGHBOURS:
        sel = no_descent & (fallback == flat_index + dr * cols + dc)
        codes[sel] = code
    codes[no_descent & (fallback < 0)] = OUTLET_CODE
    receiver[~domain.ravel()] = -1
    return receiver, codes
