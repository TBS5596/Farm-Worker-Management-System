"""Geofence checks for attendance coordinates.

The first release stored latitude and longitude and never looked at them. A
stored coordinate is not a verification; comparing it to the farm's location is.
"""

from __future__ import annotations

from geopy.distance import geodesic
from geopy.point import Point

from models import Setting


def _setting(key: str, default: str = "") -> str:
    row = Setting.query.filter_by(key=key).first()
    return row.value if row and row.value else default


def normalize_coordinates(lat_raw, lon_raw) -> tuple[float | None, float | None]:
    """Validate and normalise coordinates supplied by the clock-in page."""
    if lat_raw in (None, "") or lon_raw in (None, ""):
        return None, None
    try:
        point = Point(float(lat_raw), float(lon_raw))
        return float(point.latitude), float(point.longitude)
    except Exception:
        return None, None


def farm_centre() -> tuple[float | None, float | None]:
    lat, lon = normalize_coordinates(_setting("farm_latitude"), _setting("farm_longitude"))
    return lat, lon


def radius_metres() -> float:
    try:
        return max(10.0, float(_setting("geofence_radius_m", "500")))
    except ValueError:
        return 500.0


def is_enforced() -> bool:
    return (_setting("geofence_enforce", "off") or "off").strip().lower() in ("on", "1", "true", "yes")


def evaluate(lat: float | None, lon: float | None) -> dict:
    """Compare a clock-in position against the configured farm centre.

    Returns configured / has_position / within / distance_m / enforce, so the
    caller can distinguish "outside the fence" from "no fence set up" and
    "worker sent no position" - three situations that deserve different
    handling.

    Example with the farm at -15.4067, 28.2871 and a 500 m radius:
        evaluate(-15.4069, 28.2873)  -> within True,  distance_m 30.1
        evaluate(-15.4340, 28.2871)  -> within False, distance_m 3036.4
        evaluate(None, None)         -> has_position False, within None

    The position is self-reported by the worker's browser, so this is
    corroboration rather than proof: it catches a punch from the wrong side of
    the district, not a determined spoof. Hence enforcement is off by default -
    run in recording mode first and look at real distances before choosing a
    radius.
    """
    farm_lat, farm_lon = farm_centre()
    result = {
        "configured": farm_lat is not None and farm_lon is not None,
        "has_position": lat is not None and lon is not None,
        "within": None,
        "distance_m": None,
        "radius_m": radius_metres(),
        "enforce": is_enforced(),
    }
    if not result["configured"] or not result["has_position"]:
        return result

    distance = geodesic((farm_lat, farm_lon), (lat, lon)).meters
    result["distance_m"] = round(float(distance), 1)
    result["within"] = bool(distance <= result["radius_m"])
    return result
