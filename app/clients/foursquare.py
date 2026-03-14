"""Foursquare Places API client."""

from app.clients.base import BaseAPIClient
from app.config import get_settings
from app.models.schemas import Place, PlaceDetail


# Map our type to Foursquare query terms
TYPE_MAP = {
    "restaurant": "restaurant",
    "cafe": "cafe",
    "bar": "bar",
    "bakery": "bakery",
    "food": "restaurant",
}


class FoursquareClient(BaseAPIClient):
    """Client for Foursquare Places API v3."""

    BASE_URL = "https://api.foursquare.com/v3/places"

    def __init__(self):
        super().__init__()
        self.api_key = get_settings().foursquare_api_key

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        # Foursquare v3 uses raw API key; newer Places API uses Bearer
        auth = self.api_key if self.api_key.startswith("Bearer ") else self.api_key
        return {
            "Authorization": auth,
            "Accept": "application/json",
        }

    async def search_nearby(
        self,
        lat: float,
        lng: float,
        radius: int,
        place_type: str = "restaurant",
        max_results: int = 20,
    ) -> list[Place]:
        """Search for places near a location."""
        if not self.is_configured:
            return []

        query = TYPE_MAP.get(place_type.lower(), "restaurant")
        url = f"{self.BASE_URL}/search"
        params = {
            "ll": f"{lat},{lng}",
            "radius": min(radius, 100000),
            "limit": min(max_results, 50),
            "query": query,
            "fields": "name,location,geocodes,rating,categories,photos",
        }

        try:
            resp = await self._get(url, params=params, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        places = []
        for r in data.get("results", []):
            fsq_id = r.get("fsq_id", "")
            if not fsq_id:
                continue
            loc = r.get("geocodes", {}).get("main", {})
            photo_url = None
            photos = r.get("photos") or []
            if photos:
                ph = photos[0]
                prefix = ph.get("prefix")
                suffix = ph.get("suffix")
                if prefix and suffix:
                    photo_url = f"{prefix}original{suffix}"
            places.append(
                Place(
                    id=f"foursquare:{fsq_id}",
                    name=r.get("name", "Unknown"),
                    address=r.get("location", {}).get("formatted_address"),
                    lat=loc.get("latitude"),
                    lng=loc.get("longitude"),
                    rating=r.get("rating"),
                    types=[c.get("name", "") for c in r.get("categories", [])],
                    source="foursquare",
                    photo_url=photo_url,
                )
            )
        return places

    async def search_text(
        self,
        query: str,
        lat: float,
        lng: float,
        max_results: int = 20,
    ) -> list[Place]:
        """Search for places by text query near a location."""
        if not self.is_configured or not query or not query.strip():
            return []

        url = f"{self.BASE_URL}/search"
        params = {
            "ll": f"{lat},{lng}",
            "radius": 50000,
            "limit": min(max_results, 50),
            "query": query.strip(),
            "fields": "name,location,geocodes,rating,categories,photos",
        }

        try:
            resp = await self._get(url, params=params, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        places = []
        for r in data.get("results", []):
            fsq_id = r.get("fsq_id", "")
            if not fsq_id:
                continue
            loc = r.get("geocodes", {}).get("main", {})
            photo_url = None
            photos = r.get("photos") or []
            if photos:
                ph = photos[0]
                prefix = ph.get("prefix")
                suffix = ph.get("suffix")
                if prefix and suffix:
                    photo_url = f"{prefix}original{suffix}"
            places.append(
                Place(
                    id=f"foursquare:{fsq_id}",
                    name=r.get("name", "Unknown"),
                    address=r.get("location", {}).get("formatted_address"),
                    lat=loc.get("latitude"),
                    lng=loc.get("longitude"),
                    rating=r.get("rating"),
                    types=[c.get("name", "") for c in r.get("categories", [])],
                    source="foursquare",
                    photo_url=photo_url,
                )
            )
        return places

    async def get_place_details(self, place_id: str) -> PlaceDetail | None:
        """Get detailed info for a place."""
        if not self.is_configured:
            return None

        url = f"{self.BASE_URL}/{place_id}"
        try:
            resp = await self._get(url, headers=self._headers())
            resp.raise_for_status()
            r = resp.json()
        except Exception:
            return None

        loc = r.get("geocodes", {}).get("main", {})
        tips = []
        for t in r.get("tips", [])[:5]:
            text = t.get("text", "")
            if text:
                tips.append(text[:200] + ("..." if len(text) > 200 else ""))

        photo_url = None
        photos = r.get("photos") or []
        if photos:
            ph = photos[0]
            prefix = ph.get("prefix")
            suffix = ph.get("suffix")
            if prefix and suffix:
                photo_url = f"{prefix}original{suffix}"

        return PlaceDetail(
            id=f"foursquare:{place_id}",
            name=r.get("name", "Unknown"),
            address=r.get("location", {}).get("formatted_address"),
            lat=loc.get("latitude"),
            lng=loc.get("longitude"),
            rating=r.get("rating"),
            types=[c.get("name", "") for c in r.get("categories", [])],
            source="foursquare",
            photo_url=photo_url,
            website=r.get("website"),
            review_count=r.get("stats", {}).get("total_ratings"),
            reviews=tips,
        )

    async def get_vibe_data(self, place_id: str, place_name: str) -> dict | None:
        """Get rating/tips for vibe aggregation."""
        if not self.is_configured:
            return None

        detail = await self.get_place_details(place_id)
        if not detail:
            return None

        return {
            "rating": detail.rating,
            "review_count": detail.review_count,
            "reviews": detail.reviews,
        }
