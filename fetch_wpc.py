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

# =====================================================================
# CONFIGURATION
# =====================================================================

ERO_REST_URL = "https://mapservices.weather.noaa.gov/vector/rest/services/hazards/wpc_precip_hazards/MapServer/0/query"
MPD_FTP_URL = "https://ftp-wpc.ncep.noaa.gov/shapefiles/qpf/mpd/"
MPD_PRODUCT_URL = "https://www.wpc.ncep.noaa.gov/metwatch/metwatch_mpd_multi.php"

OUTPUT_FILENAME = "wpc_data.geojson"

# Look back far enough to catch current active MPDs, but not so far that
# GitHub Actions wastes time scanning the full archive every run.
MPD_LOOKBACK_HOURS = 48
MAX_MPD_ZIPS_TO_CHECK = 80

NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
    "User-Agent": "WPC-Hydro-Dashboard-Bot/1.0"
}


# =====================================================================
# GENERAL HELPERS
# =====================================================================

def utc_now():
    return datetime.now(timezone.utc)


def extract_mpd_num(text):
    match = re.search(r"MPD[_\s-]*(\d{3,4})|(\d{3,4})", str(text), re.IGNORECASE)
    if not match:
        return None
    num = match.group(1) or match.group(2)
    return int(num)


def iso_z(dt):
    if dt is None or pd.isna(dt):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def display_utc(dt):
    if dt is None or pd.isna(dt):
        return "Unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%HZ %b %d %Y")


def safe_to_wgs84(gdf):
    if gdf.empty:
        return gdf

    if gdf.crs is None:
        # WPC shapefiles are normally lon/lat; set CRS if missing.
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    else:
        gdf = gdf.to_crs("EPSG:4326")

    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
    return gdf


# =====================================================================
# TIME PARSING
# =====================================================================

def parse_datetime_value(value):
    """
    Handles common WPC/DBF timestamp forms:
    - datetime / pandas Timestamp
    - YYYYMMDDHHMM
    - YYMMDDHHMM
    - YYYYMMDDHHMMSS
    - ISO-ish strings
    - epoch seconds / milliseconds
    """
    if value is None or pd.isna(value):
        return None

    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        if value.tzinfo is None:
            return value.to_pydatetime().replace(tzinfo=timezone.utc)
        return value.to_pydatetime().astimezone(timezone.utc)

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    # Numeric values can be YYYYMMDDHHMM, YYMMDDHHMM, or epoch.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer():
            s = str(int(value))
        else:
            s = str(value).strip()
    else:
        s = str(value).strip()

    if not s or s.lower() in {"nan", "nat", "none", "null"}:
        return None

    # Avoid interpreting valid ranges as a single timestamp.
    if re.search(r"\d{6}\s*Z?\s*[-–]\s*\d{6}\s*Z?", s, re.IGNORECASE):
        return None

    digits = re.sub(r"\D", "", s)

    for fmt in [
        ("%Y%m%d%H%M%S", 14),
        ("%Y%m%d%H%M", 12),
        ("%y%m%d%H%M", 10),
    ]:
        date_fmt, expected_len = fmt
        if len(digits) == expected_len:
            try:
                return datetime.strptime(digits, date_fmt).replace(tzinfo=timezone.utc)
            except Exception:
                pass

    # Epoch fallback
    try:
        numeric = float(s)
        if numeric > 1e12:
            return datetime.fromtimestamp(numeric / 1000.0, tz=timezone.utc)
        if numeric > 1e9:
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
    except Exception:
        pass

    # General pandas fallback
    try:
        parsed = pd.to_datetime(s, utc=True, errors="coerce")
        if pd.notna(parsed):
            return parsed.to_pydatetime().astimezone(timezone.utc)
    except Exception:
        pass

    return None


def month_year_shift(year, month, shift):
    m = month + shift
    y = year
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return y, m


