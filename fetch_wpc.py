import geopandas as gpd
import pandas as pd
import requests
import zipfile
import io
import gzip
import os
import re
import time
import tempfile
import math
import json
from html import unescape
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

from shapely.geometry import Polygon

ERO_REST_URL = "https://mapservices.weather.noaa.gov/vector/rest/services/hazards/wpc_precip_hazards/MapServer/0/query"
ERO_PAGE_URL = "https://www.wpc.ncep.noaa.gov/qpf/excessive_rainfall_outlook_ero.php"
ERO_POINTS_URL = "https://www.wpc.ncep.noaa.gov/qpf/94epoints.txt"
AWC_STATIONS_URL = "https://aviationweather.gov/data/cache/stations.cache.json.gz"
MPD_FTP_URL = "https://ftp-wpc.ncep.noaa.gov/shapefiles/qpf/mpd/"
MPD_ACTIVE_URL = "https://www.wpc.ncep.noaa.gov/metwatch/metwatch_mpd.php"
MPD_TEXT_URL = "https://www.wpc.ncep.noaa.gov/metwatch/metwatch_mpd_multi.php"
OUTPUT_FILENAME = "wpc_data.geojson"
SCRIPT_VERSION = "2026-11-23.0025-ero-no-area-wording-fix"

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


def empty_ero_gdf():
    return gpd.GeoDataFrame(
        columns=["dataType", "OUTLOOK", "ero_source", "geometry"],
        geometry="geometry",
        crs="EPSG:4326",
    )


def normalize_ero_gdf(gdf, source_name):
    """Normalize polygonal ERO risk areas from an official WPC GIS source."""
    if gdf is None or gdf.empty:
        return empty_ero_gdf()

    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if gdf.empty:
        return empty_ero_gdf()

    geometry_types = sorted(set(gdf.geometry.geom_type.astype(str)))
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    if gdf.empty:
        print(
            f" -> {source_name} contains no polygon risk geometry "
            f"(geometry types: {geometry_types})."
        )
        return empty_ero_gdf()

    if gdf.crs is not None and str(gdf.crs).upper() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")

    outlook_col = next(
        (
            col for col in gdf.columns
            if str(col).lower() in {"outlook", "risk", "category", "label"}
        ),
        None,
    )

    if outlook_col:
        gdf["OUTLOOK"] = gdf[outlook_col].astype(str)
    else:
        dn_col = next(
            (col for col in gdf.columns if str(col).lower() == "dn"),
            None,
        )
        if dn_col:
            labels = {
                1: "Marginal (At Least 5%)",
                2: "Slight (At Least 15%)",
                3: "Moderate (At Least 40%)",
                4: "High (At Least 70%)",
            }
            gdf["OUTLOOK"] = pd.to_numeric(
                gdf[dn_col], errors="coerce"
            ).map(labels)

    if "OUTLOOK" not in gdf.columns:
        raise ValueError(
            f"{source_name} ERO data has no recognizable risk-category field"
        )

    # Do not treat label/centroid features such as "None Expected" as risk
    # polygons. Only the four operational ERO categories are displayable.
    risk_mask = gdf["OUTLOOK"].fillna("").str.upper().str.contains(
        r"MARGINAL|MRGL|SLIGHT|SLGT|MODERATE|MDT|HIGH",
        regex=True,
    )
    gdf = gdf[risk_mask].copy()
    if gdf.empty:
        print(f" -> {source_name} contains no recognized ERO risk polygons.")
        return empty_ero_gdf()

    gdf["dataType"] = "ERO"
    gdf["ero_source"] = source_name
    return gdf[
        ["dataType", "OUTLOOK", "ero_source", "geometry"]
    ].copy()


def extract_wpc_day1_download_url(raw_html, section_name, stop_name=None):
    """Find WPC's Day-1 link within one GIS-download section."""
    marker = re.search(re.escape(section_name), raw_html, re.IGNORECASE)
    if not marker:
        return None

    start = marker.end()
    end = len(raw_html)
    if stop_name:
        stop = re.search(
            re.escape(stop_name),
            raw_html[start:],
            re.IGNORECASE,
        )
        if stop:
            end = start + stop.start()

    section = raw_html[start:end]
    for href, body in re.findall(
        r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
        section,
        re.IGNORECASE | re.DOTALL,
    ):
        label = re.sub(r"<[^>]+>", "", body)
        label = re.sub(r"\s+", "", unescape(label)).lower()
        if label == "day1":
            return urljoin(ERO_PAGE_URL, unescape(href))
    return None


