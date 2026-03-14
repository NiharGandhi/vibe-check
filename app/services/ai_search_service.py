"""AI-powered natural language search for places."""

from __future__ import annotations

from app.clients.claude_client import ClaudeClient
from app.models.schemas import Place
from app.services.places_service import PlacesService
from app.services.recommendation_service import RecommendationService
from app.models.schemas import VibePreference


class AISearchService:
    """Use natural language + AI + heuristics to turn text into vibe-aware search."""

    def __init__(self) -> None:
        self.places = PlacesService()
        self.reco = RecommendationService()
        self.claude = ClaudeClient()

    async def ai_search(
        self,
        query: str,
        lat: float,
        lng: float,
        limit: int = 20,
    ) -> list[Place]:
        """
        Natural-language search endpoint.

        Strategy (kept robust and fast):
        - Use provider text search (Google/Foursquare) so cuisine, neighbourhood and other
          keywords in the query directly influence the candidate list.
        - Infer a high-level vibe preference (lively/chill/date night, etc.).
        - When Claude is configured, ask it to score how well each candidate matches the
          user's request using the place metadata (name, address, rating, types).
        - Fall back to fast heuristic scoring when Claude is unavailable or errors.
        """
        # 1) Use provider text search so cuisine + area words are understood.
        from logging import getLogger

        logger = getLogger("uvicorn.error")
        logger.info("AI search service: query=%r lat=%s lng=%s limit=%s", query, lat, lng, limit)
        candidates = await self.places.search_places(
            query=query,
            lat=lat,
            lng=lng,
            max_results=max(limit * 2, 40),
        )
        logger.info("AI search service: %d candidates from text search", len(candidates))
        if not candidates:
            # Nothing text-relevant found near this area
            return []

        # 2) Infer vibe preference from the query (cheap heuristic).
        vibe = await self._infer_vibe(query)

        # 3) If Claude is configured, let it verify and score a small subset of candidates.
        verified: list[Place] = []
        if self.claude.is_configured:
            top = candidates[: min(max(limit * 2, 10), 20)]
            summaries = [
                {
                    "id": p.id,
                    "name": p.name,
                    "address": p.address,
                    "rating": float(p.rating or 0.0),
                    "types": p.types,
                    "source": p.source,
                }
                for p in top
            ]
            logger.info("AI search service: sending %d summaries to Claude for verification", len(summaries))
            try:
                scores = await self.claude.score_places(query=query, places=summaries)
            except Exception:
                scores = None

            if scores:
                # Sort by Claude match score
                ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
                threshold = 0.5
                id_map = {p.id: p for p in top}
                for pid, score in ranked:
                    place = id_map.get(pid)
                    if not place:
                        continue
                    if score < threshold and len(verified) >= 3:
                        # Allow a few slightly-below-threshold matches but don't return junk.
                        continue
                    verified.append(place)
                    if len(verified) >= limit:
                        break
                logger.info(
                    "AI search service: Claude returned scores for %d places, using %d verified matches",
                    len(scores),
                    len(verified),
                )

        if verified:
            return verified

        # 4) Fallback: fast heuristic scoring on the text-search candidates.
        recs = self.reco.score_places_for_vibe_fast(vibe=vibe, places=candidates, limit=limit)
        logger.info("AI search service: returning %d fast-scored recommendations (fallback)", len(recs.recommendations))
        return [r.place for r in recs.recommendations]

    async def _infer_vibe(self, query: str) -> VibePreference:
        """Infer the closest VibePreference from the natural-language query."""
        # Simple heuristic classification based on keywords.
        q = query.lower()
        if any(k in q for k in ["club", "party", "live music", "dj", "dance", "shots", "drinks", "bar", "rooftop"]):
            return VibePreference.LIVELY
        if any(k in q for k in ["date", "anniversary", "romantic", "candle", "proposal"]):
            return VibePreference.DATE_NIGHT
        if any(k in q for k in ["cowork", "laptop", "work", "focus", "quiet cafe", "meeting"]):
            return VibePreference.WORK
        if any(k in q for k in ["family", "kids", "children", "mall", "brunch with kids"]):
            return VibePreference.FAMILY
        if any(k in q for k in ["group", "friends", "team", "office outing", "birthday"]):
            return VibePreference.GROUP
        if any(k in q for k in ["chill", "quiet", "relaxed", "cozy"]):
            return VibePreference.CHILL

        # Default: lively is a good baseline for going-out intent.
        return VibePreference.LIVELY


__all__ = ["AISearchService"]

