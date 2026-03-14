"""Pydantic request/response models."""

from enum import Enum

from pydantic import BaseModel, Field


class Place(BaseModel):
    """Place summary for list views."""

    id: str = Field(..., description="Composite ID: source:external_id")
    name: str
    photo_url: str | None = Field(
        default=None,
        description="Representative photo URL from the source (Google/Foursquare) when available.",
    )
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    rating: float | None = None
    types: list[str] = Field(default_factory=list)
    source: str


class PlaceDetail(Place):
    """Extended place info with reviews, phone, etc."""

    phone: str | None = None
    website: str | None = None
    opening_hours: list[str] | None = None
    review_count: int | None = None
    reviews: list[str] = Field(default_factory=list)
    reviews_with_dates: list[dict] = Field(default_factory=list)
    price_level: str | None = None


class PlaceNearbyQuery(BaseModel):
    """Query params for nearby search."""

    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    radius: int = Field(default=1500, ge=100, le=50000)
    type: str = Field(default="restaurant")


class PlacesResponse(BaseModel):
    """Response for nearby places."""

    places: list[Place]


class SourceRating(BaseModel):
    """Rating/review info from a single source."""

    rating: float | None = None
    review_count: int | None = None
    mentions: int | None = None
    sentiment: str | None = None


class LiveBusyness(BaseModel):
    """Real-time foot traffic from BestTime.app."""

    live_busyness: float = Field(..., description="0-100, current busyness")
    status: str = Field(..., description="lively|moderate|quiet|very_quiet")
    is_lively: bool = Field(..., description="True if busyness >= 50%")


class UserVibeReport(BaseModel):
    """Aggregated real-time user check-ins (last 4 hours)."""

    count: int = Field(..., description="Number of recent reports")
    lively_pct: float | None = None
    fun_pct: float | None = None
    good_pct: float | None = None
    is_lively: bool | None = None
    is_fun: bool | None = None
    is_good: bool | None = None


class VibeReportRequest(BaseModel):
    """User at venue reporting real vibe (advertising vs reality)."""

    lively: bool = Field(..., description="Is it lively right now?")
    fun: bool = Field(..., description="Is it fun?")
    good: bool = Field(..., description="Is it good?")


class ReviewHighlight(BaseModel):
    """Review excerpt with optional publish time."""

    text: str
    when: str | None = Field(None, description="e.g. '2 weeks ago', '3 months ago'")


class BestTimeInfo(BaseModel):
    """BestTime foot traffic data when available."""

    live_busyness: float = Field(..., description="0-100, current busyness (100%=weekly peak)")
    status: str = Field(..., description="lively|moderate|quiet|very_quiet")
    is_lively: bool = Field(..., description="True if busyness >= 50%")
    busy_hours: list[int] = Field(default_factory=list, description="Hours when busy (0-23)")
    peak_hours: list[dict] = Field(default_factory=list, description="Peak periods: peak_start, peak_max, peak_end")
    quiet_hours: list[int] = Field(default_factory=list, description="Hours when quiet")
    day_mean: float | None = Field(None, description="Average busyness for the day")
    day_raw: list[float] = Field(default_factory=list, description="Hourly forecast 0-23 (BestTime: index 0=6AM)")


class VibeResponse(BaseModel):
    """Aggregated vibe data for a place."""

    place_id: str
    place_name: str
    overall_score: float | None = None
    sources: dict[str, SourceRating] = Field(default_factory=dict)
    recent_highlights: list[str] = Field(default_factory=list)
    recent_highlights_with_dates: list[ReviewHighlight] = Field(
        default_factory=list,
        description="Reviews with publish time (e.g. '2 weeks ago')",
    )
    summary: str = ""

    # Real-time data
    live_busyness: LiveBusyness | None = Field(None, description="Current foot traffic (BestTime)")
    besttime_info: BestTimeInfo | None = Field(None, description="Full BestTime data when available")
    user_reports: UserVibeReport | None = Field(None, description="Recent user check-ins")
    is_lively: bool | None = Field(None, description="Real-time: lively? (from live + user reports)")
    is_fun: bool | None = Field(None, description="Real-time: fun? (from user reports)")
    is_good: bool | None = Field(None, description="Real-time: good? (from user reports)")


class VibePreference(str, Enum):
    """High-level vibe intent for recommendations."""

    CHILL = "chill"
    LIVELY = "lively"
    DATE_NIGHT = "date_night"
    GROUP = "group"
    WORK = "work"
    FAMILY = "family"


class Recommendation(BaseModel):
    """Recommended place with vibe metadata."""

    place: Place
    vibe_tags: list[str] = Field(default_factory=list)
    score: float = Field(..., description="Relative match score 0-1")
    reason: str = Field("", description="Short explanation for why it matches")


class RecommendationsResponse(BaseModel):
    """Response for vibe-based recommendations."""

    recommendations: list[Recommendation] = Field(default_factory=list)


class RecommendationRequest(BaseModel):
    """Optional body for future persisted preferences (kept minimal for now)."""

    vibe: VibePreference = Field(..., description="Desired vibe")


class AIChatRequest(BaseModel):
    """Request body for the on-site AI concierge chat."""

    message: str = Field(..., description="Latest user message about what they want")
    lat: float | None = Field(None, ge=-90, le=90, description="User latitude (optional, for grounded suggestions)")
    lng: float | None = Field(None, ge=-180, le=180, description="User longitude (optional, for grounded suggestions)")


class AIChatResponse(BaseModel):
    """Single-turn AI chat reply."""

    reply: str = Field(..., description="Assistant response to render in the chat UI")
    places: list[Place] | None = Field(
        None,
        description="Optional concrete place suggestions to render as cards (subset of Place fields).",
    )
