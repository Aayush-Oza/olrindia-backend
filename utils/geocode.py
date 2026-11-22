import requests

def pincode_to_latlong(pincode: str) -> tuple[float, float] | tuple[None, None]:
    """
    Convert an Indian pincode to lat/lng using Nominatim (OpenStreetMap).
    Completely free, no API key needed, accurate for Indian pincodes.
    """
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "postalcode": pincode,
                "country":    "India",
                "format":     "json",
                "limit":      1,
            },
            headers={"User-Agent": "OLR-India-App"},  # just a name, anything works
            timeout=5,
        )
        results = response.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])

    except Exception as e:
        from flask import current_app
        current_app.logger.warning(f"Geocoding failed for pincode {pincode}: {e}")

    return None, None