"""Minimal Claude (Anthropic) client for AI-powered features."""

from __future__ import annotations

from typing import Any

from app.clients.base import BaseAPIClient
from app.config import get_settings


class ClaudeClient(BaseAPIClient):
    """Thin wrapper around Claude's messages API for lightweight classifications."""

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self) -> None:
        super().__init__(timeout=20.0)
        settings = get_settings()
        self.api_key: str | None = settings.claude_api_key
        # Default to a widely-available Claude 3 model; can be overridden later via settings if needed.
        self.model: str = "claude-3-haiku-20240307"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def classify_vibe(self, query: str) -> str | None:
        """
        Map a natural-language query to a VibePreference enum value using Claude.

        Returns one of: "lively", "chill", "date_night", "group", "work", "family",
        or None if classification fails.
        """
        if not self.is_configured:
            return None

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 64,
            "system": (
                "You receive a user's natural-language request for a place to go out.\n"
                "Classify it into exactly one of these vibe buckets and respond with ONLY "
                "the bucket id, nothing else:\n"
                "- lively\n- chill\n- date_night\n- group\n- work\n- family\n"
                "If uncertain, pick the closest match."
            ),
            "messages": [
                {"role": "user", "content": query},
            ],
        }

        try:
            resp = await self._post(self.API_URL, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return None

        try:
            # Anthropic messages API returns content as a list of blocks.
            text = (data.get("content") or [])[0].get("text", "")  # type: ignore[index]
        except Exception:
            return None

        norm = (text or "").strip().lower()
        allowed = {"lively", "chill", "date_night", "group", "work", "family"}
        return norm if norm in allowed else None

    async def score_places(self, query: str, places: list[dict[str, Any]]) -> dict[str, float] | None:
        """
        Given the user's free-text query and a list of place summaries, ask Claude
        to assign a 0-1 match score to each place.

        `places` should be a list of small dicts with at least:
        - id, name, address, area, rating, price_level, types, vibe_summary, highlights

        Returns a dict mapping place_id -> score (0-1), or None on failure.
        """
        from logging import getLogger

        logger = getLogger("uvicorn.error")

        if not self.is_configured:
            logger.info("Claude score_places called but CLAUDE_API_KEY is not configured")
            return None
        if not places:
            logger.info("Claude score_places called with no places")
            return None

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        system_prompt = (
            "You help a user pick venues that truly match their request.\n"
            "You are given the user's query and a list of candidate places with metadata.\n"
            "For each place, you must assign a numeric match score between 0.0 and 1.0, where:\n"
            "- 1.0 = extremely strong match to the query\n"
            "- 0.0 = clearly not suitable for the query\n"
            "Consider cuisine, neighbourhood/area, vibe/ambience, and any hints like live music or views.\n"
            "Reply ONLY with strict JSON of the form:\n"
            "{\n"
            '  "scores": [\n'
            '    {"id": "<place_id>", "score": 0.0},\n'
            "    ...\n"
            "  ]\n"
            "}\n"
            "Do not include any other text."
        )

        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 256,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "User query:\n"
                        f"{query.strip()}\n\n"
                        "Candidate places (JSON):\n"
                        f"{places}"
                    ),
                },
            ],
        }

        try:
            logger.info("Claude score_places: calling Anthropic with %d places (model=%s)", len(places), self.model)
            resp = await self._post(self.API_URL, json=body, headers=headers)
            status = resp.status_code
            text_body = resp.text
            logger.info("Claude score_places: HTTP %s, body preview=%r", status, text_body[:300])
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.exception("Claude score_places: request failed: %r", exc)
            return None

        try:
            text = (data.get("content") or [])[0].get("text", "")  # type: ignore[index]
        except Exception as exc:
            logger.exception("Claude score_places: failed to extract text content: %r", exc)
            return None

        if not text:
            logger.warning("Claude score_places: empty content text")
            return None

        import json
        import re

        try:
            parsed = json.loads(text)
        except Exception:
            # Claude sometimes returns JSON with minor issues (e.g. trailing commas or
            # truncated arrays). Try a light cleanup first, then fall back to a regex
            # extractor to salvage any well-formed id/score pairs, without surfacing
            # noisy stack traces in normal logs.
            logger.info("Claude score_places: primary JSON parse failed, attempting cleanup/regex fallback")
            cleaned = re.sub(r",(\s*])", r"\1", text)
            try:
                parsed = json.loads(cleaned)
                logger.info("Claude score_places: successfully parsed JSON after cleanup")
            except Exception:
                # As a last resort, extract id/score pairs via regex.
                pattern = r'"id"\s*:\s*"([^"]+)"\s*,\s*"score"\s*:\s*([0-9.]+)'
                matches = re.findall(pattern, text)
                if not matches:
                    logger.info("Claude score_places: regex extraction found no id/score pairs")
                    return None
                out_from_regex: dict[str, float] = {}
                for pid, score_str in matches:
                    try:
                        s = float(score_str)
                    except ValueError:
                        continue
                    if s < 0.0:
                        s = 0.0
                    if s > 1.0:
                        s = 1.0
                    out_from_regex[pid] = s
                if not out_from_regex:
                    logger.info("Claude score_places: regex extraction produced no valid scores")
                    return None
                logger.info(
                    "Claude score_places: using regex-extracted scores for %d places",
                    len(out_from_regex),
                )
                return out_from_regex

        scores_list = parsed.get("scores")
        if not isinstance(scores_list, list):
            logger.warning("Claude score_places: 'scores' key missing or not a list in response: %r", parsed)
            return None

        out: dict[str, float] = {}
        for item in scores_list:
            if not isinstance(item, dict):
                continue
            pid = item.get("id")
            score = item.get("score")
            if isinstance(pid, str) and isinstance(score, (int, float)):
                # Clamp just in case
                s = float(score)
                if s < 0.0:
                    s = 0.0
                if s > 1.0:
                    s = 1.0
                out[pid] = s

        if not out:
            logger.warning("Claude score_places: no valid scores extracted from response")
            return None

        logger.info("Claude score_places: got scores for %d places", len(out))
        return out

