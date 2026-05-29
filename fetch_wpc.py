import geopandas as gpd
import pandas as pd
import requests
import zipfile
import io
import os
import re
import time
import tempfile
from datetime import datetime, timezone, timedelta

ERO_REST_URL = "https://mapservices.weather.noaa.gov/vector/rest/services/hazards/wpc_precip_hazards/MapServer/0/query"
MPD_FTP_URL = "https://ftp-wpc.ncep.noaa.gov/shapefiles/qpf/mpd/"
OUTPUT_FILENAME = "wpc_data.geojson"

NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
    "User-Agent": "WPC-Hydro-Dashboard-Bot/1.0"
}

# Only inspect recently modified MPD shapefiles.
# This prevents old high-number MPDs from being accidentally considered.
MPD_RECENT_FILE_HOURS = 48

# MPDs should not have expiration times wildly far into the future.
# This catches bad parsing, stale records, or malformed DBF fields.
MAX_EXPIRATION_AHEAD_HOURS = 18

# Number of recent candidates to inspect after Last-Modified sorting.
MAX_CANDIDATES = 30


def utc_now():
    return datetime.now(timezone.utc)


def extract_mpd_num(filename):
    match = re.search(r"MPD_(\d{3,4})_final", str(filename), re.IGNORECASE)
    if match:
        return int(match.group(1))

    match = re.search(r"\d{3,4}", str(filename))
    return int(match.group()) if match else None


def format_dt(dt):
    if dt is None or pd.isna(dt):
        return "Unknown"

    if isinstance(dt, pd.Timestamp):
        dt = dt.to_pydatetime()

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc).strftime("%HZ %b %d %Y")


def iso_dt(dt):
    if dt is None or pd.isna(dt):
        return ""

    if isinstance(dt, pd.Timestamp):
        dt = dt.to_pydatetime()

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_to_wgs84(gdf):
    if gdf is None or gdf.empty:
        return gdf

    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    if gdf.empty:
        return gdf

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    else:
        gdf = gdf.to_crs("EPSG:4326")

    return gdf


def parse_time_value(value):
    """
    Robust WPC/DBF timestamp parser.

    Handles:
    - YYMMDDHHMM
    - YYYYMMDDHHMM
    - YYYYMMDDHHMMSS
    - ISO-like strings
    - pandas/datetime objects
    - epoch seconds/milliseconds
    """

    if value is None or pd.isna(value):
        return pd.NaT

    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return pd.NaT
        if value.tzinfo is None:
            return value.to_pydatetime().replace(tzinfo=timezone.utc)
        return value.to_pydatetime().astimezone(timezone.utc)

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    raw = str(value).strip()

    if raw.lower() in ["", "nan", "nat", "none", "null"]:
        return pd.NaT

    # Remove decimal artifacts from DBF numeric fields.
    raw = raw.split(".")[0]

    digits = re.sub(r"\D", "", raw)

    # Explicit WPC / DBF formats
    for fmt, nchar in [
        ("%y%m%d%H%M", 10),
        ("%Y%m%d%H%M", 12),
        ("%Y%m%d%H%M%S", 14),
    ]:
        if len(digits) == nchar:
            try:
                return datetime.strptime(digits, fmt).replace(tzinfo=timezone.utc)
            except Exception:
                pass

    # Epoch fallback
    try:
        val = float(raw)
        if val > 1e12:
            return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
        if val > 1e9:
            return datetime.fromtimestamp(val, tz=timezone.utc)
    except Exception:
        pass

    # General fallback
    try:
        parsed = pd.to_datetime(raw, utc=True, errors="coerce")
        if pd.notna(parsed):
            return parsed.to_pydatetime().astimezone(timezone.utc)
    except Exception:
        pass

    return pd.NaT


def find_column(gdf, exact_names=None, contains=None):
    exact_names = exact_names or []
    contains = contains or []

    col_map = {c.strip().upper(): c for c in gdf.columns}

    for name in exact_names:
        if name.upper() in col_map:
            return col_map[name.upper()]

    for upper_col, original_col in col_map.items():
        for piece in contains:
            if piece.upper() in upper_col:
                return original_col

    return None


