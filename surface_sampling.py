"""Compact numeric copies of the displayed analysis; never inferred from RGB."""
import gzip
import io
import json
import struct
import numpy as np
from surface_analysis import BOUNDS, PRODUCTS

MAX_BYTES = 4 + 2048 + 3600 * 2024 * 2


def header(key, valid_time, width, height):
    return dict(schema="surface-sample-v1", key=key, valid_time=valid_time,
                unit=PRODUCTS[key]["unit"], width=width, height=height,
                crs="EPSG:3857", bounds=BOUNDS, scale=0.1, nodata=-32768,
                dtype="int16-le", order="north-to-south")


def pack_grid(key, values, valid_time):
    a = np.asarray(values, dtype="float64")
    if a.ndim != 2 or a.shape != (2024, 3600):
        raise ValueError("Wrong sample grid shape")
    valid = np.isfinite(a)
    q = np.rint(a[valid] * 10)
    if np.any((q <= -32768) | (q > 32767)):
        raise ValueError("Sample values exceed numeric encoding range")
    packed = np.full(a.shape, -32768, dtype="<i2")
    packed[valid] = q.astype("<i2")
    meta = json.dumps(header(key, valid_time, 3600, 2024), separators=(",", ":")).encode()
    return gzip.compress(struct.pack("<I", len(meta)) + meta + packed.tobytes(), mtime=0)


def unpack_grid(raw, key, valid_time):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or len(data) < 4:
        raise ValueError("Oversized or truncated sample grid")
    size = struct.unpack("<I", data[:4])[0]
    if not 0 < size <= 2048 or len(data) != 4 + size + 3600 * 2024 * 2:
        raise ValueError("Wrong sample grid length")
    if json.loads(data[4:4+size]) != header(key, valid_time, 3600, 2024):
        raise ValueError("Sample grid identity mismatch")
    return np.frombuffer(data, dtype="<i2", offset=4+size).reshape(2024, 3600)
