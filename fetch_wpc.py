import geopandas as gpd
import pandas as pd
import requests
import zipfile
import io
import os
import re
import time
import tempfile
import math
from html import unescape
from datetime import datetime, timezone, timedelta

from shapely.geometry import Polygon

ERO_REST_URL = "https://mapservices.weather.noaa.gov/vector/rest/services/hazards/wpc_precip_hazards/MapServer/0/query"
MPD_FTP_URL = "https://ftp-wpc.ncep.noaa.gov/shapefiles/qpf/mpd/"
MPD_ACTIVE_URL = "https://www.wpc.ncep.noaa.gov/metwatch/metwatch_mpd.php"
MPD_TEXT_URL = "https://www.wpc.ncep.noaa.gov/metwatch/metwatch_mpd_multi.php"
OUTPUT_FILENAME = "wpc_data.geojson"

# A malformed MPD that accidentally contains a second distant polygon creates
# an extremely long connecting segment. Normal operational MPDs should not
# contain an individual polygon edge remotely close to this length.
MAX_MPD_EDGE_KM = 1800.0

NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
    "User-Agent": "WPC-Hydro-Dashboard-Bot/4.0"
}


def utc_now():
    return datetime.now(timezone.utc)


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


def resolve_ddhhmm(ddhhmm, reference_dt=None):
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
            candidates.append(
                datetime(y, m, day, hour, minute, tzinfo=timezone.utc)
            )
        except ValueError:
            continue

    if not candidates:
        return None

    return min(
        candidates,
        key=lambda d: abs((d - reference_dt).total_seconds())
    )


def html_to_product_text(raw_html):
    """Convert the WPC MPD HTML response into readable bulletin text."""
    text = re.sub(r"(?i)<br\s*/?>", "\n", raw_html)
    text = re.sub(
        r"(?i)</(?:p|div|pre|tr|li|table|h[1-6])>",
        "\n",
        text,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text).replace("\r", "")

    cleaned_lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def extract_latest_mpd_rendition(text):
    """
    Return the bulletin rendition associated with the last LAT...LON block.

    A resend may replace the original bulletin while intermediary web pages or
    caches briefly contain more than one rendition. Selecting the final
    coordinate block gives the corrected resend precedence.
    """
    latlon_positions = [
        match.start()
        for match in re.finditer(r"LAT\.\.\.LON", text, re.IGNORECASE)
    ]

    if not latlon_positions:
        return text

    latest_latlon = latlon_positions[-1]
    start_candidates = []

    for marker in [
        "MESOSCALE PRECIPITATION DISCUSSION",
        "FOUS30",
    ]:
        position = text.upper().rfind(marker, 0, latest_latlon)
        if position >= 0:
            start_candidates.append(position)

    start = max(start_candidates) if start_candidates else 0
    end = text.find("$$", latest_latlon)
    if end < 0:
        end = len(text)
    else:
        end += 2

    return text[start:end]


def fetch_latest_mpd_text(mpd_num):
    """Fetch the newest official text rendition, including any resend."""
    print(
        f" -> Fetching latest official text rendition for MPD "
        f"{mpd_num:04d}..."
    )
    now = utc_now()

    for yr in [now.year, now.year - 1]:
        try:
            url = (
                f"{MPD_TEXT_URL}?md={mpd_num:04d}&yr={yr}"
                f"&t={time.time_ns()}"
            )
            response = requests.get(
                url,
                headers=NO_CACHE_HEADERS,
                timeout=20,
            )
            if response.status_code != 200:
                continue

            text = html_to_product_text(response.text)
            latest = extract_latest_mpd_rendition(text)

            if re.search(r"VALID\s+\d{6}Z?", latest, re.IGNORECASE):
                return latest, yr
        except Exception as error:
            print(f" -> Text retrieval attempt failed for {yr}: {error}")

    return None, None


def parse_mpd_times(product_text):
    now = utc_now()
    match = re.search(
        r"VALID\s+(\d{6})Z?\s*[-–]\s*(\d{6})Z?",
        product_text,
        re.IGNORECASE,
    )
    if not match:
        return None, None

    start_dt = resolve_ddhhmm(match.group(1), now)
    end_dt = resolve_ddhhmm(match.group(2), start_dt or now)

    if start_dt and end_dt and end_dt < start_dt:
        end_dt += timedelta(days=1)

    return start_dt, end_dt


def parse_mpd_tag(product_text, mpd_num):
    match = re.search(
        r"CONCERNING\.\.\.\s*(.+?)(?=\n\s*VALID\b|\bVALID\s+\d{6}|$)",
        product_text,
        re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return f"MPD {mpd_num:04d}"

    tag = re.sub(r"\s+", " ", match.group(1)).strip(" .")
    return tag if tag else f"MPD {mpd_num:04d}"


def decode_wpc_latlon_token(token):
    """Decode a compact WPC LAT...LON token into (longitude, latitude)."""
    token = token.strip()
    if not re.fullmatch(r"\d{8,10}", token):
        return None

    latitude = int(token[:4]) / 100.0
    longitude_west = int(token[4:]) / 100.0

    if not (0.0 <= latitude <= 90.0):
        return None
    if not (0.0 <= longitude_west <= 180.0):
        return None

    return (-longitude_west, latitude)


def haversine_km(coord_a, coord_b):
    lon1, lat1 = coord_a
    lon2, lat2 = coord_b
    radius_km = 6371.0088

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    value = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(d_lambda / 2.0) ** 2
    )
    return 2.0 * radius_km * math.asin(min(1.0, math.sqrt(value)))


