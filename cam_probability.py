"""Checked experimental and producer-style neighborhood probability operators.

The dashboard uses ProducerWindowAccumulator; the local-event ANY diagnostic
remains a separate statistic for comparison and standalone verification.
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
    """Experimental local-event ANY peaks with a fixed member population.

    This differs from the producer-style dashboard accumulator below and from
    the member-wise time/duration event union in the standalone notebook.
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

# The separate local-exceedance operator above remains an experimental ANY
# diagnostic. Dashboard comparisons use the producer ordering below.
from math import isqrt
from scipy.ndimage import maximum_filter1d, convolve1d, maximum_filter

PRODUCER_METHOD = "emc-neighborhood-qpf-local-ffg-gaussian-v1"
PRODUCER_SOURCE = "https://github.com/NOAA-EMC/HREF/tree/081f905354e512b854f9505f49938991658475fc/sorc/refs_ensprod.fd"


class ProducerNeighborhood:
    """EMC A/A settings: 13-cell QPF radius, Gaussian sigma 5, half-width 8.

    Native 3-km spacing gives nominal 40 km (39 km on the grid), sigma 15 km,
    and a 24-km smoothing half-width. Missing QPF is never a zero rainfall.
    """
    def __init__(self, shape, spacing, radius=40000, sigma=5, half_width=8):
        if not np.isclose(spacing[0], spacing[1], rtol=0, atol=.01):
            raise ValueError("Producer neighborhood requires a square projected grid")
        self.cells = int(round(radius / spacing[0]))
        self.operator = ProjectedNeighborhood(shape, spacing, self.cells*spacing[0])
        self.sigma, self.half_width = float(sigma), int(half_width)
        offsets = np.arange(-self.half_width, self.half_width+1)
        self.kernel = (np.exp(-.5*(offsets/self.sigma)**2) if self.sigma else
                       np.array([1.]))
        self.kernel /= self.kernel.sum()

    def maximum(self, values):
        """Exact circular maximum, decomposed into linear row filters."""
        values = np.asarray(values)
        finite = np.isfinite(values)
        safe = values if finite.all() else np.where(finite, values, -np.inf)
        output = np.full_like(safe, -np.inf)
        groups = {}
        for dy in range(-self.cells, self.cells+1):
            half = isqrt(self.cells*self.cells-dy*dy)
            groups.setdefault(half, []).append(dy)
        horizontal = np.empty_like(safe)
        height = values.shape[-2]
        for half, shifts in groups.items():
            maximum_filter1d(safe, 2*half+1, axis=-1, output=horizontal,
                             mode="constant", cval=-np.inf)
            for dy in shifts:
                if abs(dy) >= height:
                    continue
                target = slice(max(0, -dy), min(height, height-dy))
                source = slice(max(0, dy), min(height, height+dy))
                np.maximum(output[:, target, :], horizontal[:, source, :],
                           out=output[:, target, :])
        known = np.empty_like(finite)
        for n in range(len(values)):
            known[n] = self.operator.interior & ~self.operator.dilate(~finite[n])
        return output, known

    def smooth(self, probability, domain=None):
        """Smooth each probability slot before the period maximum.

        EMC uses -10 for unavailable FFG before smoothing. Preserve that
        treatment, mask negative results, and retain missing FFG centers.
        Unknown member rainfall invalidates the smoothing footprint.
        """
        p = np.asarray(probability, np.float64)
        domain = np.ones(p.shape, bool) if domain is None else np.asarray(domain, bool)
        unknown = domain & ~np.isfinite(p)
        values = np.where(domain, np.nan_to_num(p, nan=0.), -10.)
        def convolution(a):
            return convolve1d(convolve1d(a, self.kernel, axis=0, mode="constant", cval=0.),
                              self.kernel, axis=1, mode="constant", cval=0.)
        result = convolution(values)/convolution(np.ones(p.shape))
        bad = maximum_filter(unknown, size=2*self.half_width+1, mode="constant", cval=0)
        result[bad | ~domain | (result < 0)] = np.nan
        return result.astype(np.float32)


class ProducerWindowAccumulator(WindowAccumulator):
    """Producer-style dashboard peaks; not the local-event ANY diagnostic."""
    def __init__(self, start_hour, end_hour, weights, ffg, spacing, radius=40000,
                 sigma=5, half_width=8):
        super().__init__(start_hour, end_hour, weights, ffg, spacing, radius)
        self.producer = ProducerNeighborhood(self.shape, spacing, radius, sigma, half_width)

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
            event, known = self.producer.operator.apply(qpf > threshold, good, domain)
            p = self.producer.smooth(fixed_probability(event, known, self.weights))
            np.fmax(self.qpf_peak[i], p, out=self.qpf_peak[i])
            self.qpf_complete &= np.isfinite(p)
        for d in expected_ffg_durations(fxx, self.start):
            total = np.add.reduce(list(self.history)[-d:], dtype=np.float64)
            maximum, known = self.producer.maximum(total)
            domain = np.isfinite(self.ffg[d])
            probability = fixed_probability(maximum > self.ffg[d], known & domain, self.weights)
            p = self.producer.smooth(probability, domain)
            np.fmax(self.ffg_peak[d], p, out=self.ffg_peak[d])
            self.ffg_complete[d] &= np.isfinite(p)
            self.slots.append((fxx, d))
        self.next_hour += 1
