"""BestTime.app API client for real-time live foot traffic / busyness."""

import re
from datetime import datetime

from app.clients.base import BaseAPIClient
from app.config import get_settings


def _normalize_name(s: str) -> str:
    """Normalize venue name for fuzzy matching (lowercase, collapse spaces)."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.lower().strip())


def _name_match(a: str, b: str) -> bool:
    """Check if two venue names likely refer to the same place."""
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return False
    return na in nb or nb in na


def _hour_to_12h(h: int) -> str:
    """Convert 24h hour to 12h format (e.g. 14 -> '2 PM')."""
    if h is None:
        return ""
    h = int(h)
    if h == 0:
        return "12 AM"
    if h == 12:
        return "12 PM"
    return f"{h % 12} {'AM' if h < 12 else 'PM'}"


def _extract_busy(data: dict) -> float | None:
    """Extract busyness % from BestTime response."""
    for key in ("intensity", "intensity_nr", "busy", "live_busyness", "current_busy"):
        v = data.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    day_info = data.get("day_info", {})
    if isinstance(day_info, dict):
        v = day_info.get("day_mean") or day_info.get("day_max")
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    if "foot_traffic_percentage" in data:
        arr = data["foot_traffic_percentage"]
        if isinstance(arr, list) and arr:
            hour = datetime.utcnow().hour
            return float(arr[min(hour, len(arr) - 1)])
    return None


def _busy_to_status(busy_pct: float) -> str:
    if busy_pct >= 70:
        return "lively"
    if busy_pct >= 40:
        return "moderate"
    if busy_pct >= 10:
        return "quiet"
    return "very_quiet"


class BestTimeClient(BaseAPIClient):
    """Client for BestTime.app live foot traffic API."""

    BASE_URL = "https://besttime.app/api/v1"

    def __init__(self):
        super().__init__()
        self.api_key = get_settings().besttime_api_key

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def filter_venues_by_location(
        self,
        lat: float,
        lng: float,
        radius: int = 3000,
        limit: int = 50,
    ) -> list[dict]:
        """
        Get venues already forecasted in our account near a location.
        Per BestTime docs: round coords to 2 decimals for cache hits.
        Returns list of {venue_id, name, address, ...}.
        """
        if not self.is_configured:
            return []
        lat_r = round(lat, 2)
        lng_r = round(lng, 2)
        params = {
            "api_key_private": self.api_key,
            "lat": lat_r,
            "lng": lng_r,
            "radius": radius,
            "limit": limit,
        }
        try:
            resp = await self._get(f"{self.BASE_URL}/venues/filter", params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []
        return data.get("venues", []) if isinstance(data.get("venues"), list) else []

    def _build_address_variants(self, venue_name: str, venue_address: str) -> list[str]:
        """Build address variants for better geocoding (BestTime needs precise enough address)."""
        variants = []
        addr = (venue_address or "").strip()
        name = (venue_name or "").strip()
        if name and addr:
            if name.lower() not in addr.lower():
                variants.append(f"{name}, {addr}")
            variants.append(addr)
        elif addr:
            variants.append(addr)
        if name:
            if not variants:
                variants.append(name)
            if "dubai" not in addr.lower() and "uae" not in addr.lower() and "u.a.e" not in addr.lower():
                variants.append(f"{name}, Dubai, UAE")
        return variants or [""]

    async def get_live_busyness(
        self,
        venue_name: str,
        venue_address: str,
        venue_id: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
    ) -> dict | None:
        """
        Get real-time live busyness and forecast analysis for a venue.
        Per BestTime docs: use venue_id when available (faster, cheaper).
        Flow: 1) venue_id if provided 2) Venue Filter by lat/lng to find venue_id
        3) forecasts with name+address (try address variants for geocoding).
        """
        if not self.is_configured:
            return None

        resolved_venue_id = venue_id

        # Try Venue Filter when we have lat/lng but no venue_id (find existing forecast)
        if not resolved_venue_id and lat is not None and lng is not None and venue_name:
            filtered = await self.filter_venues_by_location(lat, lng, radius=3000, limit=30)
            for v in filtered:
                vname = v.get("name") or v.get("venue_name") or ""
                if _name_match(venue_name, vname):
                    resolved_venue_id = v.get("venue_id")
                    break

        # Try live/forecasts with venue_id first (fast path)
        if resolved_venue_id:
            result = await self._fetch_busyness(venue_id=resolved_venue_id)
            if result:
                return result

        # Fallback: use venue_name + venue_address (creates forecast, geocoding)
        if not venue_name:
            return None

        address_variants = self._build_address_variants(venue_name, venue_address or "")
        if not address_variants or address_variants == [""]:
            address_variants = [venue_name]
        for addr in address_variants:
            if not addr:
                continue
            result = await self._fetch_busyness(venue_name=venue_name, venue_address=addr)
            if result:
                return result

        return None

    async def _fetch_busyness(
        self,
        venue_id: str | None = None,
        venue_name: str | None = None,
        venue_address: str | None = None,
    ) -> dict | None:
        """Fetch busyness from live or forecasts endpoint."""
        if venue_id:
            params = {"api_key_private": self.api_key, "venue_id": venue_id}
        elif venue_name and venue_address:
            params = {
                "api_key_private": self.api_key,
                "venue_name": venue_name,
                "venue_address": venue_address,
            }
        else:
            return None

        for endpoint in ("forecasts/live", "forecasts"):
            try:
                resp = await self._post(f"{self.BASE_URL}/{endpoint}", params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                continue

            if data.get("status") == "Error":
                continue

            analysis = data.get("analysis")
            busy_pct = None
            if isinstance(analysis, dict):
                busy_pct = analysis.get("venue_live_busyness") or analysis.get("venue_forecasted_busyness")
            busy_pct = busy_pct or _extract_busy(data) or _extract_busy(analysis or {})
            if busy_pct is None:
                continue

            busy_pct = min(100, max(0, float(busy_pct)))
            result: dict = {
                "live_busyness": round(busy_pct, 1),
                "status": _busy_to_status(busy_pct),
                "is_lively": busy_pct >= 50,
                "busy_hours": [],
                "peak_hours": [],
                "quiet_hours": [],
                "day_mean": None,
                "day_raw": [],
                "venue_id": (data.get("venue_info") or {}).get("venue_id"),
            }

            venue_info = data.get("venue_info") or {}
            if isinstance(venue_info, dict):
                result["venue_rating"] = venue_info.get("rating")
                result["venue_reviews"] = venue_info.get("reviews")
                result["venue_price_level"] = venue_info.get("price_level")

            if isinstance(analysis, list):
                day_int = datetime.now().weekday()
                if 0 <= day_int < len(analysis):
                    day_data = analysis[day_int]
                    day_info = day_data.get("day_info") or {}
                    result["day_mean"] = day_info.get("day_mean")
                    result["busy_hours"] = day_data.get("busy_hours") or []
                    result["quiet_hours"] = day_data.get("quiet_hours") or []
                    result["day_raw"] = day_data.get("day_raw") or []
                    peaks = day_data.get("peak_hours") or []
                    result["peak_hours"] = [
                        {
                            "peak_start": p.get("peak_start"),
                            "peak_max": p.get("peak_max"),
                            "peak_end": p.get("peak_end"),
                            "peak_start_12": _hour_to_12h(p["peak_start"]) if p.get("peak_start") is not None else None,
                            "peak_max_12": _hour_to_12h(p["peak_max"]) if p.get("peak_max") is not None else None,
                            "peak_end_12": _hour_to_12h(p["peak_end"]) if p.get("peak_end") is not None else None,
                        }
                        for p in peaks
                        if isinstance(p, dict)
                    ]
            elif isinstance(analysis, dict) and "day_info" in analysis:
                day_info = analysis.get("day_info") or {}
                result["day_mean"] = day_info.get("day_mean")
                result["busy_hours"] = analysis.get("busy_hours") or []
                result["quiet_hours"] = analysis.get("quiet_hours") or []

            # Live endpoint returns dict analysis (no day_raw). Fetch full forecast for chart.
            if not result.get("day_raw") and result.get("venue_id"):
                result = await self._merge_day_raw(result) or result

            return result

        return None

    async def _merge_day_raw(self, result: dict) -> dict | None:
        """Fetch forecasts with venue_id to get day_raw for the hourly chart."""
        venue_id = result.get("venue_id")
        if not venue_id:
            return result
        try:
            resp = await self._post(
                f"{self.BASE_URL}/forecasts",
                params={"api_key_private": self.api_key, "venue_id": venue_id},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return result
        if data.get("status") == "Error":
            return result
        analysis = data.get("analysis")
        if isinstance(analysis, list):
            day_int = datetime.now().weekday()
            if 0 <= day_int < len(analysis):
                day_data = analysis[day_int]
                result["day_raw"] = day_data.get("day_raw") or []
                if not result.get("day_mean") and day_data.get("day_info"):
                    result["day_mean"] = day_data["day_info"].get("day_mean")
                if not result.get("busy_hours"):
                    result["busy_hours"] = day_data.get("busy_hours") or []
                if not result.get("quiet_hours"):
                    result["quiet_hours"] = day_data.get("quiet_hours") or []
        return result
