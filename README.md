# Vibe Check

A Zomato-like Python backend for discovering restaurants and places near you, with real-time "vibe" data aggregated from multiple APIs.

**Optimized for UAE**: Default region is UAE (Dubai, Abu Dhabi). Uses Google Places + Foursquare (Yelp and Reddit unavailable in UAE).

## Features

- **Place discovery**: Find restaurants, cafes, bars near a location (lat/lng)
- **Place details**: Get full info (address, hours, phone, reviews)
- **Vibe check**: Ratings, reviews + **real-time** (live busyness, user check-ins)
- **Real-time answers**: Is it lively? Fun? Good? (BestTime + crowdsourced)
- **Region-aware**: UAE preset (regionCode AE; Yelp and Reddit excluded)

## Quick Start

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Copy env template and add your API keys
cp .env.example .env
# Edit .env with at least one of: GOOGLE_PLACES_API_KEY, FOURSQUARE_API_KEY, YELP_API_KEY

# Run the server
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs for interactive API documentation.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Health check |
| GET | `/places/nearby` | List places near lat/lng |
| GET | `/places/{place_id}` | Place details |
| GET | `/places/{place_id}/vibe` | Vibe: ratings + real-time (live busyness, user reports) |
| POST | `/places/{place_id}/vibe-report` | Submit real-time check-in (lively, fun, good) |

### Example: Find nearby restaurants

```
GET /places/nearby?lat=40.7128&lng=-74.0060&radius=1500&type=restaurant&limit=20
```

### Example: Get vibe for a place

```
GET /places/google:ChIJ.../vibe
GET /places/yelp:abc123/vibe?place_name=Cafe+Example
```

## API Keys

| API | Where to Get | Free Tier | UAE |
|-----|--------------|-----------|-----|
| Google Places | [Cloud Console](https://console.cloud.google.com/) | $200/month credit | Yes |
| Foursquare | [Foursquare Developers](https://foursquare.com/developers/signup) | $200 credits + 10K calls | Yes |
| BestTime | [BestTime.app](https://besttime.app/) | 100 free credits | Yes (live busyness) |
| Yelp | [Yelp Fusion](https://www.yelp.com/developers/v3/manage_app) | Free | **No coverage** |
| Reddit | [Reddit Apps](https://www.reddit.com/prefs/apps) | Free (OAuth) | **Unavailable** |

**UAE mode** (`REGION=uae`): Uses Google + Foursquare. BestTime for live busyness. User check-ins for real-time vibe (lively, fun, good).

**Place IDs** use the format `{source}:{id}` (e.g., `google:ChIJ...`, `foursquare:abc123`).

## Project Structure

```
app/
├── main.py           # FastAPI app
├── config.py         # Settings from env
├── models/schemas.py # Pydantic models
├── api/routes.py     # REST endpoints
├── services/         # Business logic
└── clients/          # External API clients (Google, Foursquare, Yelp, Reddit)
```