def parse_mpd_directory_entries():
    """
    Parse the Apache-style WPC MPD shapefile directory.

    Returns:
    [
      {
        "filename": "MPD_0273_final.zip",
        "url": "...",
        "mpd_num": 273,
        "modified_dt": datetime(...)
      },
      ...
    ]
    """

    print("Reading WPC MPD shapefile directory...")

    response = requests.get(
        f"{MPD_FTP_URL}?t={int(time.time())}",
        headers=NO_CACHE_HEADERS,
        timeout=30
    )
    response.raise_for_status()

    entries = []

    for line in response.text.splitlines():
        href_match = re.search(
            r'href="(?P<filename>MPD_(?P<num>\d{3,4})_final\.zip)"',
            line,
            re.IGNORECASE
        )

        if not href_match:
            continue

        filename = href_match.group("filename")
        mpd_num = int(href_match.group("num"))

        # Apache listing format commonly looks like:
        # MPD_0273_final.zip 29-May-2026 18:17 1.6K
        modified_dt = None
        mod_match = re.search(
            r"</a>\s*(?P<date>\d{2}-[A-Za-z]{3}-\d{4})\s+(?P<time>\d{2}:\d{2})",
            line
        )

        if mod_match:
            try:
                modified_dt = datetime.strptime(
                    f"{mod_match.group('date')} {mod_match.group('time')}",
                    "%d-%b-%Y %H:%M"
                ).replace(tzinfo=timezone.utc)
            except Exception:
                modified_dt = None

        entries.append({
            "filename": filename,
            "url": f"{MPD_FTP_URL}{filename}",
            "mpd_num": mpd_num,
            "modified_dt": modified_dt
        })

    return entries


def select_recent_mpd_candidates(entries, now):
    """
    Select candidates by FTP Last-Modified time, not by MPD number.
    This is important because number sorting can grab stale or cross-year files.
    """

    entries_with_time = [e for e in entries if e["modified_dt"] is not None]

    if entries_with_time:
        recent = [
            e for e in entries_with_time
            if e["modified_dt"] >= now - timedelta(hours=MPD_RECENT_FILE_HOURS)
        ]

        recent = sorted(
            recent,
            key=lambda e: e["modified_dt"],
            reverse=True
        )

        return recent[:MAX_CANDIDATES]

    # Fallback only if timestamps are unavailable.
    # Still limited, and active/expiration logic below must pass.
    return sorted(
        entries,
        key=lambda e: e["mpd_num"] if e["mpd_num"] is not None else -1,
        reverse=True
    )[:MAX_CANDIDATES]


def read_mpd_zip(entry):
    z_resp = requests.get(
        entry["url"],
        headers=NO_CACHE_HEADERS,
        timeout=30
    )

    if z_resp.status_code != 200:
        print(f"  -> Failed to download {entry['filename']} HTTP {z_resp.status_code}")
        return None

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            with zipfile.ZipFile(io.BytesIO(z_resp.content)) as z:
                z.extractall(tmp_dir)

            shp_files = [
                os.path.join(tmp_dir, f)
                for f in os.listdir(tmp_dir)
                if f.lower().endswith(".shp")
            ]

            if not shp_files:
                print(f"  -> No shapefile found in {entry['filename']}")
                return None

            gdf = gpd.read_file(shp_files[0])
            gdf = safe_to_wgs84(gdf)

            if gdf is None or gdf.empty:
                return None

            return gdf.copy()

        except Exception as e:
            print(f"  -> Failed to read {entry['filename']}: {e}")
            return None