def parse_latest_latlon_polygon(product_text):
    """Parse the last LAT...LON block from the latest MPD text rendition."""
    matches = list(
        re.finditer(
            r"LAT\.\.\.LON\s+((?:\d{8,10}(?:\s+|$)){3,})",
            product_text,
            re.IGNORECASE,
        )
    )

    if not matches:
        return None, "No LAT...LON block found"

    token_block = matches[-1].group(1)
    tokens = re.findall(r"\b\d{8,10}\b", token_block)
    coordinates = []

    for token in tokens:
        coordinate = decode_wpc_latlon_token(token)
        if coordinate is None:
            return None, f"Invalid LAT...LON token: {token}"
        if not coordinates or coordinate != coordinates[-1]:
            coordinates.append(coordinate)

    if len(coordinates) >= 2 and coordinates[0] == coordinates[-1]:
        coordinates.pop()

    if len(set(coordinates)) < 3:
        return None, "Fewer than three unique LAT...LON vertices"

    closed_coordinates = coordinates + [coordinates[0]]
    edge_lengths = [
        haversine_km(closed_coordinates[index], closed_coordinates[index + 1])
        for index in range(len(coordinates))
    ]
    maximum_edge = max(edge_lengths)

    if maximum_edge > MAX_MPD_EDGE_KM:
        return (
            None,
            f"Rejected implausible {maximum_edge:.0f}-km polygon edge; "
            "possible concatenated MPD coordinates",
        )

    polygon = Polygon(coordinates)
    if polygon.is_empty:
        return None, "LAT...LON polygon is empty"

    if not polygon.is_valid:
        polygon = polygon.buffer(0)

    if polygon.is_empty or not polygon.is_valid:
        return None, "LAT...LON polygon could not be repaired"

    return polygon, f"Official text LAT...LON ({len(coordinates)} vertices)"


