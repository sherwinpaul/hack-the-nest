# Trip Guardian

A multi-agent system that protects your **meeting**, not just your flight. It watches weather and
the airline network along your whole route, finds evidence on the live web, ranks alternatives by
risk × meeting value × cost, and prepares the rebooking and a message to your host. You approve the
final step before anything is booked.

Built for Hack The Nest 2026: Future of Intelligence track (OpenAI + Exa).

## Architecture

- **Trip Guardian** (orchestrator, OpenAI) calls specialist agents as tools:
  - **Weather Risk** (Gemini): Open-Meteo forecasts for each airport on the route
  - **Web Intel** (Gemini + Exa MCP, `web_search_exa` / `web_fetch_exa`): live FAA, NWS, airline
    waiver and news evidence with cited sources. Exa runs in every mode; in replay it looks up the
    booked airline's real waiver and rebooking policy next to the recorded storm evidence
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
uv run uvicorn guardian.server:app --port 8000   # web dashboard → http://localhost:8000
uv run python -m guardian.cli --dry   # ranking only, no LLM
uv run python -m guardian.cli         # full multi-agent run in the terminal (replay storm scenario)
uv run pytest
```

## Dashboard

A light, product-style dashboard:

- **Recommendation**: the guardian's pick at a glance, with booked vs recommended on-time
  chance, extra cost, expected loss avoided, and the risk it routes around
- **Agent pipeline**: each agent's live status and the model it runs on
- **Route risk map** and **airport conditions** with disruption probability and the reason
- **Options**: ranked by expected loss, in each airport's local time; book the selection
  (simulated in replay, kiwi.com link in live mode)
- **Activity**: every agent and tool call, streamed live
- **Web evidence**: Exa sources as cards; **guardian brief** and an editable **message to host**
