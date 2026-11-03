"""Shared 40-km member-neighborhood probability operator.

Inherited from the verified SPC Day 1 v0.2 engine; no second dilation.
"""
import numpy as np
from collections import deque
from scipy.ndimage import distance_transform_edt

QPF_THRESHOLDS_MM = (12.7, 25.4, 50.8, 76.2)


def expected_ffg_durations(fxx, window_start):
    """Match the native OMD product cadence; require full interval containment."""
    return tuple(d for d in (1, 3, 6)
                 if fxx-d >= window_start and (d == 1 or fxx % 3 == 0))


class WindowAccumulator:
    """Peak rolling probability; each comparison uses a fixed member population.

    This dashboard deliberately uses max(window member frequency), rather than
    the member-wise event union offered separately in the standalone notebook.
    """
    def __init__(self, start_hour, end_hour, weights, ffg, spacing, radius=40000):
        self.start, self.end = int(start_hour), int(end_hour)
        self.weights = np.asarray(weights, float)
        if self.start < 0 or self.end <= self.start or not len(self.weights):
            raise ValueError("Invalid window or population")
        if not np.isfinite(self.weights).all() or np.any(self.weights <= 0):
            raise ValueError("Use positive fixed member weights")
        self.ffg = {d: np.asarray(ffg[d], dtype=np.float64) for d in (1, 3, 6)}
        self.shape = self.ffg[1].shape
        if any(a.shape != self.shape or np.isinf(a).any() or np.any(a[np.isfinite(a)] <= 0)
               for a in self.ffg.values()):
            raise ValueError("FFG durations must share a grid with positive finite depths or NaN")
        self.operator = ProjectedNeighborhood(self.shape, spacing, radius)
        self.qpf_peak = np.full((4, *self.shape), np.nan, np.float32)
        self.ffg_peak = {d: np.full(self.shape, np.nan, np.float32) for d in (1, 3, 6)}
        self.qpf_complete = np.ones(self.shape, bool)
        self.ffg_complete = {d: np.ones(self.shape, bool) for d in (1, 3, 6)}
        self.history = deque(maxlen=6)
        self.next_hour = self.start+1
        self.slots = []

    def add(self, fxx, qpf):
        if fxx != self.next_hour or fxx > self.end:
            raise ValueError("Missing, duplicate, out-of-order or out-of-window hour")
        qpf = np.asarray(qpf, np.float32)
        if qpf.shape != (len(self.weights), *self.shape) or np.isinf(qpf).any() or np.any(qpf[np.isfinite(qpf)] < 0):
            raise ValueError("Hourly member rainfall must match the fixed population/grid")
        self.history.append(qpf.copy())
        good = np.isfinite(qpf)
        domain = np.ones(self.shape, bool)
        for i, threshold in enumerate(QPF_THRESHOLDS_MM):
            event, known = self.operator.apply(qpf > threshold, good, domain)
            probability = fixed_probability(event, known, self.weights)
            np.fmax(self.qpf_peak[i], probability, out=self.qpf_peak[i])
            self.qpf_complete &= known.all(axis=0)
        for d in expected_ffg_durations(fxx, self.start):
            total = np.add.reduce(list(self.history)[-d:], dtype=np.float64)
            event, known = self.operator.apply(total > self.ffg[d], np.isfinite(total), np.isfinite(self.ffg[d]))
            probability = fixed_probability(event, known, self.weights)
            np.fmax(self.ffg_peak[d], probability, out=self.ffg_peak[d])
            self.ffg_complete[d] &= known.all(axis=0)
            self.slots.append((fxx, d))
        self.next_hour += 1

    def finish(self):
        if self.next_hour != self.end+1:
            raise ValueError("Cannot publish a partial window")
        expected = [(f, d) for f in range(self.start+1, self.end+1)
                    for d in expected_ffg_durations(f, self.start)]
        if self.slots != expected or not {1, 3, 6}.issubset({d for _, d in self.slots}):
            raise ValueError("Incomplete FFG duration/cadence coverage")
        qpf = self.qpf_peak.copy()
        qpf[:, ~self.qpf_complete] = np.nan
        ffg = np.fmax.reduce(list(self.ffg_peak.values()))
        complete = np.logical_and.reduce(list(self.ffg_complete.values()))
        ffg[~complete] = np.nan
        return {"QPF": qpf, "FFG_MAX": ffg}


def blend_maxima(spc, omd):
    """Equal suite weights; both finite values are required at each grid cell."""
    a, b = np.asarray(spc, np.float32), np.asarray(omd, np.float32)
    if a.shape != b.shape:
        raise ValueError("Cannot blend different grids")
    return np.where(np.isfinite(a) & np.isfinite(b), .5*a+.5*b, np.nan).astype(np.float32)

def fixed_probability(events, valid, weights):
    """All configured members are required; a missing member never changes N."""
    events, valid = np.asarray(events, bool), np.asarray(valid, bool)
    weights = np.asarray(weights, dtype=float)
    if events.ndim != 3 or events.shape != valid.shape or events.shape[0] != len(weights):
        raise ValueError("Use matching [member,y,x] events/validity and one weight per member")
    if not len(weights) or not np.isfinite(weights).all() or np.any(weights <= 0):
        raise ValueError("Use positive finite weights")
    result = (100 * np.einsum("n,nij->ij", weights, events, optimize=True) / weights.sum()).astype("float32")
    result[~valid.all(axis=0)] = np.nan
    return result

class ProjectedNeighborhood:
    """Member-level ANY within a nominal radius in the declared projected CRS.

    FFG comparisons are performed locally BEFORE this operator. Only cells with
    official FFG participate in FFG events, and output centers without FFG remain
    missing. Missing member QPF inside that eligible domain invalidates nearby
    results. No-data FFG is never interpreted as a zero rainfall threshold.
    """
    def __init__(self, shape, spacing_metres=(5000, 5000), radius_metres=40000):
        self.shape = tuple(shape)
        self.spacing = tuple(float(v) for v in spacing_metres)
        self.radius = float(radius_metres)
        if len(shape) != 2 or len(self.spacing) != 2 or any(v <= 0 for v in self.spacing) or self.radius < 0:
            raise ValueError("Invalid grid spacing, shape or neighborhood radius")
        # A neighborhood crossing the analysis-grid border is incomplete.
        yy, xx = np.indices(shape)
        dy, dx = self.spacing
        self.interior = np.minimum.reduce(((yy + 0.5) * dy, (shape[0] - yy - 0.5) * dy,
                                           (xx + 0.5) * dx, (shape[1] - xx - 0.5) * dx)) >= self.radius

    def dilate(self, events):
        if self.radius == 0 or not events.any():
            return events.copy()
        return distance_transform_edt(~events, sampling=self.spacing) <= self.radius

    def apply(self, events, valid, domain):
        events, valid, domain = np.asarray(events, bool), np.asarray(valid, bool), np.asarray(domain, bool)
        if events.shape != valid.shape or events.shape[1:] != self.shape or domain.shape != self.shape:
            raise ValueError("Neighborhood grid mismatch")
        out, known = np.zeros_like(events), np.zeros_like(valid)
        for n in range(len(events)):
            out[n] = self.dilate(events[n] & valid[n] & domain) & domain
            bad = domain & ~valid[n]
            known[n] = domain & self.interior & ~self.dilate(bad)
        return out, known