def fetch_and_process_ero():
    print("Fetching WPC Day 1 ERO...")
    try:
        response = requests.get(
            f"{ERO_REST_URL}?where=1=1&outFields=OUTLOOK&f=geojson"
            f"&time_buster={time.time_ns()}",
            headers=NO_CACHE_HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        gdf = gpd.read_file(response.text, driver="GeoJSON")
        if gdf.empty or gdf.geometry.is_empty.all():
            return None

        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
        gdf["dataType"] = "ERO"
        outlook_col = next(
            (col for col in gdf.columns if col.upper() == "OUTLOOK"),
            None,
        )
        if outlook_col:
            gdf["OUTLOOK"] = gdf[outlook_col]

        return gdf[
            [c for c in ["dataType", "OUTLOOK", "geometry"] if c in gdf.columns]
        ].copy()
    except Exception as error:
        print(f"ERO failed: {error}")
        return None


def fetch_active_mpd_numbers():
    print(
        "Scraping exact active MPDs directly from WPC webpage "
        f"({MPD_ACTIVE_URL})..."
    )
    try:
        response = requests.get(
            f"{MPD_ACTIVE_URL}?t={time.time_ns()}",
            headers=NO_CACHE_HEADERS,
            timeout=20,
        )
        response.raise_for_status()

        matches = re.findall(r"md=(\d{3,4})", response.text)
        active_nums = sorted(set(int(match) for match in matches))

        print(f" -> Found active MPD numbers: {active_nums}")
        return active_nums
    except Exception as error:
        print(f"Failed to scrape active MPD numbers: {error}")
        return []


def read_shapefile_fallback(mpd_num):
    """Use the legacy final ZIP only when official text geometry is unavailable."""
    zip_filename = f"MPD_{mpd_num:04d}_final.zip"
    zip_url = f"{MPD_FTP_URL}{zip_filename}?t={time.time_ns()}"

    response = requests.get(
        zip_url,
        headers=NO_CACHE_HEADERS,
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Shapefile {zip_filename} returned HTTP {response.status_code}"
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            archive.extractall(tmp_dir)

        shp_files = [
            os.path.join(root, filename)
            for root, _, filenames in os.walk(tmp_dir)
            for filename in filenames
            if filename.lower().endswith(".shp")
        ]
        if not shp_files:
            raise RuntimeError("No .shp file found in MPD ZIP")

        gdf = gpd.read_file(shp_files[0])
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
        if gdf.empty:
            raise RuntimeError("MPD shapefile contains no usable geometry")

        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326", allow_override=True)
        else:
            gdf = gdf.to_crs("EPSG:4326")

        geometry = gdf.geometry.unary_union
        if geometry.is_empty:
            raise RuntimeError("Dissolved MPD shapefile geometry is empty")

        return geometry, gdf


def fetch_and_process_mpds():
    active_nums = fetch_active_mpd_numbers()
    if not active_nums:
        print("No active MPDs found on WPC webpage. Map will be cleared of MPDs.")
        return None

    mpd_gdfs = []

    for mpd_num in active_nums:
        print(f"\nProcessing MPD {mpd_num:04d}...")

        product_text, product_year = fetch_latest_mpd_text(mpd_num)
        if not product_text:
            print(
                f" -> Could not retrieve official text for {mpd_num:04d}. "
                "Skipping."
            )
            continue

        valid_start, valid_end = parse_mpd_times(product_text)
        if not valid_start or not valid_end:
            print(
                f" -> Could not parse official valid times for {mpd_num:04d}. "
                "Skipping."
            )
            continue

        mpd_tag = parse_mpd_tag(product_text, mpd_num)
        geometry, geometry_note = parse_latest_latlon_polygon(product_text)
        geometry_source = "official_text_latest"

        if geometry is None:
            print(f" -> Official text geometry unavailable: {geometry_note}")
            print(" -> Attempting cache-busted final shapefile fallback...")
            try:
                geometry, fallback_gdf = read_shapefile_fallback(mpd_num)
                geometry_source = "final_shapefile_fallback"

                # Preserve a shapefile tag only when the official text did not
                # provide a useful concerning line.
                if mpd_tag == f"MPD {mpd_num:04d}":
                    col_map = {
                        column.strip().upper(): column
                        for column in fallback_gdf.columns
                    }
                    tag_col = next(
                        (
                            col_map[column]
                            for column in ["TAG", "SUBJECT", "PROB"]
                            if column in col_map
                        ),
                        None,
                    )
                    if tag_col and not pd.isna(fallback_gdf[tag_col].iloc[0]):
                        raw_tag = str(fallback_gdf[tag_col].iloc[0])
                        mpd_tag = (
                            raw_tag.split("...")[-1].strip().title()
                            if "..." in raw_tag
                            else raw_tag.title()
                        )
            except Exception as error:
                print(f" -> Fallback shapefile failed: {error}")
                print(f" -> MPD {mpd_num:04d} omitted rather than drawing bad geometry.")
                continue
        else:
            print(f" -> Using corrected/latest text geometry: {geometry_note}")

        # Preserve the official four-digit HHMMZ time from the MPD text.
        issue_str = valid_start.strftime("%H%MZ %b %d %Y")
        expire_str = valid_end.strftime("%H%MZ %b %d %Y")
        valid_str = f"{issue_str} - {expire_str}"

        active_gdf = gpd.GeoDataFrame(
            {
                "dataType": ["MPD"],
                "mpd_number": [f"{mpd_num:04d}"],
                "mpd_tag": [mpd_tag],
                "valid_start_utc": [
                    valid_start.strftime("%Y-%m-%dT%H:%M:%SZ")
                ],
                "valid_end_utc": [
                    valid_end.strftime("%Y-%m-%dT%H:%M:%SZ")
                ],
                "valid_time": [valid_str],
                "hoverText": [f"{mpd_tag}\nValid: {valid_str}"],
                "geometry_source": [geometry_source],
                "product_year": [str(product_year or valid_start.year)],
            },
            geometry=[geometry],
            crs="EPSG:4326",
        )

        print(
            f" -> Successfully mapped from {geometry_source}: "
            f"{mpd_tag} | Valid {valid_str}"
        )
        mpd_gdfs.append(active_gdf)

    if mpd_gdfs:
        result = gpd.GeoDataFrame(
            pd.concat(mpd_gdfs, ignore_index=True),
            geometry="geometry",
            crs="EPSG:4326",
        )
        # One authoritative feature per active MPD number. A resend replaces
        # the earlier rendition rather than being appended beside it.
        result = result.drop_duplicates(
            subset=["mpd_number"],
            keep="last",
        ).copy()
        return result

    return None


def main():
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
        crs="EPSG:4326",
    )
    combined_gdf = combined_gdf[
        combined_gdf.geometry.notna() & ~combined_gdf.geometry.is_empty
    ].copy()

    for column in combined_gdf.columns:
        if column == "geometry":
            continue
        if pd.api.types.is_datetime64_any_dtype(combined_gdf[column]):
            combined_gdf[column] = combined_gdf[column].astype(str)
        if combined_gdf[column].dtype == "object":
            combined_gdf[column] = (
                combined_gdf[column]
                .where(combined_gdf[column].notna(), "")
                .astype(str)
            )

    # Write atomically so the repository never contains a partially written
    # GeoJSON file during an update.
    temporary_output = f"{OUTPUT_FILENAME}.tmp"
    try:
        combined_gdf.to_file(temporary_output, driver="GeoJSON")
        os.replace(temporary_output, OUTPUT_FILENAME)
    finally:
        if os.path.exists(temporary_output):
            os.remove(temporary_output)

    print(f"Successfully wrote resend-aware data to {OUTPUT_FILENAME}")


if __name__ == "__main__":
    main()
