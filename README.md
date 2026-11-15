# Trip Guardian

A multi-agent system that protects your **meeting**, not just your flight. It watches weather and
the airline network along your whole route, finds evidence on the live web, ranks alternatives by
risk × meeting value × cost, and prepares the rebooking and a message to your host. You approve the
final step before anything is booked.

Built for Hack The Nest 2026: Future of Intelligence track (OpenAI + Exa).

## Architecture

- **Trip Guardian** (orchestrator, OpenAI) calls specialist agents as tools:
  - **Weather Risk** (Gemini): Open-Meteo forecasts for each airport on the route
  - **Web Intel** (Gemini + Exa MCP): FAA, NWS, waiver and news evidence with sources
  - **Fare Search** (Gemini + Kiwi MCP / Duffel): alternative itineraries
  - **Comms** (OpenAI): drafts the message to the meeting host
- **Scoring** is deterministic code (`guardian/scoring.py`); the LLM only explains it.
- **Booking** runs only after user approval and uses Duffel test mode only.
- **Hybrid models**: per-role routing in `guardian/models.py`. Gemini goes through its
  OpenAI-compatible endpoint, so everything runs on the OpenAI Agents SDK.

## Run

```bash
uv sync
cp .env.example .env               # add GEMINI_API_KEY (and OPENAI_API_KEY, EXA_API_KEY)
uv run python -m guardian.cli --dry   # ranking only, no LLM
uv run python -m guardian.cli         # full multi-agent run (replay storm scenario)
uv run pytest
```

`DATA_MODE=replay` uses `scenarios/storm_ord.json` (sample data) for a deterministic demo;
`DATA_MODE=live` calls the real APIs and MCP servers.
