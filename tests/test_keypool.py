import asyncio
import json

import httpx

from guardian.keypool import KeyPool, KeyRotatingTransport, parse_keys


class FakeUpstream(httpx.AsyncBaseTransport):
    """Returns 429 for exhausted keys, 200 otherwise; records which keys were tried."""

    def __init__(self, exhausted: set[str]):
        self.exhausted = exhausted
        self.seen: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = request.headers["Authorization"].removeprefix("Bearer ")
        self.seen.append(key)
        assert request.content == b'{"x":1}'  # body survives a resend
        return httpx.Response(429 if key in self.exhausted else 200)


def _send(transport: KeyRotatingTransport) -> int:
    async def go():
        async with httpx.AsyncClient(transport=transport) as c:
            return (await c.post("https://example.test", content=b'{"x":1}')).status_code

    return asyncio.run(go())


def test_parse_keys_strips_spaces_and_blanks():
    assert parse_keys(" a , b,,c ") == ["a", "b", "c"]


def test_fails_over_to_next_key_and_sticks():
    pool = KeyPool(["k1", "k2"])
    up = FakeUpstream(exhausted={"k1"})
    t = KeyRotatingTransport(pool, inner=up)
    assert _send(t) == 200
    assert up.seen == ["k1", "k2"]
    assert _send(t) == 200
    assert up.seen[-1] == "k2"  # stays on the working key


class ModelQuotaUpstream(httpx.AsyncBaseTransport):
    """429 for any key on exhausted models; records (key, model) per attempt."""

    def __init__(self, exhausted_models: set[str]):
        self.exhausted_models = exhausted_models
        self.seen: list[tuple[str, str]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = request.headers["Authorization"].removeprefix("Bearer ")
        model = json.loads(request.content)["model"]
        self.seen.append((key, model))
        return httpx.Response(429 if model in self.exhausted_models else 200, json={"model": model})


def _chat(transport: KeyRotatingTransport, model: str) -> httpx.Response:
    async def go():
        async with httpx.AsyncClient(transport=transport) as c:
            r = await c.post("https://example.test", json={"model": model, "messages": []})
            await r.aread()
            return r

    return asyncio.run(go())


FALLBACKS = {"flash": "flash-lite"}


def test_falls_back_to_lite_when_all_keys_out_of_quota():
    up = ModelQuotaUpstream(exhausted_models={"flash"})
    t = KeyRotatingTransport(KeyPool(["k1", "k2"]), inner=up, model_fallbacks=FALLBACKS)
    r = _chat(t, "flash")
    assert r.status_code == 200 and r.json()["model"] == "flash-lite"
    assert [m for _, m in up.seen] == ["flash", "flash", "flash-lite"]


def test_downgrade_is_sticky_then_expires():
    now = [0.0]
    up = ModelQuotaUpstream(exhausted_models={"flash"})
    t = KeyRotatingTransport(
        KeyPool(["k1", "k2"]), inner=up, model_fallbacks=FALLBACKS, clock=lambda: now[0]
    )
    _chat(t, "flash")
    up.seen.clear()
    _chat(t, "flash")
    assert up.seen == [("k1", "flash-lite")]  # skips the exhausted model entirely
    now[0] += 16 * 60
    up.exhausted_models.clear()
    up.seen.clear()
    assert _chat(t, "flash").json()["model"] == "flash"  # cool-down over, back to flash


def test_no_fallback_when_lite_also_exhausted():
    up = ModelQuotaUpstream(exhausted_models={"flash", "flash-lite"})
    t = KeyRotatingTransport(KeyPool(["k1"]), inner=up, model_fallbacks=FALLBACKS)
    assert _chat(t, "flash").status_code == 429


def test_all_keys_exhausted_returns_429_for_sdk_backoff():
    pool = KeyPool(["k1", "k2"])
    up = FakeUpstream(exhausted={"k1", "k2"})
    assert _send(KeyRotatingTransport(pool, inner=up)) == 429
    assert up.seen == ["k1", "k2"]
