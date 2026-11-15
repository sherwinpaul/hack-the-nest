"""Round-robin API key failover at the HTTP layer.

Every request uses the pool's current key. On 429 (quota/rate limit) or 401/403
(bad or revoked key) the transport switches to the next key and retries the same
request immediately. If every key fails, the last response is returned so the
Agents SDK's backoff retry can take over.

Note: keys from the same Google Cloud project share one quota, so failover only
helps when keys come from different projects (e.g. teammates' keys).
"""

import threading

import httpx

ROTATE_ON = {401, 403, 429}


def parse_keys(raw: str) -> list[str]:
    return [k.strip() for k in raw.split(",") if k.strip()]


class KeyPool:
    def __init__(self, keys: list[str]):
        if not keys:
            raise ValueError("KeyPool needs at least one key")
        self.keys = keys
        self._i = 0
        self._lock = threading.Lock()

    @property
    def current(self) -> int:
        return self._i

    def key(self, i: int) -> str:
        return self.keys[i % len(self.keys)]

    def advance_from(self, i: int) -> int:
        """Move past key i (only if no other request already did) and return the new index."""
        with self._lock:
            if self._i == i % len(self.keys):
                self._i = (self._i + 1) % len(self.keys)
            return self._i


class KeyRotatingTransport(httpx.AsyncBaseTransport):
    def __init__(self, pool: KeyPool, inner: httpx.AsyncBaseTransport | None = None):
        self.pool = pool
        self.inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()  # keep the body so the request can be resent
        i = self.pool.current
        attempts = len(self.pool.keys)
        for attempt in range(attempts):
            request.headers["Authorization"] = f"Bearer {self.pool.key(i)}"
            request.stream = httpx.ByteStream(body)
            response = await self.inner.handle_async_request(request)
            if response.status_code not in ROTATE_ON:
                return response
            i = self.pool.advance_from(i)
            if attempt == attempts - 1:
                return response  # every key rejected: let the SDK back off and retry
            await response.aclose()
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        await self.inner.aclose()
