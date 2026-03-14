"""REST API routes."""

from fastapi import APIRouter, HTTPException, Query

from app.db.vibe_reports import add_report
from app.models.schemas import AIChatRequest, AIChatResponse, PlacesResponse, RecommendationsResponse, VibePreference, VibeReportRequest, VibeResponse
from app.services import AISearchService, PlacesService, RecommendationService, VibeService
from app.clients.claude_client import ClaudeClient

router = APIRouter(prefix="/places", tags=["places"])
places_svc = PlacesService()
vibe_svc = VibeService()
reco_svc = RecommendationService()
ai_svc = AISearchService()
chat_claude = ClaudeClient()


@router.get("/nearby", response_model=PlacesResponse)
async def get_nearby_places(
    lat: float = Query(..., ge=-90, le=90, description="Latitude"),
    lng: float = Query(..., ge=-180, le=180, description="Longitude"),
    radius: int = Query(1500, ge=100, le=50000, description="Search radius in meters"),
    type: str = Query("restaurant", description="Place type: restaurant, cafe, bar, bakery"),
    limit: int = Query(20, ge=1, le=50, description="Max results"),
):
    """List places (restaurants, cafes, etc.) near the given location."""
    places = await places_svc.get_nearby_places(
        lat=lat,
        lng=lng,
        radius=radius,
        place_type=type,
        max_results=limit,
    )
    if not places:
        raise HTTPException(
            status_code=503,
            detail="No places found. Ensure at least one API key (Google, Foursquare, or Yelp) is configured.",
        )
    return PlacesResponse(places=places)


@router.get("/search", response_model=PlacesResponse)
async def search_places(
    q: str = Query(..., min_length=1, description="Search query (e.g. 'pizza', 'coffee shop')"),
    lat: float = Query(25.2048, ge=-90, le=90, description="Latitude (default: Dubai)"),
    lng: float = Query(55.2708, ge=-180, le=180, description="Longitude (default: Dubai)"),
    limit: int = Query(20, ge=1, le=50, description="Max results"),
):
    """Search for places by name or query near a location."""
    places = await places_svc.search_places(
        query=q,
        lat=lat,
        lng=lng,
        max_results=limit,
    )
    if not places:
        raise HTTPException(
            status_code=404,
            detail="No places found for that search. Try a different query.",
        )
    return PlacesResponse(places=places)


@router.get("/ai-search", response_model=PlacesResponse)
async def ai_search_places(
    q: str = Query(..., min_length=1, description="Natural language search, e.g. 'lively rooftop bar with live music'"),
    lat: float = Query(25.2048, ge=-90, le=90, description="Latitude (default: Dubai)"),
    lng: float = Query(55.2708, ge=-180, le=180, description="Longitude (default: Dubai)"),
    limit: int = Query(20, ge=1, le=50, description="Max results"),
):
    """
    AI-powered natural language search.

    Uses Claude (when configured) plus heuristics to interpret the query into a vibe
    and then reuses the recommendation engine to return the best matching places.
    Falls back gracefully when Claude is not configured.
    """
    from logging import getLogger

    logger = getLogger("uvicorn.error")
    logger.info("AI search request: q=%r lat=%s lng=%s limit=%s", q, lat, lng, limit)

    places = await ai_svc.ai_search(
        query=q,
        lat=lat,
        lng=lng,
        limit=limit,
    )
    if not places:
        raise HTTPException(
            status_code=404,
            detail="No places found for that search. Try a different query or area.",
        )
    return PlacesResponse(places=places)



@router.get("/recommend", response_model=RecommendationsResponse)
async def recommend_places(
    vibe: VibePreference = Query(VibePreference.LIVELY, description="Desired vibe"),
    lat: float = Query(25.2048, ge=-90, le=90, description="Latitude (default: Dubai)"),
    lng: float = Query(55.2708, ge=-180, le=180, description="Longitude (default: Dubai)"),
    limit: int = Query(8, ge=1, le=20, description="Max results"),
):
    """Recommend places that match the requested vibe."""
    recs = await reco_svc.recommend_places(
        vibe=vibe,
        lat=lat,
        lng=lng,
        limit=limit,
    )
    if not recs.recommendations:
        raise HTTPException(status_code=404, detail="No recommendations available right now. Try a different vibe or area.")
    return recs


