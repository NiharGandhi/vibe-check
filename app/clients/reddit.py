"""Reddit API client via PRAW for social vibe data."""

from app.clients.base import BaseAPIClient
from app.config import get_settings


# Simple sentiment keywords
POSITIVE = {
    "great", "love", "best", "amazing", "excellent", "awesome", "good", "nice",
    "recommend", "fantastic", "delicious", "cozy", "friendly", "perfect",
}
NEGATIVE = {
    "bad", "terrible", "worst", "awful", "horrible", "disappointing", "avoid",
    "overpriced", "rude", "slow", "dirty", "mediocre",
}


class RedditClient:
    """Client for Reddit API via PRAW (sync - PRAW is sync-only). Region-aware subreddits."""

    def __init__(self):
        settings = get_settings()
        self.client_id = settings.reddit_client_id
        self.client_secret = settings.reddit_client_secret
        self.user_agent = settings.reddit_user_agent
        self._settings = settings

    def _get_subreddits(self) -> list[str]:
        """Region-aware subreddits (UAE: disabled; default: food, restaurants, city subs)."""
        return self._settings.get_reddit_subreddits()

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _get_reddit(self):
        """Create PRAW Reddit instance."""
        import praw
        return praw.Reddit(
            client_id=self.client_id,
            client_secret=self.client_secret,
            user_agent=self.user_agent,
        )

    async def search_place_mentions(
        self,
        place_name: str,
        limit: int = 25,
    ) -> dict:
        """
        Search Reddit for mentions of a place. Returns mentions, sentiment, and snippets.
        Runs in thread pool since PRAW is sync.
        """
        if not self.is_configured:
            return {"mentions": 0, "sentiment": None, "snippets": []}

        try:
            import asyncio
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: self._search_sync(place_name, limit))
        except Exception:
            return {"mentions": 0, "sentiment": None, "snippets": []}

    def _search_sync(self, place_name: str, limit: int) -> dict:
        """Synchronous Reddit search."""
        try:
            reddit = self._get_reddit()
            all_posts = []
            query = f'"{place_name}"'  # phrase search
            subreddits = self._get_subreddits()

            for sub in subreddits[:6]:  # Limit subreddits to avoid rate limit
                try:
                    subreddit = reddit.subreddit(sub)
                    for post in subreddit.search(query, limit=min(limit, 10), time_filter="year"):
                        text = f"{post.title} {post.selftext}"[:300]
                        all_posts.append({
                            "text": text,
                            "score": post.score,
                            "subreddit": sub,
                        })
                except Exception:
                    continue

            if not all_posts:
                return {"mentions": 0, "sentiment": "neutral", "snippets": []}

            # Simple sentiment
            pos_count = sum(1 for p in all_posts if any(w in p["text"].lower() for w in POSITIVE))
            neg_count = sum(1 for p in all_posts if any(w in p["text"].lower() for w in NEGATIVE))
            if pos_count > neg_count:
                sentiment = "positive"
            elif neg_count > pos_count:
                sentiment = "negative"
            else:
                sentiment = "neutral"

            snippets = [p["text"] for p in sorted(all_posts, key=lambda x: x["score"], reverse=True)[:5]]

            return {
                "mentions": len(all_posts),
                "sentiment": sentiment,
                "snippets": snippets,
            }
        except Exception:
            return {"mentions": 0, "sentiment": None, "snippets": []}
