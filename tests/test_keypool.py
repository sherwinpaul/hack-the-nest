import asyncio

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


def test_all_keys_exhausted_returns_429_for_sdk_backoff():
    pool = KeyPool(["k1", "k2"])
    up = FakeUpstream(exhausted={"k1", "k2"})
    assert _send(KeyRotatingTransport(pool, inner=up)) == 429
    assert up.seen == ["k1", "k2"]
