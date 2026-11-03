"""Checked indexed member QPF and official numerical RFC FFG for Day 1.

Native member grids must match exactly. FFG is sampled onto that grid using
nearest neighbor; no new thresholds are inferred from colors or missing cells.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
import tempfile
import threading

# Projection libraries must be initialized before the ecCodes binary stack.
import cartopy.crs
import eccodes as ec
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UTC = timezone.utc
FFG_SOURCE = "https://ftp-wpc.ncep.noaa.gov/workoff/ffg/"
DECODE_VERSION = "day1-native-qpf-v0.1"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, suffix=".json", delete=False) as f:
        json.dump(payload, f, indent=2, allow_nan=False)
        temporary = Path(f.name)
    temporary.replace(path)


def atomic_npz(path, **arrays):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as f:
        temporary = Path(f.name)
    try:
        np.savez_compressed(temporary, **arrays)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def grib_framing(raw):
    offset = count = 0
    while offset < len(raw):
        if len(raw) - offset < 20 or raw[offset:offset+4] != b"GRIB" or raw[offset+7] != 2:
            raise ValueError("Not a complete GRIB2 stream")
        size = int.from_bytes(raw[offset+8:offset+16], "big")
        if size < 20 or offset + size > len(raw) or raw[offset+size-4:offset+size] != b"7777":
            raise ValueError("Truncated GRIB2 message")
        offset += size
        count += 1
    if not count:
        raise ValueError("Empty GRIB2 stream")
    return count


def qpf_entry(text, init, fxx):
    rows = []
    for line in text.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[1].isdigit():
            rows.append((int(parts[1]), line))
    if not rows or rows[0][0] != 0 or any(b[0] < a[0] for a, b in zip(rows, rows[1:])):
        raise ValueError("Invalid or incomplete GRIB index")
    offsets = sorted(set(r[0] for r in rows))
    ends = dict(zip(offsets, [v-1 for v in offsets[1:]] + [None]))
    matches = []
    for start, line in rows:
        p = [v.strip() for v in line.split(":")]
        if not {"APCP", "surface", f"d={init:%Y%m%d%H}"}.issubset(p):
            continue
        for token in p:
            m = re.fullmatch(r"(\d+)-(\d+) (?:hour|hr) acc fcst", token)
            if (m and tuple(map(int, m.groups())) == (fxx-1, fxx)) or (fxx == 1 and token in ("1 hour acc fcst", "1 hr acc fcst")):
                matches.append((start, ends[start]))
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous exact one-hour APCP field")
    if matches[0][1] is None:
        raise ValueError("Unbounded final-field range is not supported")
    return matches[0]


def member_urls(member, init, fxx):
    day, hour = init.strftime("%Y%m%d"), init.hour
    if member["family"] == "HRRR":
        relative = f"hrrr.{day}/conus/hrrr.t{hour:02d}z.wrfsfcf{fxx:02d}.grib2"
        return ["https://noaa-hrrr-bdp-pds.s3.amazonaws.com/" + relative,
                "https://nomads.ncep.noaa.gov/pub/data/nccf/com/hrrr/prod/" + relative]
    if member["family"] == "RRFS":
        relative = f"rrfs.{day}/{hour:02d}/rrfs.t{hour:02d}z.2dfld.3km.f{fxx:03d}.conus.grib2"
    elif member["family"] == "RRFS_ENS":
        number = member["perturbation"]
        relative = f"rrfsens.{day}/{hour:02d}/{number}/rrfs.t{hour:02d}z.{number}.2dfldnomads.3km.f{fxx:03d}.conus.grib2"
    else:
        raise ValueError("Unknown member family")
    return ["https://noaa-rrfs-ops-pds.s3.amazonaws.com/" + relative,
            "https://nomads.ncep.noaa.gov/pub/data/nccf/com/rrfs/prod/" + relative,
            "https://nomads.ncep.noaa.gov/pub/data/nccf/com/rrfs/para/" + relative]


def check_qpf_metadata(path, member, init, fxx):
    if grib_framing(Path(path).read_bytes()) != 1:
        raise ValueError("Expected exactly one selected precipitation message")
    with open(path, "rb") as f:
        gid = ec.codes_grib_new_from_file(f)
        try:
            expected = {"dataDate": int(init.strftime("%Y%m%d")), "dataTime": init.hour * 100,
                        "discipline": 0, "parameterCategory": 1, "parameterNumber": 8,
                        "stepUnits": 1, "startStep": fxx-1, "endStep": fxx,
                        "stepType": "accum", "typeOfLevel": "surface"}
            observed = {k: ec.codes_get(gid, k) for k in expected}
            if observed != expected or ec.codes_get(gid, "units") not in ("kg m**-2", "mm"):
                raise ValueError(f"Incorrect precipitation metadata: {observed}")
            if member["family"] == "RRFS_ENS":
                number = int(member["perturbation"][1:])
                if ec.codes_get(gid, "perturbationNumber") != number or ec.codes_get(gid, "typeOfGeneratingProcess") != 4:
                    raise ValueError("Wrong perturbed member")
            elif ec.codes_get(gid, "typeOfGeneratingProcess") != 2:
                raise ValueError("Expected a deterministic model field")
            process = ec.codes_get(gid, "generatingProcessIdentifier")
            if process != {"HRRR": 83, "RRFS": 134, "RRFS_ENS": 136}[member["family"]]:
                raise ValueError("Unexpected generating model identifier")
            observed["generatingProcessIdentifier"] = process
            return observed
        finally:
            ec.codes_release(gid)


@dataclass(frozen=True)
class Grid:
    shape: tuple
    crs_wkt: str
    affine: tuple

    @classmethod
    def from_source(cls, source):
        if source.crs is None or source.transform.b or source.transform.d:
            raise ValueError("Expected a georeferenced unrotated native grid")
        return cls(tuple(source.shape), source.crs.to_wkt(), tuple(source.transform)[:6])

    @property
    def crs(self):
        return rasterio.crs.CRS.from_wkt(self.crs_wkt)

    @property
    def transform(self):
        return rasterio.Affine(*self.affine)

    @property
    def spacing(self):
        return abs(self.affine[4]), abs(self.affine[0])

    @property
    def identifier(self):
        return digest(json.dumps(self.metadata(), sort_keys=True).encode())[:24]

    def metadata(self):
        return {"shape": self.shape, "crs_wkt": self.crs_wkt, "affine": self.affine,
                "rainfall_regridding": "none; exact matching native member grids required",
                "ffg_regridding": "nearest neighbor from official numerical mosaic"}

    def matches(self, source):
        return tuple(source.shape) == self.shape and source.crs == self.crs and np.allclose(
            tuple(source.transform)[:6], self.affine, rtol=0, atol=0.01)


class Sources:
    def __init__(self, cache_dir, workers=2):
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.workers = workers
        self._thread = threading.local()
        self._decode_lock = threading.Lock()
        self.grid = None
        self._indexes = {}

    def session(self):
        if not hasattr(self._thread, "session"):
            session = requests.Session()
            retries = Retry(total=2, backoff_factor=0.4, status_forcelist=(429, 500, 502, 503, 504))
            session.mount("https://", HTTPAdapter(max_retries=retries))
            session.headers["User-Agent"] = "WPC-SPC-Roster-Day1-Experimental/0.1"
            self._thread.session = session
        return self._thread.session

    def get(self, url, max_bytes=25_000_000, byte_range=None):
        headers = {} if byte_range is None else {"Range": f"bytes={byte_range[0]}-{byte_range[1]}"}
        with self.session().get(url, headers=headers, timeout=(8, 35), stream=True) as r:
            r.raise_for_status()
            if byte_range is not None:
                start, end = byte_range
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", r.headers.get("Content-Range", ""))
                if r.status_code != 206 or not match or tuple(map(int, match.groups()[:2])) != byte_range:
                    raise ValueError("Server did not honor the exact requested byte range")
                max_bytes = min(max_bytes, end-start+1)
            raw = bytearray()
            for chunk in r.iter_content(128 * 1024):
                raw.extend(chunk)
                if len(raw) > max_bytes:
                    raise ValueError("Response exceeds the bounded transfer size")
            if byte_range is not None and len(raw) != byte_range[1]-byte_range[0]+1:
                raise ValueError("Truncated ranged response")
            return bytes(raw), {"url": url, "bytes": len(raw), "sha256": digest(raw),
                                "retrieved_at": datetime.now(UTC).isoformat(),
                                "http_last_modified": r.headers.get("Last-Modified"),
                                "http_etag": r.headers.get("ETag")}

    def index(self, url):
        if url not in self._indexes:
            self._indexes[url] = self.get(url + ".idx", max_bytes=2_000_000)[0].decode()
        return self._indexes[url]

    def probe_index(self, url):
        """Short, non-retried discovery probe; data transfers retain retries."""
        if url not in self._indexes:
            with requests.get(url + ".idx", headers={"User-Agent": "WPC-SPC-OMD-CAM/1"},
                              timeout=(3, 8), stream=True) as response:
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_content(64*1024):
                    raw.extend(chunk)
                    if len(raw) > 2_000_000:
                        raise ValueError("Unbounded probe index")
                self._indexes[url] = bytes(raw).decode()
        return self._indexes[url]

    def preflight(self, members, reference_init, window):
        def probe(member):
            init = reference_init - timedelta(hours=member["lag_hours"])
            fxx = int((window.end-init).total_seconds() // 3600)
            cap = member.get("viewer_reference_end_hour", member["forecast_horizon_hours"]-member["lag_hours"])
            if fxx > member["forecast_horizon_hours"] or window.end > reference_init + timedelta(hours=cap):
                raise ValueError(f"{member['id']} cannot cover the Day 1 window")
            cached = self.hour_path(member, init, fxx)
            if cached.exists():
                try:
                    with np.load(cached, allow_pickle=False) as z:
                        m = json.loads(str(z["metadata"].item()))
                    expected = (DECODE_VERSION, member["family"], member.get("perturbation", "control"), init.isoformat(), fxx, "mm")
                    if tuple(m[k] for k in ("decode_version", "family", "perturbation", "init_utc", "native_forecast_hour", "units")) == expected:
                        return {"member": member["id"], "init_utc": init.isoformat(), "terminal_fxx": fxx,
                                "url": m["source"]["url"], "preflight": "validated hourly checkpoint; full values checked during processing"}
                except (OSError, ValueError, KeyError):
                    pass
            errors = []
            for url in member_urls(member, init, fxx):
                try:
                    qpf_entry(self.probe_index(url), init, fxx)
                    return {"member": member["id"], "init_utc": init.isoformat(), "terminal_fxx": fxx, "url": url}
                except (requests.RequestException, ValueError) as exc:
                    errors.append(str(exc))
            raise ValueError(f"{member['id']} terminal hour unavailable: {'; '.join(errors)}")
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return list(pool.map(probe, members))

    def hour_path(self, member, init, fxx):
        identity = member["family"] + "_" + member.get("perturbation", "control")
        return self.cache / DECODE_VERSION / identity / init.strftime("%Y%m%d%H") / f"f{fxx:03d}.npz"

    def fetch_hour(self, member, reference_init, valid_end):
        init = reference_init - timedelta(hours=member["lag_hours"])
        fxx = int((valid_end-init).total_seconds() // 3600)
        path = self.hour_path(member, init, fxx)
        if path.is_file():
            try:
                with np.load(path, allow_pickle=False) as z:
                    meta = json.loads(str(z["metadata"].item()))
                    values = z["values"]
                    grid_meta = meta["grid"]
                    grid = Grid(tuple(grid_meta["shape"]), grid_meta["crs_wkt"], tuple(grid_meta["affine"]))
                    expected = (DECODE_VERSION, member["family"], member.get("perturbation", "control"), init.isoformat(), fxx)
                    actual = tuple(meta[k] for k in ("decode_version", "family", "perturbation", "init_utc", "native_forecast_hour"))
                    finite = values[np.isfinite(values)]
                    model_id = meta.get("validated_grib", {}).get("generatingProcessIdentifier")
                    expected_model_id = {"HRRR": 83, "RRFS": 134, "RRFS_ENS": 136}[member["family"]]
                    if actual != expected or model_id != expected_model_id or meta["units"] != "mm" or values.shape != grid.shape or not finite.size or np.any(finite < 0) or np.any(finite > 1000):
                        raise ValueError("Cache identity mismatch")
                    with self._decode_lock:
                        if self.grid is None:
                            self.grid = grid
                        elif grid.identifier != self.grid.identifier:
                            raise ValueError("Cached native grid differs")
                    meta.update(from_cache=True, transferred_bytes=0)
                    return values, meta
            except (OSError, KeyError, ValueError):
                path.unlink(missing_ok=True)
        errors = []
        for url in member_urls(member, init, fxx):
            temporary = None
            try:
                byte_range = qpf_entry(self.index(url), init, fxx)
                raw, transfer = self.get(url, max_bytes=16_000_000, byte_range=byte_range)
                with tempfile.NamedTemporaryFile(dir=self.cache, suffix=".grib2", delete=False) as f:
                    f.write(raw)
                    temporary = Path(f.name)
                with self._decode_lock:
                    validated = check_qpf_metadata(temporary, member, init, fxx)
                    with rasterio.open(temporary) as source:
                        if source.driver != "GRIB" or source.count != 1 or source.tags(1).get("GRIB_UNIT") != "[kg/(m^2)]":
                            raise ValueError("Unexpected native rainfall raster")
                        if self.grid is None:
                            self.grid = Grid.from_source(source)
                        if not self.grid.matches(source):
                            raise ValueError("Member grid differs; a new common-grid mapping must be qualified")
                        values = source.read(1, masked=True).filled(np.nan).astype("float32")
                        finite = values[np.isfinite(values)]
                        if not finite.size or np.any(finite < 0) or np.any(finite > 1000):
                            raise ValueError("Invalid native hourly precipitation depths")
                meta = {"decode_version": DECODE_VERSION, "family": member["family"],
                        "perturbation": member.get("perturbation", "control"), "init_utc": init.isoformat(),
                        "native_forecast_hour": fxx, "valid_start_utc": (valid_end-timedelta(hours=1)).isoformat(),
                        "valid_end_utc": valid_end.isoformat(), "units": "mm", "grid": self.grid.metadata(),
                        "validated_grib": validated, "source": transfer, "from_cache": False,
                        "transferred_bytes": len(raw)}
                atomic_npz(path, values=values, metadata=np.array(json.dumps(meta)))
                return values, meta
            except (requests.RequestException, ValueError, OSError, ec.CodesInternalError) as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        raise RuntimeError(f"{member['id']} at {valid_end.isoformat()}: {'; '.join(errors)}")


def ffg_band_contract(tags):
    # Preserves the dashboard's validated official RFC FFG band contract.
    if tags.get("GRIB_ELEMENT") != "FFLDG" or tags.get("GRIB_UNIT") != "[kg/(m^2)]":
        raise ValueError("Wrong FFG quantity or units")
    if "CENTER=7(US-NCEP)" not in tags.get("GRIB_IDS", "") or not re.search(r"\bSUBCENTER=(?:5\(|255\b)", tags.get("GRIB_IDS", "")):
        raise ValueError("Unexpected FFG originating center")
    if tags.get("GRIB_PDS_PDTN") != "8":
        raise ValueError("Unvalidated FFG GRIB template")
    p = [int(x) for x in tags["GRIB_PDS_TEMPLATE_ASSEMBLED_VALUES"].split()]
    if len(p) != 29 or p[21] != 1 or p[25] != 1:
        raise ValueError("Unvalidated FFG time range")
    duration, ref, end = p[26], int(tags["GRIB_REF_TIME"]), int(tags["GRIB_VALID_TIME"])
    if int(tags["GRIB_FORECAST_SECONDS"]) != 0 or end-ref != duration*3600:
        raise ValueError("Inconsistent FFG duration metadata")
    return duration, datetime.fromtimestamp(ref, UTC), datetime.fromtimestamp(end, UTC)


def load_ffg(sources, decision_time, snapshot=None, expected_cycle=None):
    # Dashboard products require the official synoptic FFG cycle, not an
    # earlier snapshot selected by a publication-before-initialization rule.
    if expected_cycle is not None:
        expected_snapshot = expected_cycle.strftime("%Y%m%d%H")
        if snapshot is not None and snapshot != expected_snapshot:
            raise ValueError("FFG snapshot must match the requested model cycle exactly")
        snapshot = expected_snapshot
    listing = sources.get(FFG_SOURCE, max_bytes=3_000_000)[0].decode()
    names = sorted(set(re.findall(r'href="(5kmffg_\d{10}\.g2)"', listing)))
    eligible = [n for n in names if datetime.strptime(n[7:17], "%Y%m%d%H").replace(tzinfo=UTC) <= decision_time]
    if snapshot:
        name = f"5kmffg_{snapshot}.g2"
        if name not in eligible:
            raise ValueError("Requested FFG snapshot is unavailable or later than the issue time")
    elif eligible:
        name = eligible[-1]
    else:
        raise ValueError("No eligible official FFG snapshot")
    snapshot_time = datetime.strptime(name[7:17], "%Y%m%d%H").replace(tzinfo=UTC)
    if expected_cycle is not None:
        if snapshot_time != expected_cycle:
            raise ValueError("Official FFG snapshot does not match the model cycle")
    elif not timedelta(0) <= decision_time-snapshot_time < timedelta(hours=3):
        raise ValueError("Official FFG snapshot is stale at issue time")
    raw, transfer = sources.get(FFG_SOURCE + name)
    if transfer.get("http_last_modified"):
        modified = parsedate_to_datetime(transfer["http_last_modified"]).astimezone(UTC)
        if modified > decision_time+timedelta(minutes=5) or modified < snapshot_time-timedelta(minutes=5):
            raise ValueError("FFG HTTP modification time is inconsistent with the snapshot/issue time")
    grib_framing(raw)
    path = sources.cache / "ffg" / f"{name}.{transfer['sha256'][:16]}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    fields, references, period_ends = {}, set(), {}
    with rasterio.open(path) as src:
        for band in src.indexes:
            d, ref, end = ffg_band_contract(src.tags(band))
            if d not in (1, 3, 6):
                continue
            if d in fields:
                raise ValueError("Duplicate FFG duration")
            array = src.read(band, masked=True).filled(np.nan).astype("float32")
            finite = array[np.isfinite(array)]
            if not finite.size or np.any(finite <= 0) or np.any(finite > 1000):
                raise ValueError("Invalid FFG depths; no-data cannot be a zero threshold")
            fields[d] = array
            references.add(ref)
            period_ends[str(d)] = end.isoformat()
        if set(fields) != {1, 3, 6} or len(references) != 1:
            raise ValueError("Missing FFG durations or mixed reference cycles")
        reference = references.pop()
        if expected_cycle is not None:
            if reference != expected_cycle:
                raise ValueError("Official FFG encoded reference must equal the model cycle; older FFG is forbidden")
        elif reference > snapshot_time or not timedelta(0) <= decision_time-reference < timedelta(hours=9):
            raise ValueError("FFG reference time is inconsistent or stale")
        grid = Grid.from_source(src)
    expiry = (None if expected_cycle is not None else
              min(snapshot_time+timedelta(hours=3), reference+timedelta(hours=9)))
    meta = {"snapshot_time_utc": snapshot_time.isoformat(), "reference_time_utc": reference.isoformat(),
            "encoded_period_ends_utc": period_ends, "expires_at_utc": expiry.isoformat() if expiry else None,
            "decision_time_utc": decision_time.isoformat(), "source": transfer, "source_file": str(path),
            "grid": grid.metadata(), "units": "mm", "policy": "one frozen issue-time FFG mosaic for the complete run",
            "individual_rfc_issue_times_available": False,
            "qualification": "valid encoded durations and values; spatial gaps remain masked"}
    if expected_cycle is not None:
        meta.update(model_cycle_utc=expected_cycle.isoformat(),
                    ffg_cycle_policy="official_synoptic_model_cycle",
                    policy="official model-cycle RFC FFG; snapshot and encoded reference must both match the ensemble cycle; later publication is permitted")
    return fields, grid, meta


def ffg_on_member_grid(fields, source_grid, destination_grid):
    output = {}
    for d, values in fields.items():
        dest = np.full(destination_grid.shape, np.nan, dtype="float32")
        reproject(values, dest, src_transform=source_grid.transform, src_crs=source_grid.crs,
                  src_nodata=np.nan, dst_transform=destination_grid.transform,
                  dst_crs=destination_grid.crs, dst_nodata=np.nan,
                  resampling=Resampling.nearest, num_threads=1)
        output[d] = dest
    return output