def fetch_and_process_ero():
    print("Fetching WPC Day 1 ERO from NOAA REST API...")

    params = {
        "where": "1=1",
        "outFields": "OUTLOOK",
        "returnGeometry": "true",
        "f": "geojson",
        "outSR": "4326",
        "time_buster": int(time.time())
    }

    try:
        response = requests.get(
            ERO_REST_URL,
            params=params,
            headers=NO_CACHE_HEADERS,
            timeout=30
        )
        response.raise_for_status()

        geojson = response.json()
        features = geojson.get("features", [])

        if not features:
            print("No ERO features returned.")
            return None

        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        gdf = safe_to_wgs84(gdf)

        if gdf is None or gdf.empty:
            print("ERO GeoDataFrame empty after geometry cleanup.")
            return None

        outlook_col = next(
            (col for col in gdf.columns if col.upper() == "OUTLOOK"),
            None
        )

        gdf["dataType"] = "ERO"

        if outlook_col:
            gdf["OUTLOOK"] = gdf[outlook_col]
            keep = ["dataType", "OUTLOOK", "geometry"]
        else:
            keep = ["dataType", "geometry"]

        gdf = gdf[[col for col in keep if col in gdf.columns]].copy()

        print(f"ERO features kept: {len(gdf)}")
        return gdf

    except Exception as e:
        print(f"Failed to fetch ERO from REST API: {e}")
        return None


def fetch_and_process_mpds():
    print("Fetching active MPDs using FTP Last-Modified + expiration math...")

    now = utc_now()
    mpd_gdfs = []

    try:
        entries = parse_mpd_directory_entries()

        if not entries:
            print("No MPD ZIP entries found.")
            return None

        candidates = select_recent_mpd_candidates(entries, now)

        print(f"Candidate MPD files to inspect: {len(candidates)}")
        for e in candidates:
            mod_txt = format_dt(e["modified_dt"]) if e["modified_dt"] else "Unknown"
            print(f"  Candidate: {e['filename']} | FTP modified: {mod_txt}")

        for entry in candidates:
            zip_filename = entry["filename"]
            mpd_num = entry["mpd_num"]

            print(f"\nChecking MPD: {zip_filename}")

            gdf = read_mpd_zip(entry)

            if gdf is None or gdf.empty:
                continue

            print(f"  -> Columns found: {list(gdf.columns)}")

            # Locate time columns.
            expire_col = find_column(
                gdf,
                exact_names=[
                    "EXPIRE", "EXPIRATION", "EXPIR", "EXP_TIME",
                    "END", "END_TIME", "VALID_TO", "VALIDEND",
                    "VALID_END", "VALID_UNTIL"
                ],
                contains=["EXP", "END", "VALID_TO", "VALIDEND", "UNTIL"]
            )

            issue_col = find_column(
                gdf,
                exact_names=[
                    "ISSUE", "ISSUED", "ISSUE_TIME", "ISSUED_TIME",
                    "START", "START_TIME", "VALID_FROM", "VALID_START",
                    "BEGIN", "BEGIN_TIME"
                ],
                contains=["ISSUE", "START", "BEGIN", "VALID_FROM", "VALID_START"]
            )

            if not expire_col:
                print("  -> No expiration column found. Dropping to prevent stale plotting.")
                continue

            gdf["expire_dt"] = gdf[expire_col].apply(parse_time_value)

            if issue_col:
                gdf["issue_dt"] = gdf[issue_col].apply(parse_time_value)
            else:
                gdf["issue_dt"] = pd.NaT

            # Use one representative time per MPD polygon.
            expire_dt = gdf["expire_dt"].dropna().iloc[0] if gdf["expire_dt"].notna().any() else pd.NaT
            issue_dt = gdf["issue_dt"].dropna().iloc[0] if gdf["issue_dt"].notna().any() else pd.NaT

            if pd.isna(expire_dt):
                print("  -> Expiration value could not be parsed. Dropping.")
                continue

            # Safety check to prevent year/format parsing mistakes.
            if expire_dt > now + timedelta(hours=MAX_EXPIRATION_AHEAD_HOURS):
                print(
                    f"  -> Expiration is unrealistically far in the future "
                    f"({format_dt(expire_dt)}). Dropping."
                )
                continue

            # Core active logic.
            # If issue/start time exists, require issue <= now <= expire.
            # If issue/start is missing, require now <= expire and recent FTP modified time.
            if pd.notna(issue_dt):
                is_active = issue_dt <= now <= expire_dt
            else:
                recently_modified = (
                    entry["modified_dt"] is not None
                    and entry["modified_dt"] >= now - timedelta(hours=MPD_RECENT_FILE_HOURS)
                )
                is_active = now <= expire_dt and recently_modified

            if not is_active:
                print(
                    f"  -> Inactive. "
                    f"Valid: {format_dt(issue_dt)} - {format_dt(expire_dt)} | "
                    f"Now: {format_dt(now)}"
                )
                continue

            print(
                f"  -> ACTIVE. "
                f"Valid: {format_dt(issue_dt)} - {format_dt(expire_dt)}"
            )

            active_gdf = gdf.copy()
            active_gdf["dataType"] = "MPD"
            active_gdf["mpd_number"] = f"{mpd_num:04d}" if mpd_num is not None else ""
            active_gdf["mpd_tag"] = f"MPD {mpd_num:04d}" if mpd_num is not None else "MPD"
            active_gdf["valid_start_utc"] = iso_dt(issue_dt)
            active_gdf["valid_end_utc"] = iso_dt(expire_dt)
            active_gdf["valid_time"] = f"{format_dt(issue_dt)} - {format_dt(expire_dt)}"
            active_gdf["hoverText"] = (
                f"{active_gdf['mpd_tag'].iloc[0]}\n"
                f"Valid: {active_gdf['valid_time'].iloc[0]}"
            )

            keep_cols = [
                "dataType",
                "mpd_number",
                "mpd_tag",
                "valid_start_utc",
                "valid_end_utc",
                "valid_time",
                "hoverText",
                "geometry"
            ]

            active_gdf = active_gdf[[c for c in keep_cols if c in active_gdf.columns]].copy()

            mpd_gdfs.append(active_gdf)

        if mpd_gdfs:
            out = gpd.GeoDataFrame(
                pd.concat(mpd_gdfs, ignore_index=True),
                geometry="geometry",
                crs="EPSG:4326"
            )

            return out

        print("No active MPDs found.")
        return None

    except Exception as e:
        print(f"Failed to fetch MPDs: {e}")
        return None