def wpc_page_advertises_ero_risk(raw_html):
    """Return True when WPC's rendered Day-1 page advertises a risk category."""
    text = html_to_product_text(raw_html).upper()
    return any(
        token in text
        for token in (
            "MARGINAL (AT LEAST 5%)",
            "SLIGHT (AT LEAST 15%)",
            "MODERATE (AT LEAST 40%)",
            "HIGH (AT LEAST 70%)",
        )
    )


def read_zipped_shapefile(content):
    with tempfile.TemporaryDirectory() as temporary_dir:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            archive.extractall(temporary_dir)
        shapefiles = []
        for root, _, files in os.walk(temporary_dir):
            for name in files:
                if name.lower().endswith(".shp"):
                    shapefiles.append(os.path.join(root, name))
        if not shapefiles:
            raise ValueError("WPC shapefile ZIP contains no .shp member")
        return gpd.read_file(shapefiles[0])


def fetch_wpc_day1_downloads():
    """Try WPC's own Day-1 GeoJSON and shapefile GIS downloads."""
    page = requests.get(
        f"{ERO_PAGE_URL}?t={time.time_ns()}",
        headers=NO_CACHE_HEADERS,
        timeout=30,
    )
    page.raise_for_status()

    advertised_risk = wpc_page_advertises_ero_risk(page.text)
    candidates = [
        (
            "wpc_direct_geojson",
            extract_wpc_day1_download_url(
                page.text, "GeoJSON", "ArcGIS REST Service"
            ),
        ),
        (
            "wpc_direct_shapefile",
            extract_wpc_day1_download_url(
                page.text, "Shapefile", "GeoJSON"
            ),
        ),
    ]

    available = [(name, url) for name, url in candidates if url]
    if not available:
        raise ValueError("WPC ERO page exposed no Day-1 GIS download links")

    successful_empty = 0
    failures = []
    for source_name, source_url in available:
        try:
            separator = "&" if "?" in source_url else "?"
            response = requests.get(
                f"{source_url}{separator}t={time.time_ns()}",
                headers=NO_CACHE_HEADERS,
                timeout=30,
            )
            response.raise_for_status()

            if source_name.endswith("shapefile"):
                raw = read_zipped_shapefile(response.content)
            else:
                raw = gpd.read_file(response.text, driver="GeoJSON")

            normalized = normalize_ero_gdf(raw, source_name)
            print(
                f" -> WPC Day-1 fallback {source_name}: {source_url}; "
                f"{len(normalized)} risk polygon(s)."
            )
            if not normalized.empty:
                return normalized

            successful_empty += 1
        except Exception as error:
            failures.append(f"{source_name}: {error}")
            print(f" -> {source_name} fallback failed: {error}")

    if advertised_risk:
        # The rendered WPC page says a risk exists, so empty/missing GIS
        # downloads are a publication lag, not an authoritative No Area.
        detail = "; ".join(failures) if failures else "GIS downloads were empty"
        raise ValueError(
            "WPC Day-1 page advertises active ERO risk but downloadable GIS "
            f"polygons are unavailable ({detail})"
        )

    if successful_empty and not failures:
        return empty_ero_gdf()

    raise ValueError(
        "WPC Day-1 GIS downloads could not be authoritatively resolved: "
        + "; ".join(failures)
    )



ERO_RISK_LABELS = {
    "MARGINAL": "Marginal (At Least 5%)",
    "SLIGHT": "Slight (At Least 15%)",
    "MODERATE": "Moderate (At Least 40%)",
    "HIGH": "High (At Least 70%)",
}

COMPASS_BEARINGS = {
    "N": 0.0, "NNE": 22.5, "NE": 45.0, "ENE": 67.5,
    "E": 90.0, "ESE": 112.5, "SE": 135.0, "SSE": 157.5,
    "S": 180.0, "SSW": 202.5, "SW": 225.0, "WSW": 247.5,
    "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5,
}

