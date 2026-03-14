"""Base HTTP client with retries."""

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


class BaseAPIClient:
    """Base async HTTP client with retry logic."""

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _get(self, url: str, **kwargs) -> httpx.Response:
        async with self._client() as client:
            return await client.get(url, **kwargs)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _post(self, url: str, **kwargs) -> httpx.Response:
        async with self._client() as client:
            return await client.post(url, **kwargs)
