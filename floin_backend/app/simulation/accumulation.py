import numpy as np


def accumulate(order: np.ndarray, receiver: np.ndarray, weights: np.ndarray) -> tuple[np.ndarray, float]:
    total = np.asarray(weights, dtype="float64").ravel().copy()
    flow = total.tolist()
    recv = receiver.tolist()
    outflow = 0.0
    for c in reversed(order.tolist()):
        r = recv[c]
        if r < 0:
            outflow += flow[c]
        else:
            flow[r] += flow[c]
    return np.asarray(flow).reshape(np.shape(weights)), outflow
