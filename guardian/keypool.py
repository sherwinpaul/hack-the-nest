"""Round-robin API key failover, plus model fallback, at the HTTP layer.

1. Key failover: each request uses the pool's current key. On 429 (quota/rate
   limit) or 401/403 (bad or revoked key) the transport switches to the next key
   and resends the same request immediately.
2. Model fallback: if every key returns 429 for a model that has a fallback
   (e.g. gemini-3.5-flash -> gemini-3.5-flash-lite), the request is rewritten to
   the fallback model and the keys are tried again. That model stays downgraded
   for a cool-down period, so later requests skip the exhausted one.
3. If nothing works, the last 429 is returned so the Agents SDK's backoff takes over.

Note: keys from the same Google Cloud project share one quota, so key failover
only helps when keys come from different projects (e.g. teammates' keys).
"""

import json
import logging
import threading
import time

import httpx

log = logging.getLogger("guardian.keypool")

ROTATE_ON = {401, 403, 429}
DOWNGRADE_SECONDS = 15 * 60


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
    def __init__(
        self,
        pool: KeyPool,
        inner: httpx.AsyncBaseTransport | None = None,
        model_fallbacks: dict[str, str] | None = None,
        clock=time.monotonic,
    ):
        self.pool = pool
        self.inner = inner or httpx.AsyncHTTPTransport()
        self.model_fallbacks = model_fallbacks or {}
        self._downgraded_until: dict[str, float] = {}
        self._clock = clock

    def _effective_model(self, model: str) -> str:
        """Follow fallbacks for models still inside their cool-down window."""
        seen = set()
        while model in self._downgraded_until and model not in seen:
            seen.add(model)
            if self._clock() >= self._downgraded_until[model]:
                del self._downgraded_until[model]
                break
            model = self.model_fallbacks.get(model, model)
        return model

    async def _try_all_keys(
        self, request: httpx.Request, body: bytes
    ) -> httpx.Response:
        i = self.pool.current
        attempts = len(self.pool.keys)
        for attempt in range(attempts):
            # Fresh request per attempt: httpx caches the body on the original after a read.
            headers = request.headers.copy()
            headers.pop("Content-Length", None)
            headers["Authorization"] = f"Bearer {self.pool.key(i)}"
            attempt_req = httpx.Request(
                request.method,
                request.url,
                headers=headers,
                content=body,
                extensions=request.extensions,
            )
            response = await self.inner.handle_async_request(attempt_req)
            if response.status_code not in ROTATE_ON:
                return response
            i = self.pool.advance_from(i)
            if attempt == attempts - 1:
                return response
            await response.aclose()
        raise AssertionError("unreachable")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()  # keep the body so the request can be resent
        payload = _json_or_none(body)
        model = payload.get("model") if payload else None

        if model:
            effective = self._effective_model(model)
            if effective != model:
                payload["model"] = effective
                body = json.dumps(payload).encode()
                model = effective

        tried = {model}
        while True:
            response = await self._try_all_keys(request, body)
            fallback = self.model_fallbacks.get(model) if model else None
            if response.status_code != 429 or not fallback or fallback in tried:
                return response
            tried.add(fallback)
            await response.aclose()
            log.warning(
                "All keys out of quota for %s; falling back to %s", model, fallback
            )
            self._downgraded_until[model] = self._clock() + DOWNGRADE_SECONDS
            payload["model"] = fallback
            body = json.dumps(payload).encode()
            model = fallback

    async def aclose(self) -> None:
        await self.inner.aclose()


def _json_or_none(body: bytes) -> dict | None:
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None
