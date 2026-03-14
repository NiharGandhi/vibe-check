"""Yelp Fusion API client."""

from app.clients.base import BaseAPIClient
from app.config import get_settings
from app.models.schemas import Place, PlaceDetail


TYPE_MAP = {
    "restaurant": "restaurants",
    "cafe": "cafes",
    "bar": "bars",
    "bakery": "bakeries",
    "food": "restaurants",
}


class YelpClient(BaseAPIClient):
    """Client for Yelp Fusion API v3."""

    BASE_URL = "https://api.yelp.com/v3"

    def __init__(self):
        super().__init__()
        self.api_key = get_settings().yelp_api_key

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
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

        term = TYPE_MAP.get(place_type.lower(), "restaurants")
        url = f"{self.BASE_URL}/businesses/search"
        params = {
            "latitude": lat,
            "longitude": lng,
            "radius": min(radius, 40000),
            "term": term,
            "limit": min(max_results, 50),
        }

        try:
            resp = await self._get(url, params=params, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        places = []
        for b in data.get("businesses", []):
            yelp_id = b.get("id", "")
            if not yelp_id:
                continue
            coords = b.get("coordinates", {})
            addr = b.get("location", {})
            addr_str = ", ".join(
                filter(
                    None,
                    [
                        addr.get("address1"),
                        addr.get("city"),
                        addr.get("state"),
                        addr.get("zip_code"),
                    ],
                )
            )
            places.append(
                Place(
                    id=f"yelp:{yelp_id}",
                    name=b.get("name", "Unknown"),
                    address=addr_str or b.get("display_address", [""])[0],
                    lat=coords.get("latitude"),
                    lng=coords.get("longitude"),
                    rating=b.get("rating"),
                    types=[c.get("title", "") for c in b.get("categories", [])],
                    source="yelp",
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

        url = f"{self.BASE_URL}/businesses/search"
        params = {
            "latitude": lat,
            "longitude": lng,
            "radius": 40000,
            "term": query.strip(),
            "limit": min(max_results, 50),
        }

        try:
            resp = await self._get(url, params=params, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        places = []
        for b in data.get("businesses", []):
            yelp_id = b.get("id", "")
            if not yelp_id:
                continue
            coords = b.get("coordinates", {})
            addr = b.get("location", {})
            addr_str = ", ".join(
                filter(
                    None,
                    [
                        addr.get("address1"),
                        addr.get("city"),
                        addr.get("state"),
                        addr.get("zip_code"),
                    ],
                )
            )
            places.append(
                Place(
                    id=f"yelp:{yelp_id}",
                    name=b.get("name", "Unknown"),
                    address=addr_str or b.get("display_address", [""])[0],
                    lat=coords.get("latitude"),
                    lng=coords.get("longitude"),
                    rating=b.get("rating"),
                    types=[c.get("title", "") for c in b.get("categories", [])],
                    source="yelp",
                )
            )
        return places

    async def _get_reviews(self, place_id: str) -> list[str]:
        """Fetch up to 5 review excerpts from Yelp."""
        if not self.is_configured:
            return []
        url = f"{self.BASE_URL}/businesses/{place_id}/reviews"
        try:
            resp = await self._get(url, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            return [r.get("text", "")[:200] for r in data.get("reviews", [])[:5] if r.get("text")]
        except Exception:
            return []

    async def get_place_details(self, place_id: str) -> PlaceDetail | None:
        """Get detailed info for a place."""
        if not self.is_configured:
            return None

        url = f"{self.BASE_URL}/businesses/{place_id}"
        try:
            resp = await self._get(url, headers=self._headers())
            resp.raise_for_status()
            b = resp.json()
        except Exception:
            return None

        reviews = await self._get_reviews(place_id)

        coords = b.get("coordinates", {})
        addr = b.get("location", {})
        addr_str = ", ".join(
            filter(
                None,
                [
                    addr.get("address1"),
                    addr.get("city"),
                    addr.get("state"),
                    addr.get("zip_code"),
                ],
            )
        )

        price = b.get("price")
        price_level = str(price) if price else None

        hours = []
        for day in b.get("hours", [{}])[0].get("open", [])[:7]:
            hours.append(
                f"{day.get('day', '')}: {day.get('start', '')}-{day.get('end', '')}"
            )

        return PlaceDetail(
            id=f"yelp:{place_id}",
            name=b.get("name", "Unknown"),
            address=addr_str or (b.get("display_address", [""])[0] if b.get("display_address") else None),
            lat=coords.get("latitude"),
            lng=coords.get("longitude"),
            rating=b.get("rating"),
            types=[c.get("title", "") for c in b.get("categories", [])],
            source="yelp",
            phone=b.get("display_phone"),
            website=b.get("url"),
            opening_hours=hours if hours else None,
            review_count=b.get("review_count"),
            reviews=reviews,
            price_level=price_level,
        )

    async def get_vibe_data(self, place_id: str, place_name: str) -> dict | None:
        """Get rating/reviews for vibe aggregation."""
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