# WPC threat-point text still uses the legacy XFL identifier for Flagler
# County Airport. FAA now identifies the same Palm Coast field as FIN/KFIN.
WPC_STATION_ALIASES = {
    "XFL": "KFIN",
}


def station_lookup_from_awc():
    """Load the once-daily AWC station catalog and index common identifiers."""
    response = requests.get(
        AWC_STATIONS_URL,
        headers=NO_CACHE_HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    try:
        payload = gzip.decompress(response.content)
    except OSError:
        payload = response.content

    rows = json.loads(payload.decode("utf-8"))
    if isinstance(rows, dict):
        rows = (
            rows.get("features")
            or rows.get("stations")
            or rows.get("data")
            or []
        )

    lookup = {}
    for row in rows:
        if not isinstance(row, dict):
            continue

        properties = row.get("properties") if isinstance(
            row.get("properties"), dict
        ) else row

        geometry = row.get("geometry") if isinstance(
            row.get("geometry"), dict
        ) else None

        lat = properties.get("lat", properties.get("latitude"))
        lon = properties.get("lon", properties.get("longitude"))

        if (lat is None or lon is None) and geometry:
            coordinates = geometry.get("coordinates")
            if isinstance(coordinates, list) and len(coordinates) >= 2:
                lon, lat = coordinates[:2]

        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            continue

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue

        identifiers = {
            properties.get("icaoId"),
            properties.get("stationId"),
            properties.get("iataId"),
            properties.get("faaId"),
            properties.get("id"),
        }

        for identifier in identifiers:
            if not identifier:
                continue
            key = str(identifier).upper().strip()
            if key:
                lookup.setdefault(key, (lon, lat))
                # WPC/SPC threat-area products frequently use the domestic
                # three-character identifier while AWC stores the ICAO K-code.
                if len(key) == 4 and key.startswith("K"):
                    lookup.setdefault(key[1:], (lon, lat))

    if len(lookup) < 500:
        raise ValueError(
            f"AWC station catalog unexpectedly small ({len(lookup)} IDs)"
        )

    return lookup


def resolve_threat_station(identifier, lookup):
    key = identifier.upper().strip()
    candidates = [key]
    alias = WPC_STATION_ALIASES.get(key)
    if alias:
        candidates.insert(0, alias)
    if len(key) == 3:
        candidates.append("K" + key)

    for candidate in candidates:
        if candidate in lookup:
            return lookup[candidate]

    raise ValueError(f"Unresolved WPC threat-area station: {identifier}")


def destination_point(lon, lat, bearing_degrees, statute_miles):
    """Great-circle destination using WPC/NWS outlook distances in statute miles."""
    radius_km = 6371.0088
    distance_km = float(statute_miles) * 1.609344
    angular = distance_km / radius_km
    bearing = math.radians(float(bearing_degrees))
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)

    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular)
        + math.cos(lat1) * math.sin(angular) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular) * math.cos(lat1),
        math.cos(angular) - math.sin(lat1) * math.sin(lat2),
    )
    lon2 = (lon2 + math.pi) % (2 * math.pi) - math.pi
    return (math.degrees(lon2), math.degrees(lat2))


def parse_threat_vertices(raw_line, station_lookup):
    tokens = re.findall(r"[A-Z0-9]+|-", raw_line.upper())
    coordinates = []
    index = 0

    while index < len(tokens):
        token = tokens[index]

        if token.isdigit():
            if index + 2 >= len(tokens):
                raise ValueError(
                    f"Incomplete distance/direction/station triplet near {token}"
                )
            distance = int(token)
            direction = tokens[index + 1]
            station = tokens[index + 2]
            lon, lat = resolve_threat_station(station, station_lookup)

            if distance == 0 and direction == "-":
                coordinate = (lon, lat)
            else:
                if direction not in COMPASS_BEARINGS:
                    raise ValueError(
                        f"Unknown WPC threat-area direction: {direction}"
                    )
                coordinate = destination_point(
                    lon,
                    lat,
                    COMPASS_BEARINGS[direction],
                    distance,
                )
            index += 3
        else:
            if token == "-":
                raise ValueError("Unexpected standalone '-' in threat-area line")
            coordinate = resolve_threat_station(token, station_lookup)
            index += 1

        if not coordinates or coordinate != coordinates[-1]:
            coordinates.append(coordinate)

    if len(coordinates) >= 2 and coordinates[0] == coordinates[-1]:
        coordinates.pop()

    if len(set(coordinates)) < 3:
        raise ValueError("Threat-area contour has fewer than three unique vertices")

    return coordinates