@router.get("/{place_id}")
async def get_place_details(place_id: str):
    """Get detailed info for a single place."""
    detail = await places_svc.get_place_details(place_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Place not found")
    return detail


@router.get("/{place_id}/vibe", response_model=VibeResponse)
async def get_place_vibe(
    place_id: str,
    place_name: str | None = Query(None, description="Place name (optional)"),
):
    """Get vibe: ratings, reviews + real-time (live busyness, user check-ins). Answers: Is it lively? Fun? Good?"""
    vibe = await vibe_svc.get_vibe(place_id, place_name)
    return vibe


@router.post("/{place_id}/vibe-report")
async def submit_vibe_report(place_id: str, body: VibeReportRequest):
    """
    Submit real-time vibe check-in. Call this when you're AT the venue.
    Verifies advertised vs actual: lively, fun, good.
    """
    add_report(place_id, body.lively, body.fun, body.good)
    return {"status": "ok", "message": "Vibe report recorded. Thanks for the real-time check-in!"}


@router.post("/ai-chat", response_model=AIChatResponse)
async def ai_concierge_chat(body: AIChatRequest) -> AIChatResponse:
    """
    Lightweight AI concierge chat to help users decide what they want.

    This is intentionally single-turn: we send the current message and rely on Claude
    to ask clarifying questions or propose 1–3 concrete ideas.
    """
    from logging import getLogger

    logger = getLogger("uvicorn.error")

    if not chat_claude.is_configured:
        logger.info("AI chat requested but CLAUDE_API_KEY is not configured")
        raise HTTPException(status_code=503, detail="AI assistant is not configured right now.")

    # If the user's message already contains a clear intent (area + cuisine),
    # go straight to grounded suggestions using our own AI search instead of
    # asking further clarifying questions.
    msg_lower = body.message.lower()
    cuisine_keywords = [
        "indian",
        "mediterranean",
        "italian",
        "japanese",
        "asian",
        "steak",
        "burger",
        "seafood",
        "mexican",
        "arabic",
        "lebanese",
    ]
    area_keywords = [
        "business bay",
        "downtown",
        "difc",
        "dubai marina",
        "marina",
        "jumeirah",
        "dubai creek",
        "creek",
        "dubai mall",
        "city walk",
        "d3",
        "dubai design district",
    ]
    has_cuisine = any(k in msg_lower for k in cuisine_keywords)
    has_area = any(k in msg_lower for k in area_keywords)

    if has_cuisine and has_area:
        lat = body.lat if body.lat is not None else 25.2048
        lng = body.lng if body.lng is not None else 55.2708
        try:
            places = await ai_svc.ai_search(
                query=body.message,
                lat=lat,
                lng=lng,
                limit=5,
            )
        except Exception:
            logger.exception("AI concierge chat: failed calling ai_search, falling back to pure chat")
            places = []

        if places:
            lines: list[str] = []
            lines.append("Here are a few real spots that match what you described:")
            lines.append("You can tap a card or tweak the search above to see more options.")
            return AIChatResponse(reply="\n".join(lines), places=places[:3])

    system_prompt = (
        "You are VibeCheck's dining concierge for Dubai.\n"
        "- Your ONLY job is to help the user clarify their intent: area, cuisine, vibe, budget, and occasion.\n"
        "- NEVER invent or mention specific restaurant names or claim that a venue exists.\n"
        "- Talk only in terms of categories and search phrases like 'lively Indian with Burj views in Business Bay'.\n"
        "- Ask 1–2 short clarifying questions if their request is vague.\n"
        "- Keep replies under 5 short sentences; be direct and specific.\n"
        "- At the end, suggest 2–4 concrete SEARCH PHRASES using this exact format on separate lines:\n"
        "  [chip] Lively Indian with Burj views in Business Bay\n"
        "  [chip] Casual rooftop Mediterranean in Dubai Marina\n"
        "- These [chip] lines must be usable as queries for a search box, not as descriptions of confirmed venues."
    )

    headers = {
        "Content-Type": "application/json",
        "x-api-key": chat_claude.api_key,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": chat_claude.model,
        "max_tokens": 256,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": body.message},
        ],
    }

    try:
        resp = await chat_claude._post(chat_claude.API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content") or []
        text = ""
        if content and isinstance(content, list):
            block = content[0]
            if isinstance(block, dict):
                text = block.get("text", "") or ""
        if not text:
            text = "I'm here to help you narrow it down. Try telling me the area, cuisine, and vibe you're in the mood for."
    except Exception:
        logger.exception("AI concierge chat failed")
        text = "I'm having trouble reaching the AI concierge right now. Try again in a moment."

    return AIChatResponse(reply=text)
