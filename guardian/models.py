"""Hybrid model router: each agent role picks OpenAI or Gemini.

OpenAI handles reasoning-heavy roles (orchestrator, decision, comms).
Gemini handles high-volume sub-agents (weather, intel summaries, fare normalisation).
Gemini is reached through its OpenAI-compatible endpoint, so every agent uses the same SDK.
"""

from typing import Literal

from agents import Model, OpenAIChatCompletionsModel, set_tracing_disabled
from openai import AsyncOpenAI

from guardian.config import settings

Provider = Literal["openai", "gemini"]

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Change routing here. This is the one place to rebalance cost vs. quality.
ROLE_PROVIDER: dict[str, Provider] = {
    "orchestrator": "openai",
    "decision": "openai",
    "comms": "openai",
    "weather": "gemini",
    "intel": "gemini",
    "fares": "gemini",
}


def _resolve(provider: Provider) -> Provider:
    s = settings()
    if provider == "openai" and not s.openai_api_key and s.gemini_api_key:
        return "gemini"  # fallback so the team can build before OpenAI credits arrive
    if provider == "gemini" and not s.gemini_api_key and s.openai_api_key:
        return "openai"
    return provider


def model_for(role: str) -> Model:
    s = settings()
    provider = _resolve(ROLE_PROVIDER.get(role, "gemini"))
    if provider == "openai":
        if not s.openai_api_key:
            raise RuntimeError("Set OPENAI_API_KEY or GEMINI_API_KEY in .env")
        client = AsyncOpenAI(api_key=s.openai_api_key)
        return OpenAIChatCompletionsModel(model=s.openai_model, openai_client=client)
    if not s.gemini_api_key:
        raise RuntimeError("Set GEMINI_API_KEY or OPENAI_API_KEY in .env")
    client = AsyncOpenAI(api_key=s.gemini_api_key, base_url=GEMINI_BASE_URL)
    return OpenAIChatCompletionsModel(model=s.gemini_model, openai_client=client)


def describe_routing() -> dict[str, str]:
    s = settings()
    out = {}
    for role, p in ROLE_PROVIDER.items():
        r = _resolve(p)
        out[role] = f"{r}:{s.openai_model if r == 'openai' else s.gemini_model}"
    return out


def configure_tracing() -> None:
    # Agents SDK traces upload to OpenAI; disable when there is no OpenAI key.
    if not settings().openai_api_key:
        set_tracing_disabled(True)