def parse_ero_points_validity(text):
    match = re.search(
        r"Valid\s+(\d{1,2})Z\s+\w+\s+(\w+)\s+(\d{1,2})\s+(\d{4})"
        r"\s*-\s*(\d{1,2})Z\s+\w+\s+(\w+)\s+(\d{1,2})\s+(\d{4})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None, None

    start = datetime.strptime(
        f"{match.group(1)} {match.group(2)} {match.group(3)} {match.group(4)}",
        "%H %b %d %Y",
    ).replace(tzinfo=timezone.utc)
    end = datetime.strptime(
        f"{match.group(5)} {match.group(6)} {match.group(7)} {match.group(8)}",
        "%H %b %d %Y",
    ).replace(tzinfo=timezone.utc)
    return start, end


def fetch_wpc_ero_threat_text():
    """Build ERO polygons from WPC's current first-party 94epoints text."""
    response = requests.get(
        f"{ERO_POINTS_URL}?t={time.time_ns()}",
        headers=NO_CACHE_HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    text = response.text.replace("\r", "")

    start, end = parse_ero_points_validity(text)
    now = utc_now()
    if start is None or end is None:
        raise ValueError("WPC 94epoints validity line could not be parsed")
    if now < start - timedelta(minutes=15) or now >= end:
        raise ValueError(
            f"WPC 94epoints is not current: valid {start.isoformat()} "
            f"through {end.isoformat()}"
        )

    heading = re.compile(
        r"(?P<risk>MARGINAL|SLIGHT|MODERATE|HIGH)\s+RISK\s+OF\s+"
        r"RAINFALL\s+EXCEEDING\s+FFG\s+TO\s+THE\s+RIGHT\s+OF\s+A\s+LINE\s+FROM",
        re.IGNORECASE,
    )
    matches = list(heading.finditer(text))

    no_area = re.search(
        r"(?:"
        r"NO\s+(?:ORGANIZED\s+)?AREAS?.*"
        r"(?:EXCEED|EXCESSIVE|FLASH\s+FLOOD)"
        r"|"
        r"RAINFALL\s+IS\s+NOT\s+EXPECTED\s+TO\s+EXCEED\s+"
        r"FLASH\s+FLOOD\s+GUIDANCE(?:\s+VALUES)?\s+"
        r"THIS\s+FORECAST\s+PERIOD"
        r")",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if not matches:
        if no_area:
            print(
                " -> WPC 94epoints explicitly contains no Day-1 risk areas."
            )
            return empty_ero_gdf()
        raise ValueError(
            "Current WPC 94epoints contains neither risk contours nor an "
            "explicit No Area statement"
        )

    station_lookup = station_lookup_from_awc()
    features = []

    for position, match in enumerate(matches):
        section_start = match.end()
        section_end = (
            matches[position + 1].start()
            if position + 1 < len(matches)
            else len(text)
        )
        raw_line = text[section_start:section_end]
        raw_line = re.sub(r"\s+", " ", raw_line).strip(" .\n\t")
        coordinates = parse_threat_vertices(raw_line, station_lookup)

        polygon = Polygon(coordinates)
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if polygon.is_empty or not polygon.is_valid:
            raise ValueError(
                f"{match.group('risk')} threat contour is invalid"
            )

        minx, miny, maxx, maxy = polygon.bounds
        if not (
            -130 <= minx <= -60
            and -130 <= maxx <= -60
            and 20 <= miny <= 55
            and 20 <= maxy <= 55
        ):
            raise ValueError(
                f"{match.group('risk')} threat contour has implausible CONUS bounds "
                f"{polygon.bounds}"
            )

        risk = match.group("risk").upper()
        features.append(
            {
                "dataType": "ERO",
                "OUTLOOK": ERO_RISK_LABELS[risk],
                "ero_source": "wpc_94epoints",
                "ero_valid_start_utc": start.isoformat(),
                "ero_valid_end_utc": end.isoformat(),
                "geometry": polygon,
            }
        )

    result = gpd.GeoDataFrame(features, geometry="geometry", crs="EPSG:4326")
    print(
        " -> WPC 94epoints fallback built "
        f"{len(result)} authoritative risk polygon(s); "
        f"valid {start.isoformat()} through {end.isoformat()}."
    )
    return result


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


def decode_wpc_latlon_token(token, context_text=""):
    """Decode a compact WPC LAT...LON token into (longitude, latitude).

    WPC/NWS compact coordinates normally devote the first four digits to
    latitude.  Longitudes west of 100 degrees are often encoded with the
    leading ``1`` suppressed, for example::

        34470879 -> 34.47N, 108.79W
        37502223 -> 37.50N, 122.23W

    Longitudes below 100W remain direct, for example::

        34198699 -> 34.19N, 86.99W

    Explicit five-or-more-digit longitude fields (such as 10043) are decoded
    directly.  Alaska and Hawaii require conservative context checks because
    their suppressed values overlap Puerto Rico and western Atlantic values.
    """
    token = token.strip()
    if not re.fullmatch(r"\d{8,10}", token):
        return None

    latitude = int(token[:4]) / 100.0
    lon_raw = token[4:]
    context_upper = context_text.upper()

    if not (0.0 <= latitude <= 90.0):
        return None

    if len(lon_raw) >= 5:
        longitude_west = int(lon_raw) / 100.0
    elif len(lon_raw) == 4:
        longitude_west = int(lon_raw) / 100.0

        # CONUS west of 100W is commonly encoded as 00.xx-39.xx after the
        # leading 100-degree component is suppressed.
        if longitude_west < 40.0:
            longitude_west += 100.0
        else:
            alaska_words = (
                "ALASKA",
                "ALEUTIAN",
                "KODIAK",
                "KENAI",
                "FAIRBANKS",
                "ANCHORAGE",
            )
            hawaii_words = (
                "HAWAII",
                "HAWAIIAN",
                "KAUAI",
                "OAHU",
                "MAUI",
                "MOLOKAI",
                "LANAI",
                "BIG ISLAND",
            )

            if 40.0 <= longitude_west < 80.0 and (
                latitude >= 48.0
                or any(word in context_upper for word in alaska_words)
            ):
                longitude_west += 100.0
            elif 50.0 <= longitude_west < 70.0 and any(
                word in context_upper for word in hawaii_words
            ):
                longitude_west += 100.0
    else:
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
        coordinate = decode_wpc_latlon_token(token, product_text)
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
            f"{ERO_REST_URL}?where=1=1&outFields=*&f=geojson"
            f"&time_buster={time.time_ns()}",
            headers=NO_CACHE_HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        gdf = gpd.read_file(response.text, driver="GeoJSON")
        gdf = normalize_ero_gdf(gdf, "noaa_arcgis")

        if gdf is not None and not gdf.empty:
            print(f" -> NOAA ArcGIS Day-1 ERO returned {len(gdf)} risk polygon(s).")
            return gdf

        # An empty ArcGIS layer is not by itself proof of an authoritative
        # "No Area" issuance. The map service can lag or briefly clear while
        # WPC's own ERO product has already updated. Confirm against the direct
        # GeoJSON advertised by WPC before clearing the retained ERO.
        print(
            " -> NOAA ArcGIS Day-1 ERO returned no risk polygons; "
            "checking WPC's direct Day-1 GeoJSON before declaring No Area."
        )
        try:
            direct = fetch_wpc_day1_downloads()
        except Exception as fallback_error:
            print(
                " -> Direct WPC Day-1 GIS fallback unavailable: "
                f"{fallback_error}. Trying WPC 94epoints."
            )
            direct = None

        if direct is not None and not direct.empty:
            return direct

        # The direct GIS packages can lag independently of the forecast.
        # WPC's 94epoints text is a first-party, issuance-stamped threat-area
        # representation. Use it before interpreting empty GIS as No Area.
        try:
            threat = fetch_wpc_ero_threat_text()
        except Exception as threat_error:
            print(
                " -> WPC 94epoints fallback unavailable: "
                f"{threat_error}. Retaining the prior verified ERO."
            )
            return None

        if threat is not None and not threat.empty:
            return threat

        print(
            " -> WPC 94epoints confirms no Day-1 risk areas; "
            "treating this as an authoritative No Area update."
        )
        return empty_ero_gdf()
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

    # The WPC current-MPD webpage can occasionally retain a discussion briefly
    # after its official valid end time. Treat the bulletin's VALID period as
    # authoritative so an upstream cleanup delay cannot leave an expired MPD on
    # the dashboard.
    processing_time = utc_now()
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

        if valid_end <= processing_time:
            print(
                f" -> MPD {mpd_num:04d} expired at "
                f"{valid_end.strftime('%Y-%m-%d %H:%MZ')}; "
                "skipping despite its presence on the WPC current-MPD page."
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

        issue_str = valid_start.strftime("%HZ %b %d %Y")
        expire_str = valid_end.strftime("%HZ %b %d %Y")
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
    print(f"Running fetch_wpc.py version: {SCRIPT_VERSION}")
    final_gdfs = []

    ero_gdf = fetch_and_process_ero()
    ero_authoritative = ero_gdf is not None
    if ero_gdf is not None and not ero_gdf.empty:
        final_gdfs.append(ero_gdf)

    mpd_gdf = fetch_and_process_mpds()
    if mpd_gdf is not None and not mpd_gdf.empty:
        final_gdfs.append(mpd_gdf)

    if not final_gdfs:
        # The workflow restores the last published pages-live snapshot before
        # running this script. If all fresh sources are empty/unavailable, do
        # not blindly republish an expired MPD from that restored snapshot.
        # Retain non-MPD features as last-known-good data, but prune MPDs whose
        # authoritative bulletin valid_end_utc has passed.
        if os.path.exists(OUTPUT_FILENAME):
            try:
                retained_gdf = gpd.read_file(OUTPUT_FILENAME)
                processing_time = utc_now()
                keep_rows = []

                removed_ero = 0
                removed_mpd = 0

                for _, row in retained_gdf.iterrows():
                    data_type = str(row.get("dataType", "")).upper()

                    # A successful empty Day 1 ERO response means WPC has
                    # explicitly issued "No Area". Clear any retained ERO
                    # polygons from the previous issuance. Only preserve the
                    # old ERO when the source fetch itself failed.
                    if data_type == "ERO" and ero_authoritative:
                        keep_rows.append(False)
                        removed_ero += 1
                        continue

                    if data_type != "MPD":
                        keep_rows.append(True)
                        continue

                    valid_end_raw = row.get("valid_end_utc", "")
                    try:
                        valid_end = pd.to_datetime(
                            valid_end_raw, utc=True, errors="raise"
                        ).to_pydatetime()
                    except Exception:
                        # Unknown expiration is safer to retain than to delete.
                        keep_rows.append(True)
                        continue

                    keep_mpd = valid_end > processing_time
                    keep_rows.append(keep_mpd)
                    if not keep_mpd:
                        removed_mpd += 1

                pruned_gdf = retained_gdf.loc[keep_rows].copy()
                removed = len(retained_gdf) - len(pruned_gdf)

                if removed > 0:
                    temporary_output = f"{OUTPUT_FILENAME}.tmp"
                    try:
                        if pruned_gdf.empty:
                            with open(temporary_output, "w", encoding="utf-8") as handle:
                                json.dump(
                                    {"type": "FeatureCollection", "features": []},
                                    handle,
                                )
                        else:
                            pruned_gdf.to_file(temporary_output, driver="GeoJSON")
                        os.replace(temporary_output, OUTPUT_FILENAME)
                    finally:
                        if os.path.exists(temporary_output):
                            os.remove(temporary_output)

                    print(
                        "No fresh WPC features available; pruned retained snapshot: "
                        f"{removed_ero} obsolete ERO feature(s), "
                        f"{removed_mpd} expired MPD feature(s)."
                    )
                else:
                    print(
                        "No fresh WPC features available; retained existing "
                        "non-expired dashboard snapshot."
                    )
            except Exception as error:
                print(
                    "No fresh WPC features available and retained-snapshot "
                    f"pruning failed: {error}"
                )
        else:
            print("No valid WPC data processed and no retained snapshot exists.")
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
