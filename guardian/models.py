"""Hybrid model router: each agent role picks OpenAI or Gemini.

OpenAI handles reasoning-heavy roles (orchestrator, decision, comms).
Gemini handles high-volume sub-agents (weather, intel summaries, fare normalisation).
Gemini is reached through its OpenAI-compatible endpoint, so every agent uses the same SDK.
"""

from functools import lru_cache
from typing import Literal

import httpx
from agents import (
    Model,
    ModelRetrySettings,
    ModelSettings,
    OpenAIChatCompletionsModel,
    retry_policies,
    set_tracing_disabled,
)
from openai import AsyncOpenAI

from guardian.config import settings
from guardian.keypool import KeyPool, KeyRotatingTransport, parse_keys

Provider = Literal["openai", "gemini", "gemini_lite"]

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Change routing here. This is the one place to rebalance cost vs. quality.
# Sub-agents use the lite model: each Gemini model has its own rate-limit quota.
ROLE_PROVIDER: dict[str, Provider] = {
    "orchestrator": "openai",
    "decision": "openai",
    "comms": "openai",
    "weather": "gemini_lite",
    "intel": "gemini_lite",
    "fares": "gemini_lite",
}


def _resolve(provider: Provider) -> Provider:
    s = settings()
    if provider == "openai" and not s.openai_api_key and s.gemini_api_key:
        return "gemini"  # fallback so the team can build before OpenAI credits arrive
    if provider != "openai" and not s.gemini_api_key and s.openai_api_key:
        return "openai"
    return provider


def _model_name(provider: Provider) -> str:
    s = settings()
    return {"openai": s.openai_model, "gemini": s.gemini_model, "gemini_lite": s.gemini_lite_model}[
        provider
    ]


def model_for(role: str) -> Model:
    s = settings()
    provider = _resolve(ROLE_PROVIDER.get(role, "gemini_lite"))
    if provider == "openai":
        if not s.openai_api_key:
            raise RuntimeError("Set OPENAI_API_KEY or GEMINI_API_KEY in .env")
        client = AsyncOpenAI(api_key=s.openai_api_key)
    else:
        client = gemini_client()
    return OpenAIChatCompletionsModel(model=_model_name(provider), openai_client=client)


@lru_cache
def gemini_pool() -> KeyPool:
    keys = parse_keys(settings().gemini_api_key)
    if not keys:
        raise RuntimeError("Set GEMINI_API_KEY or OPENAI_API_KEY in .env")
    return KeyPool(keys)


@lru_cache
def gemini_client() -> AsyncOpenAI:
    """One shared client: all Gemini agents use the same key pool, comma-separated in .env."""
    pool = gemini_pool()
    s = settings()
    fallbacks = {s.gemini_model: s.gemini_lite_model} if s.gemini_model != s.gemini_lite_model else {}
    transport = KeyRotatingTransport(pool, model_fallbacks=fallbacks)
    http = httpx.AsyncClient(transport=transport, timeout=120)
    # The transport sets the real key per request; api_key here is only a placeholder.
    return AsyncOpenAI(api_key=pool.key(0), base_url=GEMINI_BASE_URL, http_client=http)


def model_settings() -> ModelSettings:
    """Retry rate limits and transient errors with backoff (free tiers 429 quickly)."""
    return ModelSettings(
        retry=ModelRetrySettings(
            max_retries=6,
            backoff={"initial_delay": 4, "max_delay": 60, "multiplier": 2, "jitter": True},
            policy=retry_policies.any(
                retry_policies.retry_after(),
                retry_policies.http_status([429, 500, 502, 503, 504]),
                retry_policies.network_error(),
            ),
        )
    )


def describe_routing() -> dict[str, str]:
    out = {}
    for role, p in ROLE_PROVIDER.items():
        r = _resolve(p)
        out[role] = f"{r}:{_model_name(r)}"
    return out


def configure_tracing() -> None:
    # Agents SDK traces upload to OpenAI; disable when there is no OpenAI key.
    if not settings().openai_api_key:
        set_tracing_disabled(True)