def main():
    print("Starting WPC data processing...")

    final_gdfs = []

    ero_gdf = fetch_and_process_ero()
    if ero_gdf is not None and not ero_gdf.empty:
        final_gdfs.append(ero_gdf)

    mpd_gdf = fetch_and_process_mpds()
    if mpd_gdf is not None and not mpd_gdf.empty:
        final_gdfs.append(mpd_gdf)

    if not final_gdfs:
        print("No valid data processed. GeoJSON not updated.")
        return

    combined_gdf = gpd.GeoDataFrame(
        pd.concat(final_gdfs, ignore_index=True),
        geometry="geometry",
        crs="EPSG:4326"
    )

    combined_gdf = combined_gdf[
        combined_gdf.geometry.notna() & ~combined_gdf.geometry.is_empty
    ].copy()

    # Convert unsupported object/datetime values to strings before GeoJSON write.
    for col in combined_gdf.columns:
        if col == "geometry":
            continue

        if pd.api.types.is_datetime64_any_dtype(combined_gdf[col]):
            combined_gdf[col] = combined_gdf[col].astype(str)

        # Keep object fields JSON-safe.
        if combined_gdf[col].dtype == "object":
            combined_gdf[col] = combined_gdf[col].where(
                combined_gdf[col].notna(),
                ""
            ).astype(str)

    combined_gdf.to_file(OUTPUT_FILENAME, driver="GeoJSON")

    mpd_count = 0
    ero_count = 0

    if "dataType" in combined_gdf.columns:
        mpd_count = int((combined_gdf["dataType"] == "MPD").sum())
        ero_count = int((combined_gdf["dataType"] == "ERO").sum())

    print(f"Successfully wrote {OUTPUT_FILENAME}")
    print(f"ERO features: {ero_count}")
    print(f"Active MPD features: {mpd_count}")


if __name__ == "__main__":
    main()
