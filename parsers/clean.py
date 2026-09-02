from __future__ import annotations

import numpy as np

SENTINEL = 99_990.0
GAP_MS = 120_000.0


def as_float(arr) -> np.ndarray:
    return np.asarray(arr, dtype=np.float64)


def clean_xy(
    x: np.ndarray,
    y: np.ndarray,
    y_min: float | None = None,
    y_max: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    x = as_float(x)
    y = as_float(y)
    if x.size == 0:
        return x, y
    n = min(x.size, y.size)
    x = x[:n]
    y = y[:n]
    mask = np.isfinite(x) & np.isfinite(y) & (np.abs(y) < SENTINEL)
    if y_min is not None:
        mask &= y >= y_min
    if y_max is not None:
        mask &= y <= y_max
    return x[mask], y[mask]


def insert_gap_nans(x: np.ndarray, y: np.ndarray, gap_ms: float = GAP_MS) -> tuple[np.ndarray, np.ndarray]:
    if x.size < 2:
        return x, y
    order = np.argsort(x)
    x = x[order]
    y = y[order]
    dx = np.diff(x)
    breaks = np.flatnonzero(dx > gap_ms)
    if breaks.size == 0:
        return x, y
    pieces_x = []
    pieces_y = []
    start = 0
    for b in breaks:
        pieces_x.append(x[start : b + 1])
        pieces_y.append(y[start : b + 1])
        pieces_x.append(np.array([x[b] + 1.0], dtype=np.float64))
        pieces_y.append(np.array([np.nan], dtype=np.float64))
        start = b + 1
    pieces_x.append(x[start:])
    pieces_y.append(y[start:])
    return np.concatenate(pieces_x), np.concatenate(pieces_y)
