
"""GPS utilities for location tagging."""

import logging
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

logger = logging.getLogger(__name__)

# Coordinates for known locations
# Format: "Name": (Lat, Lon)
LOCATIONS = {
    "Tokyo_Asakusabashi": (35.697, 139.782),  # Taito, Tokyo
    "Tokyo_HigashiIkebukuro": (35.728, 139.719),  # Toshima, Tokyo
    "Numazu": (35.100, 138.860),  # Numazu, Shizuoka
    "Tsukuba": (36.083, 140.111),  # Tsukuba, Ibaraki
}

# Mapping internal keys to (Classroom, Venue) names
LOCATION_MAPPING = {
    "Tokyo_Asakusabashi": ("東京教室", "浅草橋会場"),
    "Tokyo_HigashiIkebukuro": ("東京教室", "東池袋会場"),
    "Numazu": ("沼津教室", "沼津会場"),
    "Tsukuba": ("つくば教室", "つくば会場"),
}

@dataclass
class LocationTag:
    classroom: str
    venue: str

def get_exif_data(image_path: Path):
    """Returns a dictionary from the exif data of an PIL Image item."""
    try:
        image = Image.open(image_path)
        exif_data = {}
        info = image._getexif()
        if info:
            for tag, value in info.items():
                decoded = TAGS.get(tag, tag)
                if decoded == "GPSInfo":
                    gps_data = {}
                    for t in value:
                        sub_decoded = GPSTAGS.get(t, t)
                        gps_data[sub_decoded] = value[t]
                    exif_data[decoded] = gps_data
                else:
                    exif_data[decoded] = value
        return exif_data
    except Exception as e:
        logger.debug(f"Failed to read EXIF from {image_path}: {e}")
        return None

def _convert_to_degrees(value):
    """Helper function to convert the GPS coordinates to degrees."""
    d = float(value[0])
    m = float(value[1])
    s = float(value[2])
    return d + (m / 60.0) + (s / 3600.0)

def get_lat_lon(exif_data):
    """Returns the latitude and longitude, if available, from the provided exif_data."""
    if not exif_data or "GPSInfo" not in exif_data:
        return None, None

    gps_info = exif_data["GPSInfo"]

    # Check for required tags
    required_tags = ["GPSLatitude", "GPSLatitudeRef", "GPSLongitude", "GPSLongitudeRef"]
    if not all(tag in gps_info for tag in required_tags):
        return None, None

    try:
        lat = _convert_to_degrees(gps_info["GPSLatitude"])
        lon = _convert_to_degrees(gps_info["GPSLongitude"])

        if gps_info["GPSLatitudeRef"] != "N":
            lat = -lat
        if gps_info["GPSLongitudeRef"] != "E":
            lon = -lon

        return lat, lon
    except Exception as e:
        logger.debug(f"Error converting GPS data: {e}")
        return None, None

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate the great circle distance between two points in km."""
    # Convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

    # Haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    r = 6371 # Radius of earth in kilometers
    return c * r

def identify_location(lat, lon, threshold_km=50.0) -> LocationTag | None:
    """Identify the nearest classroom/venue based on coordinates."""
    nearest_loc = None
    min_dist = float("inf")

    for key, (loc_lat, loc_lon) in LOCATIONS.items():
        dist = haversine_distance(lat, lon, loc_lat, loc_lon)
        if dist < min_dist:
            min_dist = dist
            nearest_loc = key

    if nearest_loc and min_dist <= threshold_km:
        classroom, venue = LOCATION_MAPPING[nearest_loc]
        return LocationTag(classroom=classroom, venue=venue)

    return None

def get_location_for_file(image_path: Path) -> LocationTag | None:
    """High-level function to get location tag from an image file."""
    exif = get_exif_data(image_path)
    lat, lon = get_lat_lon(exif)

    if lat is not None and lon is not None:
        return identify_location(lat, lon)

    return None
