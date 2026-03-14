"""Service for aggregating place discovery from multiple APIs."""

import asyncio
from cachetools import TTLCache

from app.clients import FoursquareClient, GooglePlacesClient, YelpClient
from app.config import get_settings
from app.models.schemas import Place, PlaceDetail


class PlacesService:
    """Aggregates place discovery from Google, Foursquare, Yelp."""

    def __init__(self):
        self.google = GooglePlacesClient()
        self.foursquare = FoursquareClient()
        self.yelp = YelpClient()
        self.settings = get_settings()
        self._cache: TTLCache = TTLCache(maxsize=500, ttl=self.settings.cache_ttl_seconds)

    def _parse_place_id(self, place_id: str) -> tuple[str, str]:
        """Parse composite ID into (source, external_id)."""
        if ":" in place_id:
            source, ext_id = place_id.split(":", 1)
            return source.lower(), ext_id
        return "google", place_id  # default

    async def get_nearby_places(
        self,
        lat: float,
        lng: float,
        radius: int = 1500,
        place_type: str = "restaurant",
        max_results: int = 20,
    ) -> list[Place]:
        """Get places near location from first available source."""
        cache_key = f"nearby:{lat:.4f}:{lng:.4f}:{radius}:{place_type}:{max_results}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        priority = self.settings.get_place_sources_priority()
        clients = []
        if self.google.is_configured and "google" in priority:
            clients.append(("google", self.google))
        if self.foursquare.is_configured and "foursquare" in priority:
            clients.append(("foursquare", self.foursquare))
        if self.yelp.is_configured and "yelp" in priority:
            clients.append(("yelp", self.yelp))

        for _source, client in clients:
            try:
                places = await client.search_nearby(
                    lat=lat,
                    lng=lng,
                    radius=radius,
                    place_type=place_type,
                    max_results=max_results,
                )
                if places:
                    self._cache[cache_key] = places
                    return places
            except Exception:
                continue

        self._cache[cache_key] = []
        return []

    async def search_places(
        self,
        query: str,
        lat: float,
        lng: float,
        max_results: int = 20,
    ) -> list[Place]:
        """Search for places by text query near a location."""
        if not query or not query.strip():
            return []

        cache_key = f"search:{query.strip().lower()}:{lat:.4f}:{lng:.4f}:{max_results}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        priority = self.settings.get_place_sources_priority()
        clients = []
        if self.google.is_configured and "google" in priority:
            clients.append(("google", self.google))
        if self.foursquare.is_configured and "foursquare" in priority:
            clients.append(("foursquare", self.foursquare))
        if self.yelp.is_configured and "yelp" in priority:
            clients.append(("yelp", self.yelp))

        for _source, client in clients:
            try:
                places = await client.search_text(
                    query=query.strip(),
                    lat=lat,
                    lng=lng,
                    max_results=max_results,
                )
                if places:
                    self._cache[cache_key] = places
                    return places
            except Exception:
                continue

        self._cache[cache_key] = []
        return []

    async def get_place_details(self, place_id: str) -> PlaceDetail | None:
        """Get detailed info for a place by composite ID."""
        cache_key = f"detail:{place_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        source, ext_id = self._parse_place_id(place_id)

        detail = None
        if source == "google" and self.google.is_configured:
            detail = await self.google.get_place_details(ext_id)
        elif source == "foursquare" and self.foursquare.is_configured:
            detail = await self.foursquare.get_place_details(ext_id)
        elif source == "yelp" and self.yelp.is_configured:
            detail = await self.yelp.get_place_details(ext_id)

        if detail:
            self._cache[cache_key] = detail
        return detail
