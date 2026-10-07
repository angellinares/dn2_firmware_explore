"""Tune the cost table from the instrument: non-negative least squares with a pull
toward the manuals' numbers.

A case is one state measured on the instrument and run in the emulator: its
event counts and its measured cycles. The instrument measures a whole frame and
the emulator runs only part of it, so cases come in pairs that share the rest
(one build silent and the same build with a chord held; two builds on the same
patch), and the fit uses their differences: whatever neither run models cancels.

    minimise  sum_i ((A x - b)_i / sigma_i)^2  +  lam * sum_k ((x_k - x0_k) / s_k)^2,  x >= 0

over the FREE keys only, with A the count differences, b the measured cycle
differences less what the fixed keys predict, sigma_i each pair's measured
spread, x0 the current costs and s_k their scale (the default, at least 1).
With fewer pairs than free keys the pull decides the rest, and `report` says
which keys the data moved.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .costs import Cost


@dataclass(frozen=True)
class Pair:
    name: str
    counts: dict[str, float]        # counts(a) - counts(b), per frame
    cycles: float                   # measured(a) - measured(b), per frame
    sigma: float = 1000.0           # the measurement's spread, cycles per frame


def nnls(a: np.ndarray, b: np.ndarray, iters: int = 500) -> np.ndarray:
    """min ||a x - b||, x >= 0 (Lawson and Hanson's active-set method)."""
    m, n = a.shape
    x = np.zeros(n)
    passive = np.zeros(n, dtype=bool)
    w = a.T @ (b - a @ x)
    for _ in range(iters):
        if passive.all() or (w[~passive] <= 1e-10).all():
            break
        j = np.argmax(np.where(passive, -np.inf, w))
        passive[j] = True
        while True:
            z = np.zeros(n)
            z[passive] = np.linalg.lstsq(a[:, passive], b, rcond=None)[0]
            if (z[passive] > 0).all():
                x = z
                break
            neg = passive & (z <= 0)
            alpha = np.min(x[neg] / (x[neg] - z[neg]))
            x = x + alpha * (z - x)
            passive &= x > 1e-12
        w = a.T @ (b - a @ x)
    return x


def fit(pairs: list[Pair], table: dict[str, Cost], free: list[str], lam: float = 1.0):
    """-> (new costs for FREE, residual per pair before, after)."""
    fixed = [k for k in table if k not in free]
    rows, rhs = [], []
    for p in pairs:
        known = sum(p.counts.get(k, 0) * table[k].value for k in fixed)
        rows.append([p.counts.get(k, 0) / p.sigma for k in free])
        rhs.append((p.cycles - known) / p.sigma)
    x0 = np.array([table[k].value for k in free])
    scale = np.maximum(np.abs(x0), 1.0)
    prior = np.sqrt(lam) * np.diag(1 / scale)
    a = np.vstack([np.array(rows, dtype=float).reshape(len(pairs), len(free)), prior])
    b = np.concatenate([np.array(rhs, dtype=float), prior @ x0])
    x = nnls(a, b)

    def residuals(values):
        out = []
        for p in pairs:
            pred = sum(p.counts.get(k, 0) * (values.get(k, table[k].value)) for k in p.counts if k in table)
            out.append(p.cycles - pred)
        return out

    new = dict(zip(free, x))
    return new, residuals({}), residuals(new)
