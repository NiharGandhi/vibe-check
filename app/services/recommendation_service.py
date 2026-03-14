"""Vibe-based place recommendations."""

from __future__ import annotations

from typing import Iterable

from app.models.schemas import (
    Place,
    Recommendation,
    RecommendationsResponse,
    VibePreference,
)
from app.services.places_service import PlacesService
from app.services.vibe_service import VibeService


class RecommendationService:
    """Suggest places that match a desired vibe."""

    def __init__(self) -> None:
        self.places = PlacesService()
        self.vibes = VibeService()

    async def recommend_places(
        self,
        vibe: VibePreference,
        lat: float,
        lng: float,
        limit: int = 10,
    ) -> RecommendationsResponse:
        """
        Recommend places for a given vibe near lat/lng.

        Strategy:
        - Use nearby search to get a candidate list (already includes rating + types)
        - Score each place using existing data (no per-place vibe API calls)
        - Return top N sorted by score; vibe details fetched on-demand per place
        """
        candidates: list[Place] = await self.places.get_nearby_places(
            lat=lat,
            lng=lng,
            radius=2500,
            place_type="restaurant",
            max_results=max(limit * 2, 20),
        )
        if not candidates:
            return RecommendationsResponse(recommendations=[])

        return self.score_places_for_vibe_fast(vibe=vibe, places=candidates, limit=limit)

    def score_places_for_vibe_fast(
        self,
        vibe: VibePreference,
        places: Iterable[Place],
        limit: int | None = None,
    ) -> RecommendationsResponse:
        """
        Score an existing iterable of Place objects for a given vibe.

        This lets other services (like AI search) reuse the same fast-scoring logic
        on arbitrary candidate lists (e.g. text search results), without needing
        to perform their own nearby queries.
        """
        recs: list[Recommendation] = []
        for place in places:
            score, tags, reason = self._score_place_for_vibe_fast(vibe, place)
            if score > 0:
                recs.append(
                    Recommendation(
                        place=place,
                        vibe_tags=tags,
                        score=round(score, 3),
                        reason=reason,
                    )
                )

        recs.sort(key=lambda r: (r.score, r.place.rating or 0.0), reverse=True)
        if limit is None:
            return RecommendationsResponse(recommendations=recs)
        return RecommendationsResponse(recommendations=recs[:limit])

    def _score_place_for_vibe_fast(
        self,
        vibe: VibePreference,
        place: Place,
    ) -> tuple[float, list[str], str]:
        """Score a place using only data already available from search (no extra API calls)."""
        rating = place.rating or 0.0
        types = {t.lower() for t in (place.types or [])}
        is_bar   = any("bar" in t or "pub" in t for t in types)
        is_cafe  = any("cafe" in t or "coffee" in t for t in types)
        is_family = any("family" in t or "mall" in t or "food_court" in t for t in types)

        base = 0.2 + max(0.0, min(rating / 5.0, 1.0)) * 0.5
        tags: list[str] = []
        score = base

        if vibe is VibePreference.LIVELY:
            if is_bar:
                score += 0.2
                tags.append("Bar / drinks")
            if rating >= 4.0:
                tags.append("Highly rated")
        elif vibe is VibePreference.CHILL:
            if is_cafe:
                score += 0.2
                tags.append("Cafe / chill")
            else:
                tags.append("Quieter vibe")
        elif vibe is VibePreference.DATE_NIGHT:
            score += 0.15
            if rating >= 4.3:
                score += 0.1
                tags.append("Highly rated")
            if not is_bar and not is_family:
                tags.append("Date-friendly")
        elif vibe is VibePreference.GROUP:
            if is_bar or is_family:
                score += 0.15
            tags.append("Good for groups")
        elif vibe is VibePreference.WORK:
            if is_cafe:
                score += 0.2
                tags.append("Cafe / workspace")
            tags.append("Low key")
        elif vibe is VibePreference.FAMILY:
            if is_family:
                score += 0.2
            tags.append("Family-friendly")

        score = max(0.0, min(score, 1.0))
        if not tags:
            tags.append(vibe.value.replace("_", " ").title())
        reason = f"Rated {rating:.1f}/5" if rating else "Nearby pick"
        return score, tags, reason

    def _score_place_for_vibe(
        self,
        vibe: VibePreference,
        place: Place,
        vibe_data,
    ) -> tuple[float, list[str], str]:
        """Return (score, tags, reason) for this place."""
        rating = vibe_data.overall_score or place.rating or 0.0
        tags: list[str] = []
        base = 0.2 + max(0.0, min(rating / 5.0, 1.0)) * 0.4

        is_lively = bool(vibe_data.is_lively)
        live = vibe_data.live_busyness
        bt = vibe_data.besttime_info
        user = vibe_data.user_reports

        lively_score = 0.0
        if live:
            lively_score += live.live_busyness / 100.0
        if bt and bt.day_mean is not None:
            lively_score = max(lively_score, bt.day_mean / 100.0)
        if user and user.lively_pct is not None:
            lively_score = max(lively_score, user.lively_pct / 100.0)
        if is_lively:
            lively_score = max(lively_score, 0.6)

        # Simple heuristics based on types
        types = {t.lower() for t in (place.types or [])}
        is_bar = any("bar" in t or "pub" in t for t in types)
        is_cafe = any("cafe" in t or "coffee" in t for t in types)
        is_family = any("family" in t or "mall" in t or "food_court" in t for t in types)

        # Vibe-specific adjustments
        score = base

        if vibe is VibePreference.LIVELY:
            score += lively_score * 0.5
            if is_bar:
                score += 0.15
                tags.append("Bar / drinks")
            if lively_score >= 0.6:
                tags.append("Lively")
        elif vibe is VibePreference.CHILL:
            score += (1.0 - min(lively_score, 1.0)) * 0.4
            if is_cafe:
                score += 0.15
                tags.append("Cafe / chill")
            tags.append("Quieter vibe")
        elif vibe is VibePreference.DATE_NIGHT:
            score += 0.2
            if rating >= 4.3:
                score += 0.1
            if not is_bar and not is_family:
                tags.append("Date-friendly")
        elif vibe is VibePreference.GROUP:
            if is_bar or is_family:
                score += 0.2
            if lively_score >= 0.4:
                score += 0.1
            tags.append("Good for groups")
        elif vibe is VibePreference.WORK:
            if is_cafe:
                score += 0.2
                tags.append("Cafe / workspace")
            if lively_score <= 0.4:
                score += 0.1
                tags.append("Not too loud")
        elif vibe is VibePreference.FAMILY:
            if is_family:
                score += 0.2
            if lively_score <= 0.7:
                score += 0.05
            tags.append("Family-friendly")

        # Clamp and build reason
        score = max(0.0, min(score, 1.0))
        if not tags:
            tags.append(vibe.value.replace("_", " ").title())
        reason_parts: list[str] = []
        reason_parts.append(f"Rated {rating:.1f}/5")
        if live:
            reason_parts.append(f"currently {live.live_busyness:.0f}% busy ({live.status})")
        elif bt and bt.day_mean is not None:
            reason_parts.append(f"typically {bt.day_mean:.0f}% busy on this day")
        reason = " · ".join(reason_parts)
        return score, tags, reason


__all__ = ["RecommendationService"]

