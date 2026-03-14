"""Service for aggregating vibe data from multiple sources."""

import asyncio
from cachetools import TTLCache

from app.clients import BestTimeClient, FoursquareClient, GooglePlacesClient, RedditClient, YelpClient
from app.config import get_settings
from app.db.vibe_reports import get_besttime_venue_id, get_recent_reports, set_besttime_venue_id
from app.models.schemas import BestTimeInfo, LiveBusyness, ReviewHighlight, SourceRating, UserVibeReport, VibeResponse
from app.services.places_service import PlacesService


# Short TTL for real-time data (live busyness + user reports)
LIVE_CACHE_TTL = 90  # 90 seconds for "real-time" feel


class VibeService:
    """Aggregates vibe data: reviews + real-time (BestTime live busyness, user check-ins)."""

    def __init__(self):
        self.google = GooglePlacesClient()
        self.foursquare = FoursquareClient()
        self.yelp = YelpClient()
        self.reddit = RedditClient()
        self.besttime = BestTimeClient()
        self.settings = get_settings()
        self._cache: TTLCache = TTLCache(maxsize=200, ttl=LIVE_CACHE_TTL)

    def _parse_place_id(self, place_id: str) -> tuple[str, str]:
        """Parse composite ID into (source, external_id)."""
        if ":" in place_id:
            source, ext_id = place_id.split(":", 1)
            return source.lower(), ext_id
        return "google", place_id

    async def get_vibe(self, place_id: str, place_name: str | None = None) -> VibeResponse:
        """Get aggregated vibe data for a place."""
        cache_key = f"vibe:{place_id}"
        cached = self._cache.get(cache_key)

        if cached is not None:
            # Use cached for API data; always merge fresh user_reports below
            response = cached
        else:
            source, ext_id = self._parse_place_id(place_id)

            # Resolve place name and address (needed for BestTime live data)
            places_svc = PlacesService()
            detail = await places_svc.get_place_details(place_id)
            if detail:
                place_name = detail.name
                place_address = detail.address or ""
            else:
                place_name = place_name or "Unknown"
                place_address = ""

            # Fetch from all configured sources in parallel
            tasks = []
            if self.google.is_configured:
                tasks.append(("google", self.google.get_vibe_data(ext_id, place_name or "")))
            if self.yelp.is_configured:
                tasks.append(("yelp", self.yelp.get_vibe_data(ext_id, place_name or "")))
            if self.foursquare.is_configured:
                tasks.append(("foursquare", self.foursquare.get_vibe_data(ext_id, place_name or "")))
            if self.settings.is_reddit_enabled() and self.reddit.is_configured and place_name:
                tasks.append(("reddit", self.reddit.search_place_mentions(place_name)))
            if self.besttime.is_configured and place_name:
                cached_venue_id = get_besttime_venue_id(place_id)
                place_lat = detail.lat if detail else None
                place_lng = detail.lng if detail else None
                tasks.append((
                    "besttime",
                    self.besttime.get_live_busyness(
                        venue_name=place_name,
                        venue_address=place_address or "",
                        venue_id=cached_venue_id,
                        lat=place_lat,
                        lng=place_lng,
                    ),
                ))

            results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
            source_data = {name: r for (name, _), r in zip(tasks, results) if not isinstance(r, Exception) and r}

            # Build sources dict
            sources: dict[str, SourceRating] = {}
            all_ratings: list[float] = []
            all_highlights: list[str] = []
            all_highlights_with_dates: list[ReviewHighlight] = []

            # Real-time: BestTime live busyness + full analysis
            live_busyness = None
            besttime_info = None
            besttime_data = source_data.get("besttime")
            if besttime_data:
                if besttime_data.get("venue_id"):
                    set_besttime_venue_id(place_id, besttime_data["venue_id"])
                live_busyness = LiveBusyness(
                    live_busyness=besttime_data["live_busyness"],
                    status=besttime_data["status"],
                    is_lively=besttime_data["is_lively"],
                )
                besttime_info = BestTimeInfo(
                    live_busyness=besttime_data["live_busyness"],
                    status=besttime_data["status"],
                    is_lively=besttime_data["is_lively"],
                    busy_hours=besttime_data.get("busy_hours") or [],
                    peak_hours=besttime_data.get("peak_hours") or [],
                    quiet_hours=besttime_data.get("quiet_hours") or [],
                    day_mean=float(besttime_data["day_mean"]) if besttime_data.get("day_mean") is not None else None,
                    day_raw=[float(x) for x in raw] if isinstance(raw := besttime_data.get("day_raw"), list) else [],
                )

            # User reports fetched fresh below (never cached)
            user_reports = None
            is_lively = live_busyness.is_lively if live_busyness else None
            is_fun = None
            is_good = None

            for src_name, data in source_data.items():
                if src_name == "besttime":
                    continue  # Already handled above
                if src_name == "reddit":
                    sources["reddit"] = SourceRating(
                        mentions=data.get("mentions", 0),
                        sentiment=data.get("sentiment"),
                    )
                    all_highlights.extend(data.get("snippets", [])[:3])
                else:
                    rating = data.get("rating")
                    review_count = data.get("review_count")
                    reviews = data.get("reviews", [])
                    reviews_with_dates = data.get("reviews_with_dates", [])
                    if rating is not None:
                        all_ratings.append(rating)
                    sources[src_name] = SourceRating(
                        rating=rating,
                        review_count=review_count,
                    )
                    all_highlights.extend(reviews[:3])
                    for rwd in reviews_with_dates[:5]:
                        if isinstance(rwd, dict) and rwd.get("text"):
                            all_highlights_with_dates.append(
                                ReviewHighlight(text=rwd["text"], when=rwd.get("when"))
                            )

            # Compute overall score
            overall = None
            if all_ratings:
                overall = round(sum(all_ratings) / len(all_ratings), 1)

            # Build summary
            sentiment_parts = []
            reddit_src = sources.get("reddit")
            if reddit_src and reddit_src.sentiment:
                sentiment_parts.append(f"Reddit: {reddit_src.sentiment}")
            if overall is not None:
                sentiment_parts.append(f"Average rating: {overall}/5")
            rt_parts = []
            if live_busyness:
                rt_parts.append(f"Live: {live_busyness.status} ({live_busyness.live_busyness}% busy)")
            if rt_parts:
                sentiment_parts.insert(0, " | ".join(rt_parts))
            summary = ". ".join(sentiment_parts) if sentiment_parts else "No aggregated sentiment available."

            response = VibeResponse(
                place_id=place_id,
                place_name=place_name or "Unknown",
                overall_score=overall,
                sources=sources,
                recent_highlights=all_highlights[:10],
                recent_highlights_with_dates=all_highlights_with_dates[:10],
                summary=summary,
                live_busyness=live_busyness,
                besttime_info=besttime_info,
                user_reports=None,  # Fetched fresh below
                is_lively=is_lively,
                is_fun=is_fun,
                is_good=is_good,
            )
            self._cache[cache_key] = response

        # Always fetch user_reports fresh (real-time - never cached)
        user_reports_data = get_recent_reports(place_id)
        if user_reports_data["count"] > 0:
            user_reports = UserVibeReport(**user_reports_data)
            rt_parts = []
            if user_reports.lively_pct is not None:
                rt_parts.append(f"{user_reports.lively_pct:.0f}% lively")
            if user_reports.fun_pct is not None:
                rt_parts.append(f"{user_reports.fun_pct:.0f}% fun")
            if user_reports.good_pct is not None:
                rt_parts.append(f"{user_reports.good_pct:.0f}% good")
            rt_summary = f"Recent check-ins ({user_reports.count}): {', '.join(rt_parts)}"
            base_summary = response.summary
            if rt_summary not in base_summary:
                base_summary = f"{rt_summary}. {base_summary}"
            return VibeResponse(
                place_id=response.place_id,
                place_name=response.place_name,
                overall_score=response.overall_score,
                sources=response.sources,
                recent_highlights=response.recent_highlights,
                recent_highlights_with_dates=response.recent_highlights_with_dates,
                summary=base_summary,
                live_busyness=response.live_busyness,
                besttime_info=response.besttime_info,
                user_reports=user_reports,
                is_lively=user_reports.is_lively or response.is_lively,
                is_fun=user_reports.is_fun,
                is_good=user_reports.is_good,
            )

        return response
