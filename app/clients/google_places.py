"""Google Places API (New) client."""

from app.clients.base import BaseAPIClient
from app.config import get_settings
from app.models.schemas import Place, PlaceDetail, SourceRating


# Map our type param to Google includedTypes
TYPE_MAP = {
    "restaurant": "restaurant",
    "cafe": "cafe",
    "bar": "bar",
    "bakery": "bakery",
    "meal_takeaway": "meal_takeaway",
    "meal_delivery": "meal_delivery",
    "food": "restaurant",  # fallback
}


class GooglePlacesClient(BaseAPIClient):
    """Client for Google Places API (New). Region-aware for UAE (regionCode: AE)."""

    BASE_URL = "https://places.googleapis.com/v1"

    def __init__(self):
        super().__init__()
        settings = get_settings()
        self.api_key = settings.google_places_api_key
        self._settings = settings

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

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

        included_type = TYPE_MAP.get(place_type.lower(), "restaurant")
        url = f"{self.BASE_URL}/places:searchNearby"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location,places.types,places.rating,places.userRatingCount,places.photos",
        }
        payload = {
            "includedTypes": [included_type],
            "maxResultCount": min(max_results, 20),
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": float(radius),
                }
            },
        }
        # Region-aware: UAE uses regionCode AE for local place names and results
        lang = self._settings.get_google_language_code()
        if lang:
            payload["languageCode"] = lang
        region = self._settings.get_google_region_code()
        if region:
            payload["regionCode"] = region

        try:
            resp = await self._post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        places = []
        for p in data.get("places", []):
            name = p.get("displayName", {}).get("text", "Unknown")
            loc = p.get("location", {})
            place_id = p.get("id", "")
            if not place_id:
                continue
            photo_url = None
            photos = p.get("photos") or []
            if photos:
                # New Places API photo access via media endpoint.
                # We intentionally include the API key here; in production you should
                # restrict this key to your backend or use a proxy endpoint.
                photo_name = photos[0].get("name")
                if photo_name:
                    photo_url = f"{self.BASE_URL}/{photo_name}/media?maxWidthPx=800&maxHeightPx=800&key={self.api_key}"
            places.append(
                Place(
                    id=f"google:{place_id}",
                    name=name,
                    address=p.get("formattedAddress"),
                    lat=loc.get("latitude"),
                    lng=loc.get("longitude"),
                    rating=p.get("rating"),
                    types=p.get("types", []),
                    source="google",
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

        url = f"{self.BASE_URL}/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location,places.types,places.rating,places.userRatingCount,places.photos",
        }
        payload = {
            "textQuery": query.strip(),
            "maxResultCount": min(max_results, 20),
            "locationBias": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": 50000.0,
                }
            },
        }
        lang = self._settings.get_google_language_code()
        if lang:
            payload["languageCode"] = lang
        region = self._settings.get_google_region_code()
        if region:
            payload["regionCode"] = region

        try:
            resp = await self._post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        places = []
        for p in data.get("places", []):
            name = p.get("displayName", {}).get("text", "Unknown")
            loc = p.get("location", {})
            place_id = p.get("id", "")
            if not place_id:
                continue
            photo_url = None
            photos = p.get("photos") or []
            if photos:
                photo_name = photos[0].get("name")
                if photo_name:
                    photo_url = f"{self.BASE_URL}/{photo_name}/media?maxWidthPx=800&maxHeightPx=800&key={self.api_key}"
            places.append(
                Place(
                    id=f"google:{place_id}",
                    name=name,
                    address=p.get("formattedAddress"),
                    lat=loc.get("latitude"),
                    lng=loc.get("longitude"),
                    rating=p.get("rating"),
                    types=p.get("types", []),
                    source="google",
                    photo_url=photo_url,
                )
            )
        return places

    async def get_place_details(self, place_id: str) -> PlaceDetail | None:
        """Get detailed info for a place. place_id should be the raw ID (no 'google:' prefix)."""
        if not self.is_configured:
            return None

        url = f"{self.BASE_URL}/places/{place_id}"
        params = {}
        lang = self._settings.get_google_language_code()
        if lang:
            params["languageCode"] = lang
        region = self._settings.get_google_region_code()
        if region:
            params["regionCode"] = region

        headers = {
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "id,displayName,formattedAddress,location,types,rating,userRatingCount,reviews,nationalPhoneNumber,websiteUri,regularOpeningHours,priceLevel,photos",
        }

        try:
            resp = await self._get(url, params=params, headers=headers)
            resp.raise_for_status()
            p = resp.json()
        except Exception:
            return None

        name = p.get("displayName", {}).get("text", "Unknown")
        loc = p.get("location", {})
        raw_id = p.get("id", place_id)

        reviews = []
        reviews_with_dates = []
        for r in p.get("reviews", [])[:5]:
            text = r.get("text", {}).get("text", "")
            if text:
                snippet = text[:200] + ("..." if len(text) > 200 else "")
                reviews.append(snippet)
                when = r.get("relativePublishTimeDescription")
                reviews_with_dates.append({"text": snippet, "when": when})

        hours = []
        for h in p.get("regularOpeningHours", {}).get("periods", [])[:7]:
            open_t = h.get("open", {}).get("hour")
            close_t = h.get("close", {}).get("hour")
            if open_t is not None and close_t is not None:
                hours.append(f"{open_t}:00-{close_t}:00")

        photo_url = None
        photos = p.get("photos") or []
        if photos:
            photo_name = photos[0].get("name")
            if photo_name:
                photo_url = f"{self.BASE_URL}/{photo_name}/media?maxWidthPx=1200&maxHeightPx=800&key={self.api_key}"

        return PlaceDetail(
            id=f"google:{raw_id}",
            name=name,
            address=p.get("formattedAddress"),
            lat=loc.get("latitude"),
            lng=loc.get("longitude"),
            rating=p.get("rating"),
            types=p.get("types", []),
            source="google",
            photo_url=photo_url,
            phone=p.get("nationalPhoneNumber"),
            website=p.get("websiteUri"),
            opening_hours=hours if hours else None,
            review_count=p.get("userRatingCount"),
            reviews=reviews,
            reviews_with_dates=reviews_with_dates,
            price_level=p.get("priceLevel"),
        )

    async def get_vibe_data(self, place_id: str, place_name: str) -> dict | None:
        """Get rating/review data for vibe aggregation."""
        if not self.is_configured:
            return None

        detail = await self.get_place_details(place_id)
        if not detail:
            return None

        return {
            "rating": detail.rating,
            "review_count": detail.review_count,
            "reviews": detail.reviews,
            "reviews_with_dates": detail.reviews_with_dates,
        }