def resolve_ddhhmm(ddhhmm, reference_dt):
    """
    MPD text products often use DDHHMMZ. Resolve that to year/month
    by choosing the candidate closest to the reference time.
    """
    if reference_dt is None:
        reference_dt = utc_now()

    if reference_dt.tzinfo is None:
        reference_dt = reference_dt.replace(tzinfo=timezone.utc)

    token = str(ddhhmm).strip()
    if not re.fullmatch(r"\d{6}", token):
        return None

    day = int(token[0:2])
    hour = int(token[2:4])
    minute = int(token[4:6])

    candidates = []
    for shift in [-1, 0, 1]:
        y, m = month_year_shift(reference_dt.year, reference_dt.month, shift)
        try:
            candidates.append(datetime(y, m, day, hour, minute, tzinfo=timezone.utc))
        except ValueError:
            continue

    if not candidates:
        return None

    return min(candidates, key=lambda d: abs((d - reference_dt).total_seconds()))


def parse_valid_range_text(text, reference_dt):
    """
    Parses strings like:
    Valid 121700Z - 122300Z
    VALID 121700Z-130100Z
    """
    if text is None:
        return None, None

    s = str(text)

    match = re.search(
        r"VALID\s+(\d{6})Z?\s*[-–]\s*(\d{6})Z?",
        s,
        re.IGNORECASE
    )

    if not match:
        match = re.search(
            r"(\d{6})Z?\s*[-–]\s*(\d{6})Z?",
            s,
            re.IGNORECASE
        )

    if not match:
        return None, None

    start = resolve_ddhhmm(match.group(1), reference_dt)
    end = resolve_ddhhmm(match.group(2), reference_dt)

    if start and end and end < start:
        # Handles crossing 00Z or month boundary.
        while end < start:
            end += timedelta(days=1)

    return start, end


def find_time_column(gdf, exact_names, contains_names):
    col_map = {c.strip().upper(): c for c in gdf.columns}

    for name in exact_names:
        if name.upper() in col_map:
            return col_map[name.upper()]

    for upper_name, original_name in col_map.items():
        if any(piece.upper() in upper_name for piece in contains_names):
            return original_name

    return None


def infer_valid_times_from_shapefile(gdf, reference_dt):
    """
    First tries to parse a valid range from any string field.
    Then tries start/end columns separately.
    """
    # 1. Look for a combined valid range in any field.
    for col in gdf.columns:
        if col == "geometry":
            continue

        for value in gdf[col].dropna().astype(str).head(10):
            start, end = parse_valid_range_text(value, reference_dt)
            if start and end:
                return start, end

    # 2. Look for individual start/end fields.
    start_col = find_time_column(
        gdf,
        exact_names=[
            "VALID", "VALIDTIME", "VALID_TIME", "VALID_FROM",
            "START", "START_TIME", "BEGIN", "BEGIN_TIME",
            "ISSUE", "ISSUED", "ISSUE_TIME", "INIT", "INIT_TIME"
        ],
        contains_names=["VALID_FROM", "START", "BEGIN", "ISSUE", "INIT"]
    )

    end_col = find_time_column(
        gdf,
        exact_names=[
            "EXPIRE", "EXPIRATION", "EXPIR", "EXP_TIME",
            "END", "END_TIME", "VALID_TO", "VALIDEND",
            "VALID_UNTIL", "UNTIL"
        ],
        contains_names=["EXP", "END", "VALID_TO", "UNTIL"]
    )

    start_dt = None
    end_dt = None

    if start_col:
        for value in gdf[start_col].dropna().head(10):
            start_dt = parse_datetime_value(value)
            if start_dt:
                break

    if end_col:
        for value in gdf[end_col].dropna().head(10):
            end_dt = parse_datetime_value(value)
            if end_dt:
                break

    return start_dt, end_dt


def fetch_valid_times_from_mpd_text(mpd_num, reference_dt):
    """
    Fallback: use WPC metwatch text page and parse the 'Valid DDHHMMZ - DDHHMMZ' line.
    """
    years_to_try = []
    if reference_dt:
        years_to_try.extend([reference_dt.year, reference_dt.year - 1, reference_dt.year + 1])
    else:
        now = utc_now()
        years_to_try.extend([now.year, now.year - 1])

    seen = set()
    for year in years_to_try:
        if year in seen:
            continue
        seen.add(year)

        try:
            resp = requests.get(
                MPD_PRODUCT_URL,
                params={"md": f"{mpd_num:04d}", "yr": str(year), "_": int(time.time())},
                headers=NO_CACHE_HEADERS,
                timeout=20
            )
            if resp.status_code != 200:
                continue

            start, end = parse_valid_range_text(resp.text, reference_dt)
            if start and end:
                return start, end
        except Exception as e:
            print(f"  -> Text fallback failed for MPD {mpd_num:04d} year {year}: {e}")

    return None, None


# =====================================================================
# ERO PROCESSING
# =====================================================================

def fetch_and_process_ero():
    print("Fetching WPC Day 1 ERO from NOAA REST API...")

    params = {
        "where": "1=1",
        "outFields": "OUTLOOK",
        "returnGeometry": "true",
        "f": "geojson",
        "outSR": "4326",
        "_": int(time.time())
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

        if gdf.empty:
            print("ERO GeoDataFrame is empty after geometry cleanup.")
            return None

        outlook_col = next((col for col in gdf.columns if col.upper() == "OUTLOOK"), None)

        gdf["dataType"] = "ERO"
        if outlook_col:
            gdf["OUTLOOK"] = gdf[outlook_col]
            keep = ["dataType", "OUTLOOK", "geometry"]
        else:
            keep = ["dataType", "geometry"]

        gdf = gdf[[c for c in keep if c in gdf.columns]].copy()
        print(f"ERO features kept: {len(gdf)}")
        return gdf

    except Exception as e:
        print(f"Failed to fetch/process ERO: {e}")
        return None


# =====================================================================
# MPD PROCESSING
# =====================================================================

def parse_mpd_zip_index():
    """
    Reads the WPC MPD shapefile directory and returns dictionaries:
    {
      filename,
      url,
      mpd_num,
      modified_dt
    }
    """
    print("Reading WPC MPD shapefile ZIP directory...")

    resp = requests.get(
        f"{MPD_FTP_URL}?_={int(time.time())}",
        headers=NO_CACHE_HEADERS,
        timeout=30
    )
    resp.raise_for_status()

    entries = []

    for line in resp.text.splitlines():
        href_match = re.search(
            r'href="(?P<href>MPD_(?P<num>\d{3,4})_final\.zip)"',
            line,
            re.IGNORECASE
        )

        if not href_match:
            continue

        filename = href_match.group("href")
        mpd_num = int(href_match.group("num"))

        mod_match = re.search(
            r"</a>\s*(?P<modified>\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2})",
            line
        )

        modified_dt = None
        if mod_match:
            try:
                modified_dt = datetime.strptime(
                    mod_match.group("modified"),
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


def select_candidate_mpd_zips(entries, now):
    """
    Select recent files by Last-Modified time when available.
    Fallback to the last N files by MPD number if timestamps are unavailable.
    """
    with_time = [e for e in entries if e["modified_dt"] is not None]

    if with_time:
        recent = [
            e for e in with_time
            if e["modified_dt"] >= now - timedelta(hours=MPD_LOOKBACK_HOURS)
        ]

        # If there are no recent files, fallback to the latest modified files.
        if not recent:
            recent = sorted(with_time, key=lambda e: e["modified_dt"])[-MAX_MPD_ZIPS_TO_CHECK:]

        # Limit workload.
        recent = sorted(recent, key=lambda e: e["modified_dt"], reverse=True)[:MAX_MPD_ZIPS_TO_CHECK]
        return recent

    return sorted(entries, key=lambda e: e["mpd_num"], reverse=True)[:MAX_MPD_ZIPS_TO_CHECK]


def read_mpd_zip(entry):
    """
    Downloads one MPD shapefile ZIP and returns a GeoDataFrame.
    """
    resp = requests.get(entry["url"], headers=NO_CACHE_HEADERS, timeout=30)

    if resp.status_code != 200:
        print(f"  -> Download failed: {entry['filename']} HTTP {resp.status_code}")
        return None

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                z.extractall(tmp_dir)

            shp_files = [
                os.path.join(tmp_dir, f)
                for f in os.listdir(tmp_dir)
                if f.lower().endswith(".shp")
            ]

            if not shp_files:
                print(f"  -> No .shp found in {entry['filename']}")
                return None

            gdf = gpd.read_file(shp_files[0])
            gdf = safe_to_wgs84(gdf)

            if gdf.empty:
                print(f"  -> Empty shapefile: {entry['filename']}")
                return None

            return gdf.copy()

        except Exception as e:
            print(f"  -> Failed reading {entry['filename']}: {e}")
            return None


def fetch_and_process_mpds():
    print("Fetching and filtering active MPDs...")

    now = utc_now()
    mpd_gdfs = []

    try:
        entries = parse_mpd_zip_index()

        if not entries:
            print("No MPD ZIP entries found.")
            return None

        candidates = select_candidate_mpd_zips(entries, now)
        print(f"Candidate MPD ZIPs to check: {len(candidates)}")

        for entry in candidates:
            mpd_num = entry["mpd_num"]
            filename = entry["filename"]

            print(f"Checking {filename}...")

            gdf = read_mpd_zip(entry)
            if gdf is None or gdf.empty:
                continue

            print(f"  -> Columns: {list(gdf.columns)}")

            reference_dt = entry["modified_dt"] or now

            valid_start, valid_end = infer_valid_times_from_shapefile(gdf, reference_dt)

            if valid_end is None:
                print("  -> Valid end time not found in shapefile. Trying MPD text fallback...")
                fallback_start, fallback_end = fetch_valid_times_from_mpd_text(mpd_num, reference_dt)

                if fallback_start:
                    valid_start = fallback_start
                if fallback_end:
                    valid_end = fallback_end

            if valid_end is None:
                print(f"  -> Could not determine valid end time for MPD {mpd_num:04d}. Skipping.")
                continue

            # Active logic.
            if valid_start is not None:
                is_active = valid_start <= now <= valid_end
            else:
                # If only expiration is known, require current time before end.
                is_active = now <= valid_end

            if not is_active:
                print(
                    f"  -> MPD {mpd_num:04d} inactive. "
                    f"Valid: {display_utc(valid_start)} - {display_utc(valid_end)}"
                )
                continue

            mpd_tag = f"MPD {mpd_num:04d}"
            valid_time = f"{display_utc(valid_start)} - {display_utc(valid_end)}"

            print(f"  -> ACTIVE: {mpd_tag} | {valid_time}")

            gdf = gdf.copy()
            gdf["dataType"] = "MPD"
            gdf["mpd_number"] = f"{mpd_num:04d}"
            gdf["mpd_tag"] = mpd_tag
            gdf["valid_start_utc"] = iso_z(valid_start)
            gdf["valid_end_utc"] = iso_z(valid_end)
            gdf["valid_time"] = valid_time
            gdf["hoverText"] = f"{mpd_tag}\nValid: {valid_time}"

            keep = [
                "dataType",
                "mpd_number",
                "mpd_tag",
                "valid_start_utc",
                "valid_end_utc",
                "valid_time",
                "hoverText",
                "geometry"
            ]

            gdf = gdf[[c for c in keep if c in gdf.columns]].copy()
            mpd_gdfs.append(gdf)

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
        print(f"Failed to fetch/process MPDs: {e}")
        return None


# =====================================================================
# MAIN
# =====================================================================

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

    combined_gdf = combined_gdf[combined_gdf.geometry.notna() & ~combined_gdf.geometry.is_empty].copy()

    # Ensure all non-geometry fields are JSON-safe strings/numbers.
    for col in combined_gdf.columns:
        if col == "geometry":
            continue
        if pd.api.types.is_datetime64_any_dtype(combined_gdf[col]):
            combined_gdf[col] = combined_gdf[col].astype(str)

    combined_gdf.to_file(OUTPUT_FILENAME, driver="GeoJSON")

    mpd_count = int((combined_gdf["dataType"] == "MPD").sum()) if "dataType" in combined_gdf.columns else 0
    ero_count = int((combined_gdf["dataType"] == "ERO").sum()) if "dataType" in combined_gdf.columns else 0

    print(f"Successfully wrote {OUTPUT_FILENAME}")
    print(f"ERO features: {ero_count}")
    print(f"Active MPD features: {mpd_count}")


if __name__ == "__main__":
    main()
